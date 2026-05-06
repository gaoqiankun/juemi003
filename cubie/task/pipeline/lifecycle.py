from __future__ import annotations

import inspect

from structlog.contextvars import bound_contextvars

from cubie.task.pipeline import CancelRequestResult, PipelineListener
from cubie.task.sequence import TaskStatus


class LifecycleMixin:
    def add_listener(self, listener: PipelineListener) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        if self._started:
            return
        await self.run_stage_lifecycle("start")
        recovery_summary = await self.recover_incomplete_tasks()
        self._logger.info(
            "task.recovery_summary",
            scanned=recovery_summary.scanned,
            requeued=recovery_summary.requeued,
            failed_interrupted=recovery_summary.failed_interrupted,
            failed_timeout=recovery_summary.failed_timeout,
            task_timeout_seconds=self._task_timeout_seconds,
            worker_count=self._worker_count,
        )
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self.run_stage_lifecycle("stop")
        self._started = False

    @property
    def worker_count(self) -> int:
        return self._worker_count

    @property
    def queue_capacity(self) -> int:
        return self._worker_count + self._queue_max_size

    async def cancel_task(self, task_id: str) -> CancelRequestResult:
        sequence = await self._task_store.get_task(task_id)
        if sequence is None:
            return CancelRequestResult(outcome="not_found", sequence=None)
        if sequence.status in {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }:
            return CancelRequestResult(outcome="already_terminal", sequence=sequence)
        if sequence.status != TaskStatus.GPU_QUEUED:
            return CancelRequestResult(outcome="not_cancellable", sequence=sequence)

        sequence.transition_to(
            TaskStatus.CANCELLED,
            current_stage=TaskStatus.CANCELLED.value,
        )
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.cancelled",
                requested_from_status=TaskStatus.GPU_QUEUED.value,
            )
        await self.publish_update(
            sequence,
            "cancelled",
            {
                "message": "task cancelled by client",
                "requested_from_status": TaskStatus.GPU_QUEUED.value,
            },
        )
        return CancelRequestResult(outcome="cancelled", sequence=sequence)

    async def run_stage_lifecycle(self, method_name: str) -> None:
        for stage in self._stages:
            method = getattr(stage, method_name, None)
            if method is None:
                continue
            maybe_awaitable = method()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
