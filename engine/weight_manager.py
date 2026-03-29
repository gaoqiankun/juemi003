from __future__ import annotations

import asyncio
import shutil
import tarfile
import tempfile
import threading
import zipfile
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


class WeightManager:
    _PROGRESS_INTERVAL_SECONDS = 1.0

    def __init__(self, model_store: _ModelStoreProtocol, cache_dir: Path) -> None:
        self._model_store = model_store
        self._cache_dir = Path(cache_dir).expanduser()
        self._logger = structlog.get_logger(__name__)

    async def download(
        self,
        model_id: str,
        weight_source: str,
        model_path: str,
    ) -> str:
        normalized_source = _normalize_weight_source(weight_source)
        normalized_model_path = str(model_path).strip()
        if not normalized_model_path:
            raise ValueError("model_path is required")

        if normalized_source == "local":
            resolved_path = await self._resolve_local_path(normalized_model_path)
            await self._model_store.update_download_done(model_id, resolved_path)
            return resolved_path

        tracker = _ProgressTracker()
        await self._model_store.update_download_progress(model_id, 0, 0)
        stop_event = asyncio.Event()
        progress_task = asyncio.create_task(
            self._report_progress(model_id, tracker, stop_event),
            name=f"weight-progress-{model_id}",
        )
        try:
            if normalized_source == "huggingface":
                resolved_path = await self._download_from_huggingface(
                    model_id=model_id,
                    repo_id=normalized_model_path,
                    tracker=tracker,
                )
            elif normalized_source == "url":
                resolved_path = await self._download_from_url_archive(
                    model_id=model_id,
                    source_url=normalized_model_path,
                    tracker=tracker,
                )
            else:
                raise ValueError(f"unsupported weight source: {normalized_source}")
            await self._model_store.update_download_done(model_id, resolved_path)
            return resolved_path
        except asyncio.CancelledError:
            await self._model_store.update_download_error(model_id, "download canceled")
            raise
        except Exception as exc:
            await self._model_store.update_download_error(model_id, str(exc))
            raise
        finally:
            stop_event.set()
            await asyncio.gather(progress_task, return_exceptions=True)

    async def _resolve_local_path(self, model_path: str) -> str:
        candidate = Path(model_path).expanduser()
        if not candidate.exists():
            raise ValueError(f"local model path does not exist: {model_path}")
        return str(candidate.resolve())

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
