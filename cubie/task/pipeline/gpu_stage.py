from __future__ import annotations

import traceback

from cubie.model.worker import ModelWorker
from cubie.stage.base import BaseStage
from cubie.task.sequence import RequestSequence, TaskStatus
from cubie.vram.allocator import InferenceLease


class GPUStageMixin:
    async def run_gpu_export_with_lease(
        self,
        sequence: RequestSequence,
        *,
        gpu_stage: BaseStage,
        export_stage: BaseStage,
    ) -> RequestSequence:
        if self._inference_allocator is None or self._model_registry is None:
            return await self.run_gpu_export_directly(sequence, gpu_stage, export_stage)

        model_worker = self._model_registry.get_worker(sequence.model)
        if model_worker is None:
            return await self.run_gpu_export_directly(sequence, gpu_stage, export_stage)

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
                sequence = await self.run_gpu_with_oom_retry(
                    sequence=sequence,
                    gpu_stage=gpu_stage,
                    model_worker=model_worker,
                    lease=lease,
                )
                if self.is_terminal(sequence):
                    return sequence
                sequence = await export_stage.run(sequence, on_update=self.publish_update)
                await model_worker.apply_successful_inference_measurement()
                model_worker.empty_cuda_cache()
                return sequence
        finally:
            model_worker.end_task_inference()

    async def run_gpu_export_directly(
        self,
        sequence: RequestSequence,
        gpu_stage: BaseStage,
        export_stage: BaseStage,
    ) -> RequestSequence:
        sequence = await gpu_stage.run(sequence, on_update=self.publish_update)
        if self.is_terminal(sequence):
            return sequence
        return await export_stage.run(sequence, on_update=self.publish_update)

    async def run_gpu_with_oom_retry(
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
            from cubie.task.pipeline import looks_like_oom

            if not looks_like_oom(first_error):
                raise

        bump_target_mb = model_worker.resolve_oom_bump_target_mb()
        await model_worker.apply_oom_bump_target_mb(bump_target_mb)
        model_worker.empty_cuda_cache()
        await lease.bump_and_retry_once(bump_target_mb)
        await model_worker.apply_inference_allocation(lease.allocation)
        return await gpu_stage.run(sequence, on_update=self.publish_update)

    async def mark_stage_failed(
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
