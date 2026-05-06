from __future__ import annotations

import asyncio
import contextlib

from cubie.core.observability.metrics import set_queue_depth
from cubie.task.engine import normalize_startup_models


class LifecycleMixin:
    async def start(self) -> None:
        if self._started:
            return
        await self._pipeline.start()
        if await self.has_pending_cleanups():
            self._cleanup_event.set()
        self._cleanup_worker_task = asyncio.create_task(self.run_cleanup_worker())
        self._worker_tasks = [
            asyncio.create_task(
                self.run_worker_loop(worker_index),
                name=f"cubie3d-worker-{worker_index}",
            )
            for worker_index in range(self._worker_count)
        ]
        set_queue_depth(await self._task_store.count_queued_tasks())
        self._started = True
        for model_name in self._startup_models:
            self.start_startup_prewarm(model_name)

    def set_startup_models(self, startup_models: tuple[str, ...]) -> None:
        self._startup_models = normalize_startup_models(startup_models)

    async def stop(self) -> None:
        if not self._started:
            return
        for worker_task in self._worker_tasks:
            worker_task.cancel()
        if self._worker_tasks:
            await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        self._worker_tasks.clear()
        if self._cleanup_worker_task is not None:
            self._cleanup_worker_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_worker_task
            self._cleanup_worker_task = None
        await self._pipeline.stop()
        await self._model_registry.close()
        self._started = False
        set_queue_depth(0)

    @property
    def ready(self) -> bool:
        return self._started and self._model_registry.has_ready_model()
