from __future__ import annotations

import asyncio
import time

import structlog
from structlog.contextvars import bound_contextvars

from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.model.base import ModelProviderExecutionError, StageProgress
from gen3d.observability.metrics import observe_stage_duration
from gen3d.stages.base import BaseStage, StageExecutionError, StageUpdateHandler
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle


class GPUStage(BaseStage):
    name = "gpu"

    def __init__(
        self,
        *,
        delay_ms: int = 0,
        workers: list[GPUWorkerHandle],
        task_store,
    ) -> None:
        self._delay_seconds = max(delay_ms, 0) / 1000
        self._workers = workers
        self._scheduler = GPUSlotScheduler(workers)
        self._task_store = task_store
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        for worker in self._workers:
            await worker.start()
        self._logger.info(
            "gpu.worker_pool_started",
            worker_count=len(self._workers),
            device_ids=[worker.device_id for worker in self._workers],
        )

    async def stop(self) -> None:
        for worker in self._workers:
            await worker.stop()
        self._logger.info(
            "gpu.worker_pool_stopped",
            worker_count=len(self._workers),
            device_ids=[worker.device_id for worker in self._workers],
        )

    @property
    def slot_count(self) -> int:
        return self._scheduler.slot_count()

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        started_at = time.perf_counter()
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info("stage.started", stage=self.name)
            try:
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

                slot = await self._scheduler.acquire()
                sequence.assigned_worker_id = slot.worker.worker_id
                prepared_inputs = [sequence.prepared_input or {"image_url": sequence.input_url}]
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
                            ),
                        )
                    except ModelProviderExecutionError as exc:
                        raise StageExecutionError(exc.stage_name, str(exc)) from exc
                finally:
                    await self._scheduler.release(slot.device_id)

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
    ) -> None:
        status = {
            "ss": TaskStatus.GPU_SS,
            "shape": TaskStatus.GPU_SHAPE,
            "material": TaskStatus.GPU_MATERIAL,
        }[progress.stage_name]
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
