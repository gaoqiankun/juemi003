from __future__ import annotations

import asyncio
import shutil
import tarfile
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

import httpx
import structlog

try:
    from huggingface_hub import snapshot_download
except Exception:
    snapshot_download = None


class _ModelStoreProtocol(Protocol):
    async def update_download_progress(
        self,
        model_id: str,
        progress: int,
        speed_bps: int,
    ) -> dict | None:
        ...

    async def update_download_done(
        self,
        model_id: str,
        resolved_path: str,
    ) -> dict | None:
        ...

    async def update_download_error(
        self,
        model_id: str,
        error_message: str,
    ) -> dict | None:
        ...


class _DepStoreProtocol(Protocol):
    async def get_or_create(
        self,
        dep_id: str,
        hf_repo_id: str,
        *,
        revision: str | None = None,
    ) -> dict:
        ...

    async def get(self, dep_id: str) -> dict | None:
        ...

    async def update_status(self, dep_id: str, status: str) -> dict | None:
        ...

    async def update_done(self, dep_id: str, resolved_path: str) -> dict | None:
        ...

    async def update_error(self, dep_id: str, error: str) -> dict | None:
        ...


class _ModelDepRequirementsStoreProtocol(Protocol):
    async def link(self, model_id: str, dep_id: str) -> None:
        ...


@dataclass(frozen=True)
class ProviderDependency:
    dep_id: str
    hf_repo_id: str
    description: str = ""


class WeightManager:
    _PROGRESS_INTERVAL_SECONDS = 1.0

    def __init__(
        self,
        model_store: _ModelStoreProtocol,
        cache_dir: Path,
        *,
        dep_store: _DepStoreProtocol | None = None,
        model_dep_requirements_store: _ModelDepRequirementsStoreProtocol | None = None,
    ) -> None:
        self._model_store = model_store
        self._cache_dir = Path(cache_dir).expanduser()
        self._logger = structlog.get_logger(__name__)
        self._dep_store = dep_store
        self._model_dep_requirements_store = model_dep_requirements_store
        self._dep_locks: dict[str, asyncio.Lock] = {}

    async def download(
        self,
        model_id: str,
        provider_type: str,
        weight_source: str,
        model_path: str,
    ) -> str:
        normalized_source = _normalize_weight_source(weight_source)
        normalized_model_path = str(model_path).strip()
        normalized_provider_type = str(provider_type or "").strip().lower()
        if not normalized_model_path:
            raise ValueError("model_path is required")

        try:
            if normalized_source == "local":
                resolved_path = await self._resolve_local_path(normalized_model_path)
            else:
                resolved_path = await self._download_main(
                    model_id=model_id,
                    weight_source=normalized_source,
                    model_path=normalized_model_path,
                )
            await self._download_model_dependencies(model_id, normalized_provider_type)
            await self._model_store.update_download_done(model_id, resolved_path)
            return resolved_path
        except asyncio.CancelledError:
            await self._model_store.update_download_error(model_id, "download canceled")
            raise
        except Exception as exc:
            await self._model_store.update_download_error(model_id, str(exc))
            raise

    async def _resolve_local_path(self, model_path: str) -> str:
        candidate = Path(model_path).expanduser()
        if not candidate.exists():
            raise ValueError(f"local model path does not exist: {model_path}")
        return str(candidate.resolve())

    async def _download_main(
        self,
        *,
        model_id: str,
        weight_source: str,
        model_path: str,
    ) -> str:
        tracker = _ProgressTracker()
        await self._model_store.update_download_progress(model_id, 0, 0)
        stop_event = asyncio.Event()
        progress_task = asyncio.create_task(
            self._report_progress(model_id, tracker, stop_event),
            name=f"weight-progress-{model_id}",
        )
        try:
            if weight_source == "huggingface":
                return await self._download_from_huggingface(
                    model_id=model_id,
                    repo_id=model_path,
                    tracker=tracker,
                )
            if weight_source == "url":
                return await self._download_from_url_archive(
                    model_id=model_id,
                    source_url=model_path,
                    tracker=tracker,
                )
            raise ValueError(f"unsupported weight source: {weight_source}")
        finally:
            stop_event.set()
            await asyncio.gather(progress_task, return_exceptions=True)

    async def _download_model_dependencies(
        self,
        model_id: str,
        provider_type: str,
    ) -> None:
        if self._dep_store is None or self._model_dep_requirements_store is None:
            return
        provider_cls = _get_provider_class(provider_type)
        dependencies = _resolve_provider_dependencies(provider_cls)
        for dep in dependencies:
            await self._dep_store.get_or_create(dep.dep_id, dep.hf_repo_id)
            await self._model_dep_requirements_store.link(model_id, dep.dep_id)
        if snapshot_download is None:
            self._logger.warning(
                "weight.dependencies.download_skipped",
                reason="huggingface_hub unavailable",
                provider_type=provider_type,
                model_id=model_id,
            )
            return
        for dep in dependencies:
            try:
                await self._download_dep_once(dep)
            except Exception as exc:
                raise RuntimeError(f"dep_{dep.dep_id}: {exc}") from exc

    async def _download_dep_once(self, dep: ProviderDependency) -> None:
        if self._dep_store is None:
            return
        dep_lock = self._dep_locks.get(dep.dep_id)
        if dep_lock is None:
            dep_lock = asyncio.Lock()
            self._dep_locks[dep.dep_id] = dep_lock
        async with dep_lock:
            existing = await self._dep_store.get(dep.dep_id)
            if existing is not None and str(existing.get("download_status") or "").lower() == "done":
                return
            await self._dep_store.update_status(dep.dep_id, "downloading")
            try:
                resolved_path = await self._download_dep(dep)
            except Exception as exc:
                await self._dep_store.update_error(dep.dep_id, str(exc))
                raise
            await self._dep_store.update_done(dep.dep_id, resolved_path)

    async def _download_dep(self, dep: ProviderDependency) -> str:
        if snapshot_download is None:
            raise RuntimeError("huggingface_hub is not available")

        def _run_download() -> str:
            return snapshot_download(repo_id=dep.hf_repo_id, local_dir=None)

        resolved_path = await asyncio.to_thread(_run_download)
        resolved_candidate = Path(str(resolved_path)).expanduser()
        if not _directory_has_entries(resolved_candidate):
            raise ValueError(f"downloaded dependency repository is empty: {dep.hf_repo_id}")
        if not _snapshot_has_model_weights(resolved_candidate):
            raise ValueError(f"downloaded dependency has no model weights: {dep.hf_repo_id}")
        return str(resolved_candidate.resolve())

    async def _download_from_huggingface(
        self,
        *,
        model_id: str,
        repo_id: str,
        tracker: "_ProgressTracker",
    ) -> str:
        if snapshot_download is None:
            raise RuntimeError("huggingface_hub is not available")
        target_dir = self._prepare_target_dir(model_id)
        progress_factory = _build_hf_progress_class(tracker)

        def _run_download() -> None:
            kwargs = {
                "repo_id": repo_id,
                "local_dir": str(target_dir),
                "tqdm_class": progress_factory,
            }
            try:
                snapshot_download(**kwargs)
            except TypeError as exc:
                if "tqdm_class" not in str(exc):
                    raise
                snapshot_download(
                    repo_id=repo_id,
                    local_dir=str(target_dir),
                )

        await asyncio.to_thread(_run_download)
        if not _directory_has_entries(target_dir):
            raise ValueError(f"downloaded HuggingFace repository is empty: {repo_id}")
        return str(target_dir)

    async def _download_from_url_archive(
        self,
        *,
        model_id: str,
        source_url: str,
        tracker: "_ProgressTracker",
    ) -> str:
        archive_format = _detect_archive_format(source_url)
        if archive_format is None:
            raise ValueError(
                "url source only supports .zip and .tar.gz archives"
            )
        target_dir = self._prepare_target_dir(model_id)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix=f"{_cache_key(model_id)}-",
            dir=str(self._cache_dir),
        ) as tmp_dir:
            archive_name = f"weights{archive_format}"
            archive_path = Path(tmp_dir) / archive_name
            await self._stream_download(source_url, archive_path, tracker)
            await asyncio.to_thread(
                _extract_archive,
                archive_path,
                target_dir,
            )

        if not _directory_has_entries(target_dir):
            raise ValueError("archive extracted successfully but target directory is empty")
        return str(target_dir)

    async def _stream_download(
        self,
        source_url: str,
        destination_path: Path,
        tracker: "_ProgressTracker",
    ) -> None:
        timeout = httpx.Timeout(connect=30.0, read=60.0, write=60.0, pool=30.0)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            async with client.stream("GET", source_url) as response:
                response.raise_for_status()
                tracker.set_total(_parse_content_length(response.headers.get("content-length")))
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                with destination_path.open("wb") as destination_file:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        destination_file.write(chunk)
                        tracker.add_completed(len(chunk))
        if destination_path.stat().st_size <= 0:
            raise ValueError("downloaded archive is empty")

    async def _report_progress(
        self,
        model_id: str,
        tracker: "_ProgressTracker",
        stop_event: asyncio.Event,
    ) -> None:
        loop = asyncio.get_running_loop()
        last_time = loop.time()
        last_completed = 0
        while not stop_event.is_set():
            await asyncio.sleep(self._PROGRESS_INTERVAL_SECONDS)
            total_bytes, completed_bytes = tracker.snapshot()
            current_time = loop.time()
            elapsed = max(current_time - last_time, 1e-6)
            delta = max(0, completed_bytes - last_completed)
            speed_bps = int(delta / elapsed)
            progress = _calculate_progress(total_bytes, completed_bytes)
            await self._model_store.update_download_progress(
                model_id,
                progress,
                speed_bps,
            )
            last_time = current_time
            last_completed = completed_bytes

    def _prepare_target_dir(self, model_id: str) -> Path:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        target_dir = self._cache_dir / _cache_key(model_id)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        return target_dir


class _ProgressTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._total_bytes: int | None = None
        self._completed_bytes: int = 0
        self._next_bar_id = 1
        self._bars: dict[int, tuple[int | None, int]] = {}

    def set_total(self, total_bytes: int | None) -> None:
        with self._lock:
            self._total_bytes = total_bytes if total_bytes and total_bytes > 0 else None

    def add_completed(self, byte_count: int) -> None:
        if byte_count <= 0:
            return
        with self._lock:
            self._completed_bytes += int(byte_count)

    def add_hf_bar(self, total: object) -> int:
        with self._lock:
            bar_id = self._next_bar_id
            self._next_bar_id += 1
            normalized_total = _normalize_positive_int(total)
            self._bars[bar_id] = (normalized_total, 0)
            self._recompute_hf_totals_locked()
            return bar_id

    def update_hf_bar(self, bar_id: int, delta: object) -> None:
        normalized_delta = _normalize_positive_int(delta)
        if normalized_delta <= 0:
            return
        with self._lock:
            total, completed = self._bars.get(bar_id, (None, 0))
            next_completed = completed + normalized_delta
            if total is not None:
                next_completed = min(next_completed, total)
            self._bars[bar_id] = (total, next_completed)
            self._recompute_hf_totals_locked()

    def close_hf_bar(self, bar_id: int) -> None:
        with self._lock:
            total, completed = self._bars.get(bar_id, (None, 0))
            if total is not None and completed < total:
                self._bars[bar_id] = (total, total)
            self._recompute_hf_totals_locked()

    def snapshot(self) -> tuple[int | None, int]:
        with self._lock:
            return self._total_bytes, self._completed_bytes

    def _recompute_hf_totals_locked(self) -> None:
        totals: list[int] = []
        completed_sum = 0
        for total, completed in self._bars.values():
            if total is None:
                self._total_bytes = None
                self._completed_bytes = max(self._completed_bytes, completed_sum + completed)
                return
            totals.append(total)
            completed_sum += min(completed, total)
        self._total_bytes = sum(totals) if totals else None
        self._completed_bytes = completed_sum


def _build_hf_progress_class(tracker: _ProgressTracker):
    class _HFProgressTqdm:
        def __init__(self, *args, **kwargs) -> None:
            del args
            self.total = kwargs.get("total")
            self.n = 0
            self._bar_id = tracker.add_hf_bar(self.total)

        def update(self, value=1):
            delta = _normalize_positive_int(value)
            self.n += delta
            tracker.update_hf_bar(self._bar_id, delta)
            return self.n

        def close(self) -> None:
            tracker.close_hf_bar(self._bar_id)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb
            self.close()

        def set_description(self, *args, **kwargs) -> None:
            del args, kwargs

        def set_postfix(self, *args, **kwargs) -> None:
            del args, kwargs

        def refresh(self, *args, **kwargs) -> None:
            del args, kwargs

    return _HFProgressTqdm


def _extract_archive(archive_path: Path, destination: Path) -> None:
    suffix = archive_path.name.lower()
    destination.mkdir(parents=True, exist_ok=True)
    if suffix.endswith(".zip"):
        _extract_zip(archive_path, destination)
        return
    if suffix.endswith(".tar.gz"):
        _extract_tar_gz(archive_path, destination)
        return
    raise ValueError("url source only supports .zip and .tar.gz archives")


def _extract_zip(archive_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not members:
            raise ValueError("zip archive is empty")
        destination_root = destination.resolve()
        for member in members:
            member_path = (destination / member.filename).resolve()
            if not _is_relative_to(member_path, destination_root):
                raise ValueError("zip archive contains paths outside target directory")
        archive.extractall(destination)


def _extract_tar_gz(archive_path: Path, destination: Path) -> None:
    with tarfile.open(archive_path, mode="r:gz") as archive:
        members = archive.getmembers()
        if not members:
            raise ValueError("tar.gz archive is empty")
        destination_root = destination.resolve()
        for member in members:
            member_path = (destination / member.name).resolve()
            if not _is_relative_to(member_path, destination_root):
                raise ValueError("tar.gz archive contains paths outside target directory")
        archive.extractall(destination)


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
    except (StopIteration, FileNotFoundError):
        return False
    return True


def _snapshot_has_model_weights(path: Path) -> bool:
    if not path.exists() or not path.is_dir():
        return False
    for pattern in (
        "*.safetensors",
        "pytorch_model*.bin",
        "model.ckpt*",
        "tf_model.h5",
        "flax_model.msgpack",
    ):
        try:
            next(path.rglob(pattern))
        except StopIteration:
            continue
        return True
    return False


def _parse_content_length(value: str | None) -> int | None:
    normalized = _normalize_positive_int(value)
    return normalized if normalized > 0 else None


def _calculate_progress(total_bytes: int | None, completed_bytes: int) -> int:
    if total_bytes is None or total_bytes <= 0:
        return 0
    progress = int((completed_bytes / total_bytes) * 100)
    return max(0, min(99, progress))


def _detect_archive_format(source_url: str) -> str | None:
    path = urlsplit(str(source_url)).path.strip().lower()
    if path.endswith(".tar.gz"):
        return ".tar.gz"
    if path.endswith(".zip"):
        return ".zip"
    return None


def _normalize_positive_int(value: object) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


def _cache_key(model_id: str) -> str:
    normalized = str(model_id).strip()
    if not normalized:
        raise ValueError("model_id is required")
    return normalized.replace("/", "_").replace("\\", "_")


def _normalize_weight_source(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in {"huggingface", "url", "local"}:
        raise ValueError(
            "weight_source must be one of: huggingface, url, local"
        )
    return normalized


def _get_provider_class(provider_type: str):
    normalized_provider_type = str(provider_type or "").strip().lower()
    if normalized_provider_type == "trellis2":
        from gen3d.model.trellis2.provider import Trellis2Provider

        return Trellis2Provider
    if normalized_provider_type == "step1x3d":
        from gen3d.model.step1x3d.provider import Step1X3DProvider

        return Step1X3DProvider
    if normalized_provider_type == "hunyuan3d":
        from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider

        return Hunyuan3DProvider
    return None


def _resolve_provider_dependencies(provider_cls) -> list[ProviderDependency]:
    if provider_cls is None:
        return []
    dependencies_getter = getattr(provider_cls, "dependencies", lambda: [])
    raw_dependencies = dependencies_getter() or []
    normalized_dependencies: list[ProviderDependency] = []
    for item in raw_dependencies:
        dep = _normalize_provider_dependency(item)
        if dep is not None:
            normalized_dependencies.append(dep)
    return normalized_dependencies


def _normalize_provider_dependency(item: object) -> ProviderDependency | None:
    if isinstance(item, dict):
        raw_dep_id = item.get("dep_id")
        raw_hf_repo_id = item.get("hf_repo_id")
        raw_description = item.get("description")
    else:
        raw_dep_id = getattr(item, "dep_id", None)
        raw_hf_repo_id = getattr(item, "hf_repo_id", None)
        raw_description = getattr(item, "description", "")
    dep_id = str(raw_dep_id or "").strip()
    hf_repo_id = str(raw_hf_repo_id or "").strip()
    if not dep_id or not hf_repo_id:
        return None
    return ProviderDependency(
        dep_id=dep_id,
        hf_repo_id=hf_repo_id,
        description=str(raw_description or "").strip(),
    )
