from __future__ import annotations

from typing import Any, Awaitable, Callable

from cubie.model.base import GenerationResult, StageProgress
from cubie.model.worker import looks_like_worker_crash
from cubie.vram.allocator import InferenceAllocation


class InferenceMixin:
    def estimate_inference_mb(self, options: dict[str, Any]) -> int:
        _ = options
        return max(int(self.inference_vram_mb), 1)

    def begin_task_inference(self) -> None:
        setattr(self, "_inference_busy_holds", self._inference_busy_holds + 1)
        self.touch_last_used()

    def end_task_inference(self) -> None:
        setattr(self, "_inference_busy_holds", max(self._inference_busy_holds - 1, 0))
        self.touch_last_used()

    async def apply_inference_allocation(self, allocation: InferenceAllocation) -> None:
        if allocation.weight_allocation_id is None:
            return
        await self.do_migration(
            new_device=allocation.device_id,
            new_weight_alloc=allocation.weight_allocation_id,
            new_inference_alloc=allocation.inference_allocation_id,
        )

    async def run_batch(
        self,
        *,
        batch: list[object],
        options: dict[str, Any],
        progress_cb: Callable[[StageProgress], Awaitable[None] | None] | None,
    ) -> list[GenerationResult]:
        if self._evicting:
            raise RuntimeError(f"model {self.model_id} is evicting")
        if self._gpu_worker is None or self._device_id is None:
            raise RuntimeError(f"model {self.model_id} has no running GPU worker")

        setattr(self, "_inference_busy_holds", self._inference_busy_holds + 1)
        self.touch_last_used()
        try:
            return await self._gpu_worker.run_batch(
                prepared_inputs=batch,
                options=options,
                progress_cb=progress_cb,
            )
        except Exception as exc:
            if looks_like_worker_crash(exc):
                await self.reset_after_crash()
            raise
        finally:
            setattr(self, "_inference_busy_holds", max(self._inference_busy_holds - 1, 0))
            self.touch_last_used()

    async def run_inference(
        self,
        *,
        batch: list[object],
        options: dict[str, Any],
        progress_cb: Callable[[StageProgress], Awaitable[None] | None] | None,
    ) -> list[GenerationResult]:
        # Backward-compatible alias; allocation lifecycle now lives in pipeline lease.
        results = await self.run_batch(
            batch=batch,
            options=options,
            progress_cb=progress_cb,
        )
        await self.apply_successful_inference_measurement()
        self.empty_cuda_cache()
        return results
