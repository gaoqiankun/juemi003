# ruff: noqa: E402

from __future__ import annotations

import asyncio
from typing import cast

from cubie.model.base import BaseModelProvider, GenerationResult
from cubie.model.gpu import GPUWorkerHandle
from cubie.model.gpu_scheduler import GPUSlotScheduler, SchedulerShutdownError
from cubie.model.registry import ModelRegistry, ModelRuntime


class FakeWorker:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id
        self.worker_id = f"gpu-worker-{device_id}"
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb=None,
    ) -> list[GenerationResult]:
        _ = prepared_inputs
        _ = options
        _ = progress_cb
        return []


def test_scheduler_shutdown_wakes_all_waiters() -> None:
    async def scenario() -> None:
        worker = FakeWorker("0")
        scheduler = GPUSlotScheduler([cast(GPUWorkerHandle, worker)])
        acquired_slot = await scheduler.acquire()

        waiters = [
            asyncio.create_task(scheduler.acquire())
            for _ in range(10)
        ]
        await asyncio.sleep(0.05)
        scheduler.shutdown()

        results = await asyncio.wait_for(
            asyncio.gather(*waiters, return_exceptions=True),
            timeout=1.0,
        )
        assert all(isinstance(result, SchedulerShutdownError) for result in results)

        await scheduler.release(acquired_slot.device_id)

    asyncio.run(scenario())


def test_reload_shutdown_unblocks_waiters_on_old_scheduler() -> None:
    async def scenario() -> None:
        workers_by_device: dict[str, FakeWorker] = {}

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
            exclude_device_ids: tuple[str, ...] | None = None,
        ) -> ModelRuntime:
            target_device = device_id
            if target_device is None:
                excluded = set(exclude_device_ids or ())
                for candidate in ("0", "1"):
                    if candidate not in excluded:
                        target_device = candidate
                        break
            assert target_device is not None
            worker = workers_by_device.setdefault(target_device, FakeWorker(target_device))
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
                assigned_device_id=target_device,
            )

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2", device_id="0")
        old_runtime = await registry.wait_ready("trellis2")
        held_slot = await old_runtime.scheduler.acquire()
        waiters = [
            asyncio.create_task(old_runtime.scheduler.acquire())
            for _ in range(10)
        ]
        await asyncio.sleep(0.05)

        migrated_runtime = await registry.reload("trellis2", exclude_device_ids=("0",))
        assert migrated_runtime.assigned_device_id == "1"

        waiter_results = await asyncio.wait_for(
            asyncio.gather(*waiters, return_exceptions=True),
            timeout=1.0,
        )
        assert all(
            isinstance(result, SchedulerShutdownError)
            for result in waiter_results
        )

        await old_runtime.scheduler.release(held_slot.device_id)
        await registry.close()

    asyncio.run(scenario())
