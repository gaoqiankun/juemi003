from __future__ import annotations

import asyncio
from urllib.parse import urlparse

from structlog.contextvars import bound_contextvars

from cubie.artifact.store import ArtifactStoreOperationError


class CleanupMixin:
    async def has_pending_cleanups(self) -> bool:
        pending = await self._task_store.list_pending_cleanups(limit=1)
        return bool(pending)

    async def run_cleanup_worker(self) -> None:
        while True:
            await self._cleanup_event.wait()
            self._cleanup_event.clear()
            while True:
                pending_task_ids = await self._task_store.list_pending_cleanups(
                    limit=self._CLEANUP_BATCH_SIZE
                )
                if not pending_task_ids:
                    break
                await asyncio.gather(
                    *(self.cleanup_single_task(task_id) for task_id in pending_task_ids)
                )

    async def cleanup_single_task(self, task_id: str) -> None:
        async with self._cleanup_semaphore:
            sequence = await self._task_store.get_task(task_id, include_deleted=True)
            if self._artifact_store is not None:
                try:
                    await self._artifact_store.delete_artifacts(task_id)
                except ArtifactStoreOperationError as exc:
                    with bound_contextvars(task_id=task_id):
                        self._logger.warning(
                            "task.artifact_cleanup_failed",
                            stage=exc.stage_name,
                            error=str(exc),
                        )
                except Exception as exc:  # pragma: no cover - defensive guard
                    with bound_contextvars(task_id=task_id):
                        self._logger.warning(
                            "task.artifact_cleanup_failed",
                            stage="cleanup",
                            error=str(exc),
                        )
            if sequence is not None:
                await self.cleanup_uploaded_input(sequence.input_url, task_id=task_id)
            try:
                await self._task_store.mark_cleanup_done(task_id)
            except Exception as exc:  # pragma: no cover - defensive guard
                with bound_contextvars(task_id=task_id):
                    self._logger.warning(
                        "task.artifact_cleanup_mark_done_failed",
                        error=str(exc),
                    )

    async def cleanup_uploaded_input(self, input_url: str, *, task_id: str) -> None:
        parsed = urlparse(input_url)
        if parsed.scheme != "upload":
            return
        upload_id = (parsed.netloc or parsed.path.lstrip("/")).strip()
        if not upload_id:
            return
        try:
            matches = await asyncio.to_thread(
                lambda: list(self._uploads_dir.glob(f"{upload_id}.*"))
            )
            for match in matches:
                if match.exists():
                    await asyncio.to_thread(match.unlink)
        except Exception as exc:  # pragma: no cover - defensive guard
            with bound_contextvars(task_id=task_id):
                self._logger.warning(
                    "task.upload_cleanup_failed",
                    error=str(exc),
                    input_url=input_url,
                )
