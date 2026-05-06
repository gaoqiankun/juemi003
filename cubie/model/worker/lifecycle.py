from __future__ import annotations

import asyncio
from typing import cast

from cubie.model.gpu_scheduler import GPUSlotScheduler, GPUWorkerHandle
from cubie.model.worker import maybe_empty_cuda_cache
from cubie.model.worker.factory import invoke_gpu_worker_factory
from cubie.vram.allocator import WeightAllocation, WeightAllocationID


class LifecycleMixin:
    async def load(self) -> None:
        async with self._load_lock:
            if self._weight_allocated:
                return
            await self.load_estimates_from_db()
            setattr(
                self,
                "_weight_allocation",
                await self._allocator.request_weight(
                    self.model_id,
                    self.weight_vram_mb,
                ),
            )
            setattr(self, "_device_id", self._weight_allocation.device_id)
            self._allocator.register_worker(self.model_id, self)
            try:
                measured_weight_mb = await self.start_runtime_on(self._device_id)
            except Exception:
                self.release_weight_allocation()
                raise

            if self._weight_allocation is None:
                raise RuntimeError(f"model {self.model_id} has no weight allocation after load")
            await self.apply_measured_weight(measured_weight_mb)
            if self.is_mock_runtime():
                self.inference_vram_mb = 1
            setattr(self, "_weight_allocated", True)
            self.touch_last_used()

    async def evict(self) -> None:
        if self._evicting:
            return
        setattr(self, "_evicting", True)
        try:
            while self.inference_busy:
                await asyncio.sleep(self._EVICT_POLL_SECONDS)
            await self.stop_runtime()
            self.release_weight_allocation()
            setattr(self, "_weight_allocated", False)
        finally:
            setattr(self, "_evicting", False)

    async def unload(self) -> None:
        await self.evict()

    async def do_migration(
        self,
        new_device: str,
        new_weight_alloc: WeightAllocationID,
        new_inference_alloc,
    ) -> None:
        _ = new_inference_alloc
        old_weight_alloc = self._weight_allocation
        setattr(self, "_weight_allocated", False)
        await self.stop_runtime()
        if old_weight_alloc is not None:
            self._allocator.release_weight(old_weight_alloc.allocation_id)
        self._allocator.unregister_worker(self.model_id)

        setattr(self, "_device_id", str(new_device).strip())
        setattr(
            self,
            "_weight_allocation",
            WeightAllocation(
                allocation_id=new_weight_alloc,
                device_id=self._device_id,
            ),
        )
        try:
            measured_weight_mb = await self.start_runtime_on(self._device_id)
        except Exception:
            setattr(self, "_weight_allocation", None)
            setattr(self, "_device_id", None)
            raise

        self._allocator.register_worker(self.model_id, self)
        setattr(self, "_weight_allocated", True)
        await self.apply_measured_weight(measured_weight_mb)
        if self.is_mock_runtime():
            self.inference_vram_mb = 1
        self.touch_last_used()

    async def start_runtime_on(self, device_id: str) -> int | None:
        runtime = await invoke_gpu_worker_factory(
            self.model_id,
            self._gpu_worker_factory,
            device_id=device_id,
            measurement_callback=self.on_inference_measured,
        )
        if not runtime.workers:
            raise RuntimeError(f"model {self.model_id} runtime returned no workers")

        for worker in runtime.workers:
            await worker.start()

        runtime.scheduler = GPUSlotScheduler([cast(GPUWorkerHandle, self._runtime_adapter)])
        runtime.assigned_device_id = str(device_id).strip()
        runtime.weight_vram_mb = self.weight_vram_mb

        setattr(self, "_runtime", runtime)
        setattr(self, "_gpu_worker", runtime.workers[0])
        setattr(self, "_device_id", runtime.assigned_device_id)
        startup_weight_mb = getattr(self._gpu_worker, "startup_weight_mb", None)
        if startup_weight_mb is None:
            return None
        try:
            return max(int(startup_weight_mb), 0)
        except (TypeError, ValueError):
            return None

    async def reset_after_crash(self) -> None:
        """Release allocator state after subprocess crash.

        The subprocess has already died and the OS has reclaimed its CUDA
        memory, but the allocator still tracks the weight allocation.  Reset
        everything so load() can run cleanly on the next request.
        """
        self.release_weight_allocation()
        setattr(self, "_weight_allocated", False)
        setattr(self, "_gpu_worker", None)
        setattr(self, "_runtime", None)

    async def stop_runtime(self) -> None:
        runtime = self._runtime
        if runtime is None:
            setattr(self, "_gpu_worker", None)
            return
        scheduler_shutdown = getattr(runtime.scheduler, "shutdown", None)
        if callable(scheduler_shutdown):
            scheduler_shutdown()
        for worker in runtime.workers:
            await worker.stop()
        setattr(self, "_gpu_worker", None)
        setattr(self, "_runtime", None)
        maybe_empty_cuda_cache()
