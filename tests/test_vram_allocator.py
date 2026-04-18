from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.vram_allocator import (
    InferenceAllocation,
    VRAMAllocator,
    VRAMInsufficientError,
    WeightAllocation,
)


class FakeEvictableWorker:
    def __init__(
        self,
        *,
        allocator: VRAMAllocator,
        model_id: str,
        weight_allocation: WeightAllocation,
        inference_busy: bool = False,
        last_used_tick: int = 0,
    ) -> None:
        self._allocator = allocator
        self._model_id = model_id
        self._weight_allocation = weight_allocation
        self.device_id = weight_allocation.device_id
        self.weight_allocated = True
        self.inference_busy = inference_busy
        self.evicting = False
        self.last_used_tick = last_used_tick
        self.evict_calls = 0

    async def evict(self) -> None:
        self.evict_calls += 1
        self.evicting = True
        self.weight_allocated = False
        self._allocator.release_weight(self._weight_allocation.allocation_id)
        self._allocator.unregister_worker(self._model_id)
        self.evicting = False


def test_request_weight_places_models_across_devices() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000, "1": 24_000})
        first = await allocator.request_weight("trellis2", 16_000)
        second = await allocator.request_weight("hunyuan3d", 16_000)

        assert first.device_id == "0"
        assert second.device_id == "1"

    asyncio.run(scenario())


def test_release_weight_returns_capacity() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        first = await allocator.request_weight("model-a", 16_000)

        with pytest.raises(VRAMInsufficientError):
            await allocator.request_weight("model-b", 10_000)

        allocator.release_weight(first.allocation_id)
        second = await allocator.request_weight("model-b", 10_000)
        assert second.device_id == "0"

    asyncio.run(scenario())


def test_correct_weight_only_increases_booked_weight() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        allocation = await allocator.request_weight("model-a", 10_000)

        allocator.correct_weight(allocation.allocation_id, 9_000)
        snapshot_after_downward = allocator.snapshot()["0"]
        assert snapshot_after_downward["weight_allocations"][str(allocation.allocation_id)] == 10_000

        allocator.correct_weight(allocation.allocation_id, 12_000)
        snapshot_after_upward = allocator.snapshot()["0"]
        assert snapshot_after_upward["weight_allocations"][str(allocation.allocation_id)] == 12_000

    asyncio.run(scenario())


def test_request_weight_evicts_idle_registered_worker() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        victim_weight = await allocator.request_weight("victim", 16_000)
        victim_worker = FakeEvictableWorker(
            allocator=allocator,
            model_id="victim",
            weight_allocation=victim_weight,
            inference_busy=False,
            last_used_tick=1,
        )
        allocator.register_worker("victim", victim_worker)

        allocation = await allocator.request_weight("new-model", 12_000)

        assert allocation.device_id == "0"
        assert victim_worker.evict_calls == 1
        snapshot = allocator.snapshot()["0"]
        assert snapshot["allocations"] == {"new-model": 12_000}

    asyncio.run(scenario())


def test_request_inference_supports_migration_booking() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000, "1": 24_000})
        allocator._MIGRATION_WAIT_SECONDS = 0.01

        model_weight = await allocator.request_weight("model-a", 12_000)
        blocker_weight = await allocator.request_weight("blocker", 9_000)
        blocker_worker = FakeEvictableWorker(
            allocator=allocator,
            model_id="blocker",
            weight_allocation=blocker_weight,
            inference_busy=True,
            last_used_tick=1,
        )
        allocator.register_worker("blocker", blocker_worker)

        inference = await allocator.request_inference(
            model_id="model-a",
            device_id=model_weight.device_id,
            inference_mb=4_000,
            weight_mb=12_000,
        )

        assert isinstance(inference, InferenceAllocation)
        assert inference.device_id == "1"
        assert inference.weight_allocation_id is not None

    asyncio.run(scenario())


def test_inference_lease_releases_on_normal_exit() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        await allocator.request_weight("model-a", 12_000)

        async with allocator.reserve_for_task(
            model_id="model-a",
            estimate_mb=3_000,
            weight_mb=12_000,
        ) as lease:
            allocation_id = str(lease.allocation.inference_allocation_id)
            snapshot = allocator.snapshot()["0"]
            assert snapshot["used_inference_vram_mb"] == 3_000
            assert allocation_id in snapshot["inference_allocations"]

        snapshot_after = allocator.snapshot()["0"]
        assert snapshot_after["used_inference_vram_mb"] == 0
        assert snapshot_after["inference_allocations"] == {}

    asyncio.run(scenario())


def test_inference_lease_releases_on_exception() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        await allocator.request_weight("model-a", 12_000)

        with pytest.raises(RuntimeError, match="boom"):
            async with allocator.reserve_for_task(
                model_id="model-a",
                estimate_mb=3_000,
                weight_mb=12_000,
            ):
                raise RuntimeError("boom")

        snapshot = allocator.snapshot()["0"]
        assert snapshot["used_inference_vram_mb"] == 0
        assert snapshot["inference_allocations"] == {}

    asyncio.run(scenario())


def test_inference_lease_bump_rebooks_allocation() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        await allocator.request_weight("model-a", 12_000)

        async with allocator.reserve_for_task(
            model_id="model-a",
            estimate_mb=2_000,
            weight_mb=12_000,
        ) as lease:
            first_allocation_id = str(lease.allocation.inference_allocation_id)
            await lease.bump_and_retry_once(3_500)
            second_allocation_id = str(lease.allocation.inference_allocation_id)

            assert first_allocation_id != second_allocation_id
            snapshot = allocator.snapshot()["0"]
            assert snapshot["used_inference_vram_mb"] == 3_500
            assert first_allocation_id not in snapshot["inference_allocations"]
            assert second_allocation_id in snapshot["inference_allocations"]

        snapshot_after = allocator.snapshot()["0"]
        assert snapshot_after["used_inference_vram_mb"] == 0
        assert snapshot_after["inference_allocations"] == {}

    asyncio.run(scenario())
