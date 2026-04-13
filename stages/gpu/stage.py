from __future__ import annotations

import asyncio
import time
import traceback
from dataclasses import dataclass

import structlog
from gen3d.engine.model_registry import ModelRegistry
from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.engine.vram_allocator import (
    ExternalVRAMOccupationTimeoutError,
    InternalVRAMContentionTimeoutError,
)
from gen3d.model.base import ModelProviderExecutionError, StageProgress
from gen3d.observability.metrics import observe_stage_duration
from gen3d.stages.base import BaseStage, StageExecutionError, StageUpdateHandler
from gen3d.stages.gpu.scheduler import SchedulerShutdownError
from structlog.contextvars import bound_contextvars


@dataclass(slots=True)
class _GPUStageTiming:
    stage_started_at: float


class GPUStage(BaseStage):
    name = "gpu"

    def __init__(
        self,
        *,
        delay_ms: int = 0,
        model_registry: ModelRegistry,
        task_store,
    ) -> None:
        self._delay_seconds = max(delay_ms, 0) / 1000
        self._model_registry = model_registry
        self._task_store = task_store
        self._logger = structlog.get_logger(__name__)

    @property
    def slot_count(self) -> int:
        ready_models = self._model_registry.ready_models()
        if not ready_models:
            return 0
        runtime = self._model_registry.get_runtime(ready_models[0])
        return runtime.scheduler.slot_count()

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        started_at = time.perf_counter()
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info("stage.started", stage=self.name, model=sequence.model)
            try:
                runtime = self._model_registry.get_runtime(sequence.model)
                sequence.transition_to(
                    TaskStatus.GPU_QUEUED,
                    current_stage=TaskStatus.GPU_QUEUED.value,
                    queue_position=0,
                    estimated_wait_seconds=0,
                )
                await self._emit_update(sequence, on_update)

                if self._delay_seconds:
                    await asyncio.sleep(self._delay_seconds)

                latest = await self._task_store.get_task(sequence.task_id)
                if latest is not None and latest.status == TaskStatus.CANCELLED:
                    duration_seconds = time.perf_counter() - started_at
                    self._logger.info(
                        "stage.completed",
                        stage=self.name,
                        duration_seconds=round(duration_seconds, 6),
                        status=latest.status.value,
                    )
                    return latest

                prepared_inputs = [sequence.prepared_input or {"image_url": sequence.input_url}]
                migration_attempted = False
                while True:
                    try:
                        slot = await runtime.scheduler.acquire(
                            batch_size=len(prepared_inputs),
                            options=sequence.options,
                        )
                        break
                    except InternalVRAMContentionTimeoutError:
                        raise
                    except ExternalVRAMOccupationTimeoutError as exc:
                        if migration_attempted:
                            raise
                        migration_attempted = True
                        previous_device = runtime.assigned_device_id
                        self._logger.warning(
                            "gpu.model_migration_triggered",
                            model=sequence.model,
                            old_device=previous_device,
                            reason=str(exc),
                        )
                        runtime = await self._model_registry.reload(
                            sequence.model,
                            exclude_device_ids=(
                                (previous_device,)
                                if previous_device is not None
                                else ()
                            ),
                        )
                        self._logger.info(
                            "gpu.model_migrated",
                            model=sequence.model,
                            old_device=previous_device,
                            new_device=runtime.assigned_device_id,
                            reason="external_vram_occupation_timeout",
                        )
                    except SchedulerShutdownError:
                        if migration_attempted:
                            raise
                        migration_attempted = True
                        runtime = await self._model_registry.wait_ready(sequence.model)
                        self._logger.info(
                            "gpu.acquire_retry_after_scheduler_shutdown",
                            model=sequence.model,
                            new_device=runtime.assigned_device_id,
                        )
                sequence.assigned_worker_id = slot.worker.worker_id
                timings = _GPUStageTiming(stage_started_at=time.perf_counter())
                try:
                    self._logger.info(
                        "gpu.slot_acquired",
                        device_id=slot.device_id,
                        worker_id=slot.worker.worker_id,
                    )
                    try:
                        results = await slot.worker.run_batch(
                            prepared_inputs=prepared_inputs,
                            options=sequence.options,
                            progress_cb=lambda progress: self._handle_progress(
                                sequence,
                                progress,
                                on_update,
                                timings,
                            ),
                        )
                    except ModelProviderExecutionError as exc:
                        raise StageExecutionError(exc.stage_name, str(exc)) from exc
                finally:
                    await runtime.scheduler.release(slot.device_id)

                sequence.generation_result = results[0]
                duration_seconds = time.perf_counter() - started_at
                self._logger.info(
                    "stage.completed",
                    stage=self.name,
                    duration_seconds=round(duration_seconds, 6),
                    worker_id=sequence.assigned_worker_id,
                    current_stage=sequence.current_stage,
                )
                return sequence
            except Exception as exc:
                duration_seconds = time.perf_counter() - started_at
                self._logger.warning(
                    "stage.failed",
                    stage=self.name,
                    duration_seconds=round(duration_seconds, 6),
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )
                raise
            finally:
                observe_stage_duration(
                    stage=self.name,
                    duration_seconds=time.perf_counter() - started_at,
                )

    async def _handle_progress(
        self,
        sequence: RequestSequence,
        progress: StageProgress,
        on_update: StageUpdateHandler | None,
        timings: _GPUStageTiming,
    ) -> None:
        status = {
            "ss": TaskStatus.GPU_SS,
            "shape": TaskStatus.GPU_SHAPE,
            "material": TaskStatus.GPU_MATERIAL,
        }[progress.stage_name]
        now = time.perf_counter()
        await self._task_store.update_stage_stats(
            model=sequence.model,
            stage=status.value,
            duration_seconds=now - timings.stage_started_at,
        )
        timings.stage_started_at = now
        sequence.transition_to(
            status,
            current_stage=status.value,
        )
        await self._emit_update(
            sequence,
            on_update,
            metadata={
                "status": sequence.status.value,
                "stage": progress.stage_name,
                "step": progress.step,
                "total_steps": progress.total_steps,
                "worker_id": sequence.assigned_worker_id,
            },
        )
