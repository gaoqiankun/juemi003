from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from structlog.contextvars import bound_contextvars

from gen3d.engine.sequence import RequestSequence, TaskStatus, utcnow
from gen3d.observability.metrics import (
    increment_task_total,
    observe_task_duration,
    set_queue_depth,
)
from gen3d.stages.base import BaseStage, StageExecutionError
from gen3d.storage.task_store import TaskStore

PipelineListener = Callable[
    [RequestSequence, str, dict[str, Any]],
    Awaitable[None] | None,
]


@dataclass(slots=True)
class CancelRequestResult:
    outcome: str
    sequence: RequestSequence | None


@dataclass(slots=True)
class RecoverySummary:
    scanned: int = 0
    requeued: int = 0
    failed_interrupted: int = 0
    failed_timeout: int = 0


class PipelineCoordinator:
    def __init__(
        self,
        task_store: TaskStore,
        stages: list[BaseStage],
        *,
        task_timeout_seconds: int = 3600,
    ) -> None:
        self._task_store = task_store
        self._stages = stages
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._worker_task: asyncio.Task[None] | None = None
        self._listeners: list[PipelineListener] = []
        self._logger = structlog.get_logger(__name__)
        self._task_timeout_seconds = max(int(task_timeout_seconds), 1)

    def add_listener(self, listener: PipelineListener) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        if self._worker_task is not None:
            return
        recovery_summary = await self._recover_incomplete_tasks()
        self._logger.info(
            "task.recovery_summary",
            scanned=recovery_summary.scanned,
            requeued=recovery_summary.requeued,
            failed_interrupted=recovery_summary.failed_interrupted,
            failed_timeout=recovery_summary.failed_timeout,
            task_timeout_seconds=self._task_timeout_seconds,
        )
        self._worker_task = asyncio.create_task(self._run(), name="gen3d-pipeline")

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        await self._queue.put(None)
        await self._worker_task
        self._worker_task = None

    async def enqueue(self, task_id: str) -> None:
        await self._queue.put(task_id)
        set_queue_depth(self.queue_size())

    def queue_size(self) -> int:
        return self._queue.qsize()

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
        await self._publish_update(
            sequence,
            "cancelled",
            {
                "message": "task cancelled by client",
                "requested_from_status": TaskStatus.GPU_QUEUED.value,
            },
        )
        return CancelRequestResult(outcome="cancelled", sequence=sequence)

    async def _recover_incomplete_tasks(self) -> RecoverySummary:
        summary = RecoverySummary()
        for sequence in await self._task_store.list_incomplete_tasks():
            summary.scanned += 1
            age_seconds = max(
                (utcnow() - sequence.created_at).total_seconds(),
                0.0,
            )
            with bound_contextvars(task_id=sequence.task_id):
                if age_seconds > self._task_timeout_seconds:
                    summary.failed_timeout += 1
                    self._logger.warning(
                        "task.recovered_as_failed",
                        recovery_action="timeout",
                        previous_status=sequence.status.value,
                        current_stage=sequence.current_stage,
                        task_age_seconds=round(age_seconds, 6),
                    )
                    await self._fail_recovered_task(
                        sequence,
                        message=(
                            "task exceeded TASK_TIMEOUT_SECONDS before service recovery"
                        ),
                        recovery_action="timeout",
                    )
                    continue
                if sequence.status in {TaskStatus.SUBMITTED, TaskStatus.PREPROCESSING}:
                    summary.requeued += 1
                    self._logger.info(
                        "task.requeued_after_restart",
                        previous_status=sequence.status.value,
                        current_stage=sequence.current_stage,
                        task_age_seconds=round(age_seconds, 6),
                    )
                    await self.enqueue(sequence.task_id)
                    continue

                summary.failed_interrupted += 1
                self._logger.warning(
                    "task.recovered_as_failed",
                    recovery_action="interrupted",
                    previous_status=sequence.status.value,
                    current_stage=sequence.current_stage,
                    task_age_seconds=round(age_seconds, 6),
                )
                await self._fail_recovered_task(
                    sequence,
                    message="服务重启，任务中断",
                    recovery_action="interrupted",
                )
        return summary

    async def _fail_recovered_task(
        self,
        sequence: RequestSequence,
        *,
        message: str,
        recovery_action: str,
    ) -> None:
        failed_stage = sequence.current_stage or sequence.status.value
        sequence.transition_to(
            TaskStatus.FAILED,
            current_stage=failed_stage,
            error_message=message,
            failed_stage=failed_stage,
        )
        await self._publish_update(
            sequence,
            "failed",
            {
                "status": sequence.status.value,
                "stage": failed_stage,
                "message": message,
                "recovery_action": recovery_action,
            },
        )

    async def _run(self) -> None:
        while True:
            task_id = await self._queue.get()
            set_queue_depth(self.queue_size())
            if task_id is None:
                self._queue.task_done()
                break

            try:
                sequence = await self._task_store.get_task(task_id)
                if sequence is None or sequence.status in {
                    TaskStatus.SUCCEEDED,
                    TaskStatus.FAILED,
                    TaskStatus.CANCELLED,
                }:
                    continue
                with bound_contextvars(task_id=sequence.task_id):
                    self._logger.info(
                        "task.processing_started",
                        current_stage=sequence.current_stage,
                        queue_depth=self.queue_size(),
                    )
                    for stage in self._stages:
                        try:
                            sequence = await stage.run(sequence, on_update=self._publish_update)
                        except StageExecutionError as exc:
                            self._logger.warning(
                                "task.processing_failed",
                                stage=exc.stage_name,
                                error=str(exc),
                            )
                            sequence.transition_to(
                                TaskStatus.FAILED,
                                current_stage=exc.stage_name,
                                error_message=str(exc),
                                failed_stage=exc.stage_name,
                            )
                            await self._publish_update(
                                sequence,
                                "failed",
                                {
                                    "status": sequence.status.value,
                                    "stage": exc.stage_name,
                                    "message": str(exc),
                                },
                            )
                            break
                        except Exception as exc:  # pragma: no cover - defensive fallback
                            self._logger.exception(
                                "task.processing_failed_unexpected",
                                stage=stage.name,
                                error=str(exc),
                            )
                            sequence.transition_to(
                                TaskStatus.FAILED,
                                current_stage=stage.name,
                                error_message=str(exc),
                                failed_stage=stage.name,
                            )
                            await self._publish_update(
                                sequence,
                                "failed",
                                {
                                    "status": sequence.status.value,
                                    "stage": stage.name,
                                    "message": str(exc),
                                },
                            )
                            break
                        if sequence.status in {
                            TaskStatus.SUCCEEDED,
                            TaskStatus.FAILED,
                            TaskStatus.CANCELLED,
                        }:
                            break
            finally:
                self._queue.task_done()

    async def _publish_update(
        self,
        sequence: RequestSequence,
        event: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "status": sequence.status.value,
            "current_stage": sequence.current_stage,
            "progress": sequence.progress,
        }
        if metadata:
            payload.update(metadata)
        await self._task_store.update_task(sequence, event=event, metadata=payload)
        if event in {"succeeded", "failed", "cancelled"}:
            duration_seconds = 0.0
            if sequence.completed_at is not None:
                duration_seconds = max(
                    (sequence.completed_at - sequence.created_at).total_seconds(),
                    0.0,
                )
            observe_task_duration(
                status=sequence.status.value,
                duration_seconds=duration_seconds,
            )
            increment_task_total(status=sequence.status.value)
            with bound_contextvars(task_id=sequence.task_id):
                self._logger.info(
                    "task.processing_finished",
                    status=sequence.status.value,
                    duration_seconds=round(duration_seconds, 6),
                    failed_stage=sequence.failed_stage,
                    error=sequence.error_message,
                )
        for listener in self._listeners:
            maybe_awaitable = listener(sequence, event, payload)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
