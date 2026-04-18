from __future__ import annotations

import inspect
import traceback
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog
from gen3d.engine.model_registry import ModelRegistry
from gen3d.engine.model_worker import ModelWorker
from gen3d.engine.sequence import RequestSequence, TaskStatus, utcnow
from gen3d.engine.vram_allocator import InferenceLease, VRAMAllocator
from gen3d.observability.metrics import increment_task_total, observe_task_duration
from gen3d.stages.base import BaseStage, StageExecutionError
from gen3d.storage.task_store import TaskStore
from structlog.contextvars import bound_contextvars

PipelineListener = Callable[
    [RequestSequence, str, dict[str, Any]],
    Awaitable[None] | None,
]


@dataclass(slots=True)
class CancelRequestResult:
    outcome: str
    sequence: RequestSequence | None


class PipelineQueueFullError(RuntimeError):
    pass


@dataclass(slots=True)
class RecoverySummary:
    scanned: int = 0
    requeued: int = 0
    failed_interrupted: int = 0
    failed_timeout: int = 0


def _looks_like_oom(error: BaseException) -> bool:
    message = str(error).lower()
    return "out of memory" in message or "cuda oom" in message or "cuda out of memory" in message


class PipelineCoordinator:
    def __init__(
        self,
        task_store: TaskStore,
        stages: list[BaseStage],
        *,
        inference_allocator: VRAMAllocator | None = None,
        model_registry: ModelRegistry | None = None,
        task_timeout_seconds: int = 3600,
        queue_max_size: int = 20,
        worker_count: int = 1,
    ) -> None:
        self._task_store = task_store
        self._stages = stages
        self._inference_allocator = inference_allocator
        self._model_registry = model_registry
        self._listeners: list[PipelineListener] = []
        self._logger = structlog.get_logger(__name__)
        self._task_timeout_seconds = max(int(task_timeout_seconds), 1)
        self._worker_count = max(int(worker_count), 1)
        self._queue_max_size = max(int(queue_max_size), 0)
        self._started = False

    def add_listener(self, listener: PipelineListener) -> None:
        self._listeners.append(listener)

    async def start(self) -> None:
        if self._started:
            return
        await self._run_stage_lifecycle("start")
        recovery_summary = await self._recover_incomplete_tasks()
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
        await self._run_stage_lifecycle("stop")
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

    async def run_sequence(self, sequence: RequestSequence) -> RequestSequence:
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.processing_started",
                current_stage=sequence.current_stage,
                model=sequence.model,
            )
            stage_index = 0
            while stage_index < len(self._stages):
                stage = self._stages[stage_index]
                try:
                    if self._can_run_with_inference_lease(stage_index):
                        export_stage = self._stages[stage_index + 1]
                        sequence = await self._run_gpu_export_with_lease(
                            sequence,
                            gpu_stage=stage,
                            export_stage=export_stage,
                        )
                        stage_index += 2
                    else:
                        sequence = await stage.run(sequence, on_update=self.publish_update)
                        stage_index += 1
                except StageExecutionError as exc:
                    await self._mark_stage_failed(
                        sequence,
                        stage_name=exc.stage_name,
                        message=str(exc),
                    )
                    break
                except Exception as exc:  # pragma: no cover - defensive fallback
                    self._logger.exception(
                        "task.processing_failed_unexpected",
                        stage=stage.name,
                        error=str(exc),
                    )
                    await self._mark_stage_failed(
                        sequence,
                        stage_name=stage.name,
                        message=str(exc),
                    )
                    break
                if self._is_terminal(sequence):
                    break
        return sequence

    @staticmethod
    def _is_terminal(sequence: RequestSequence) -> bool:
        return sequence.status in {
            TaskStatus.SUCCEEDED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        }

    def _can_run_with_inference_lease(self, stage_index: int) -> bool:
        if self._inference_allocator is None or self._model_registry is None:
            return False
        if stage_index + 1 >= len(self._stages):
            return False
        stage = self._stages[stage_index]
        next_stage = self._stages[stage_index + 1]
        return stage.name == "gpu" and next_stage.name == "export"

    async def _run_gpu_export_with_lease(
        self,
        sequence: RequestSequence,
        *,
        gpu_stage: BaseStage,
        export_stage: BaseStage,
    ) -> RequestSequence:
        if self._inference_allocator is None or self._model_registry is None:
            sequence = await gpu_stage.run(sequence, on_update=self.publish_update)
            if self._is_terminal(sequence):
                return sequence
            return await export_stage.run(sequence, on_update=self.publish_update)

        model_worker = self._model_registry.get_worker(sequence.model)
        if model_worker is None:
            sequence = await gpu_stage.run(sequence, on_update=self.publish_update)
            if self._is_terminal(sequence):
                return sequence
            return await export_stage.run(sequence, on_update=self.publish_update)

        estimate_mb = model_worker.estimate_inference_mb(sequence.options)
        lease = self._inference_allocator.reserve_for_task(
            model_id=sequence.model,
            estimate_mb=estimate_mb,
            weight_mb=model_worker.weight_vram_mb,
        )
        model_worker.begin_task_inference()
        try:
            async with lease:
                await model_worker.apply_inference_allocation(lease.allocation)
                sequence = await self._run_gpu_with_oom_retry(
                    sequence=sequence,
                    gpu_stage=gpu_stage,
                    model_worker=model_worker,
                    lease=lease,
                )
                if self._is_terminal(sequence):
                    return sequence
                sequence = await export_stage.run(sequence, on_update=self.publish_update)
                await model_worker.apply_successful_inference_measurement()
                model_worker.empty_cuda_cache()
                return sequence
        finally:
            model_worker.end_task_inference()

    async def _run_gpu_with_oom_retry(
        self,
        *,
        sequence: RequestSequence,
        gpu_stage: BaseStage,
        model_worker: ModelWorker,
        lease: InferenceLease,
    ) -> RequestSequence:
        try:
            return await gpu_stage.run(sequence, on_update=self.publish_update)
        except Exception as first_error:
            if not _looks_like_oom(first_error):
                raise

        bump_target_mb = model_worker.resolve_oom_bump_target_mb()
        await model_worker.apply_oom_bump_target_mb(bump_target_mb)
        model_worker.empty_cuda_cache()
        await lease.bump_and_retry_once(bump_target_mb)
        await model_worker.apply_inference_allocation(lease.allocation)
        return await gpu_stage.run(sequence, on_update=self.publish_update)

    async def _mark_stage_failed(
        self,
        sequence: RequestSequence,
        *,
        stage_name: str,
        message: str,
    ) -> None:
        self._logger.warning(
            "task.processing_failed",
            stage=stage_name,
            error=message,
            traceback=traceback.format_exc(),
        )
        sequence.transition_to(
            TaskStatus.FAILED,
            current_stage=stage_name,
            error_message=message,
            failed_stage=stage_name,
        )
        await self.publish_update(
            sequence,
            "failed",
            {
                "status": sequence.status.value,
                "stage": stage_name,
                "message": message,
            },
        )

    async def publish_update(
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
                if sequence.status in {TaskStatus.QUEUED, TaskStatus.PREPROCESSING}:
                    summary.requeued += 1
                    self._logger.info(
                        "task.requeued_after_restart",
                        previous_status=sequence.status.value,
                        current_stage=sequence.current_stage,
                        task_age_seconds=round(age_seconds, 6),
                    )
                    await self._task_store.requeue_task(sequence.task_id)
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
        await self.publish_update(
            sequence,
            "failed",
            {
                "status": sequence.status.value,
                "stage": failed_stage,
                "message": message,
                "recovery_action": recovery_action,
            },
        )

    async def _run_stage_lifecycle(self, method_name: str) -> None:
        for stage in self._stages:
            method = getattr(stage, method_name, None)
            if method is None:
                continue
            maybe_awaitable = method()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
