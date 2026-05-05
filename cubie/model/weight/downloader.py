from __future__ import annotations

import asyncio
import tempfile
import threading
from pathlib import Path

import httpx

try:
    from huggingface_hub import snapshot_download
except Exception:
    snapshot_download = None

from .archive import (
    detect_archive_format,
    directory_has_entries,
    extract_archive,
    snapshot_has_model_weights,
)


class DownloaderMixin:
    async def download(
        self,
        model_id: str,
        provider_type: str,
        weight_source: str,
        model_path: str,
        dep_assignments: dict[str, dict] | None = None,
    ) -> str:
        from . import cache_key, normalize_weight_source

        normalized_source = normalize_weight_source(weight_source)
        normalized_model_path = str(model_path).strip()
        normalized_provider_type = str(provider_type or "").strip().lower()
        if not normalized_model_path:
            raise ValueError("model_path is required")

        try:
            if normalized_source == "local":
                resolved_path = await self.resolve_local_path(normalized_model_path)
            else:
                target_dir = self._cache_dir / cache_key(model_id)
                if target_dir.is_dir() and snapshot_has_model_weights(target_dir):
                    resolved_path = str(target_dir.resolve())
                else:
                    resolved_path = await self.download_main(
                        model_id=model_id,
                        weight_source=normalized_source,
                        model_path=normalized_model_path,
                    )
            await self.download_model_dependencies(
                model_id,
                normalized_provider_type,
                dep_assignments=dep_assignments,
            )
            await self._model_store.update_download_done(model_id, resolved_path)
            return resolved_path
        except asyncio.CancelledError:
            await self._model_store.update_download_error(model_id, "download canceled")
            raise
        except Exception as exc:
            await self._model_store.update_download_error(model_id, str(exc))
            raise

    async def download_main(
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
            self.report_progress(model_id, tracker, stop_event),
            name=f"weight-progress-{model_id}",
        )
        try:
            if weight_source == "huggingface":
                return await self.download_from_huggingface(
                    model_id=model_id,
                    repo_id=model_path,
                )
            if weight_source == "url":
                return await self.download_from_url_archive(
                    model_id=model_id,
                    source_url=model_path,
                    tracker=tracker,
                )
            raise ValueError(f"unsupported weight source: {weight_source}")
        finally:
            stop_event.set()
            await asyncio.gather(progress_task, return_exceptions=True)

    async def download_from_huggingface(
        self,
        *,
        model_id: str,
        repo_id: str,
    ) -> str:
        if snapshot_download is None:
            raise RuntimeError("huggingface_hub is not available")
        target_dir = self.prepare_target_dir(model_id)

        await asyncio.to_thread(
            lambda: snapshot_download(repo_id=repo_id, local_dir=str(target_dir))
        )
        if not directory_has_entries(target_dir):
            raise ValueError(f"downloaded HuggingFace repository is empty: {repo_id}")
        return str(target_dir)

    async def download_from_url_archive(
        self,
        *,
        model_id: str,
        source_url: str,
        tracker: "_ProgressTracker",
    ) -> str:
        from . import cache_key

        archive_format = detect_archive_format(source_url)
        if archive_format is None:
            raise ValueError(
                "url source only supports .zip and .tar.gz archives"
            )
        target_dir = self.prepare_target_dir(model_id)
        self._cache_dir.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(
            prefix=f"{cache_key(model_id)}-",
            dir=str(self._cache_dir),
        ) as tmp_dir:
            archive_name = f"weights{archive_format}"
            archive_path = Path(tmp_dir) / archive_name
            await self.stream_download(source_url, archive_path, tracker)
            await asyncio.to_thread(
                extract_archive,
                archive_path,
                target_dir,
            )

        if not directory_has_entries(target_dir):
            raise ValueError("archive extracted successfully but target directory is empty")
        return str(target_dir)

    async def stream_download(
        self,
        source_url: str,
        destination_path: Path,
        tracker: "_ProgressTracker",
    ) -> None:
        timeout = httpx.Timeout(connect=30.0, read=60.0, write=60.0, pool=30.0)
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            async with client.stream("GET", source_url) as response:
                response.raise_for_status()
                tracker.set_total(parse_content_length(response.headers.get("content-length")))
                destination_path.parent.mkdir(parents=True, exist_ok=True)
                with destination_path.open("wb") as destination_file:
                    async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                        if not chunk:
                            continue
                        destination_file.write(chunk)
                        tracker.add_completed(len(chunk))
        if destination_path.stat().st_size <= 0:
            raise ValueError("downloaded archive is empty")

    async def report_progress(
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
            progress = calculate_progress(total_bytes, completed_bytes)
            await self._model_store.update_download_progress(
                model_id,
                progress,
                speed_bps,
            )
            last_time = current_time
            last_completed = completed_bytes


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
            normalized_total = normalize_positive_int(total)
            self._bars[bar_id] = (normalized_total, 0)
            self.recompute_hf_totals_locked()
            return bar_id

    def update_hf_bar(self, bar_id: int, delta: object) -> None:
        normalized_delta = normalize_positive_int(delta)
        if normalized_delta <= 0:
            return
        with self._lock:
            total, completed = self._bars.get(bar_id, (None, 0))
            next_completed = completed + normalized_delta
            if total is not None:
                next_completed = min(next_completed, total)
            self._bars[bar_id] = (total, next_completed)
            self.recompute_hf_totals_locked()

    def close_hf_bar(self, bar_id: int) -> None:
        with self._lock:
            total, completed = self._bars.get(bar_id, (None, 0))
            if total is not None and completed < total:
                self._bars[bar_id] = (total, total)
            self.recompute_hf_totals_locked()

    def snapshot(self) -> tuple[int | None, int]:
        with self._lock:
            return self._total_bytes, self._completed_bytes

    def recompute_hf_totals_locked(self) -> None:
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


def parse_content_length(value: str | None) -> int | None:
    normalized = normalize_positive_int(value)
    return normalized if normalized > 0 else None


def calculate_progress(total_bytes: int | None, completed_bytes: int) -> int:
    if total_bytes is None or total_bytes <= 0:
        return 0
    progress = int((completed_bytes / total_bytes) * 100)
    return max(0, min(99, progress))


def normalize_positive_int(value: object) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)
