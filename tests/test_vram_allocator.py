from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.vram_allocator import (
    ExternalVRAMOccupationTimeoutError,
    InternalVRAMContentionTimeoutError,
    VRAMAllocator,
    VRAMAllocatorError,
    VRAMMetricsHook,
)


def test_allocator_places_models_on_available_devices() -> None:
    allocator = VRAMAllocator(
        device_totals_mb={
            "0": 24_000,
            "1": 24_000,
        }
    )

    first = allocator.reserve(model_name="trellis2", weight_vram_mb=16_000)
    second = allocator.reserve(model_name="hunyuan3d", weight_vram_mb=16_000)

    assert first == "0"
    assert second == "1"


def test_allocator_allows_multi_model_on_same_device_when_weight_fits() -> None:
    allocator = VRAMAllocator(
        device_totals_mb={
            "0": 24_000,
            "1": 24_000,
        }
    )

    first = allocator.reserve(model_name="model-a", weight_vram_mb=10_000)
    second = allocator.reserve(model_name="model-b", weight_vram_mb=9_000)
    third = allocator.reserve(model_name="model-c", weight_vram_mb=9_000)

    assert first == "0"
    assert second == "0"
    assert third == "1"


def test_allocator_honors_preferred_device_and_release() -> None:
    allocator = VRAMAllocator(device_totals_mb={"0": 24_000, "1": 24_000})
    allocator.reserve(
        model_name="model-a",
        weight_vram_mb=16_000,
        preferred_device_id="1",
    )

    with pytest.raises(VRAMAllocatorError):
        allocator.reserve(
            model_name="model-b",
            weight_vram_mb=10_000,
            preferred_device_id="1",
        )

    allocator.release("model-a")
    assigned = allocator.reserve(
        model_name="model-b",
        weight_vram_mb=10_000,
        preferred_device_id="1",
    )
    assert assigned == "1"


def test_external_timeout_error_is_allocator_error_subclass() -> None:
    assert issubclass(ExternalVRAMOccupationTimeoutError, VRAMAllocatorError)


def test_internal_timeout_error_is_allocator_error_subclass() -> None:
    assert issubclass(InternalVRAMContentionTimeoutError, VRAMAllocatorError)


def test_external_occupation_timeout_raises_subclass() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        allocator.reserve(
            model_name="model-a",
            weight_vram_mb=16_000,
            preferred_device_id="0",
        )
        allocator.set_vram_probe(lambda _device_id: 0)
        allocator.set_external_vram_wait_timeout_seconds(0.02)

        with pytest.raises(ExternalVRAMOccupationTimeoutError) as error_info:
            await allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=4_000,
            )
        assert isinstance(error_info.value, VRAMAllocatorError)

    asyncio.run(scenario())


def test_internal_contention_timeout_raises_when_evict_is_disabled() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        allocator.reserve(
            model_name="model-a",
            weight_vram_mb=16_000,
            preferred_device_id="0",
        )
        allocator.reserve(
            model_name="model-b",
            weight_vram_mb=6_000,
            preferred_device_id="0",
        )
        allocator.set_evict_callback(None)
        allocator.set_internal_vram_wait_timeout_seconds(0.05)

        with pytest.raises(InternalVRAMContentionTimeoutError):
            await allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=4_000,
            )

    asyncio.run(scenario())


def test_internal_and_external_wait_timers_are_independent() -> None:
    async def internal_timeout_first() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        allocator.reserve(model_name="model-a", weight_vram_mb=16_000, preferred_device_id="0")
        allocator.reserve(model_name="model-b", weight_vram_mb=7_000, preferred_device_id="0")
        allocator.set_vram_probe(lambda _device_id: 0)
        allocator.set_external_vram_wait_timeout_seconds(1.0)
        allocator.set_internal_vram_wait_timeout_seconds(0.05)
        with pytest.raises(InternalVRAMContentionTimeoutError):
            await allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=2_000,
            )

    async def external_timeout_first() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        allocator.reserve(model_name="model-a", weight_vram_mb=16_000, preferred_device_id="0")
        allocator.reserve(model_name="model-b", weight_vram_mb=7_000, preferred_device_id="0")
        allocator.set_vram_probe(lambda _device_id: 0)
        allocator.set_external_vram_wait_timeout_seconds(0.05)
        allocator.set_internal_vram_wait_timeout_seconds(1.0)
        with pytest.raises(ExternalVRAMOccupationTimeoutError):
            await allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=2_000,
            )

    asyncio.run(internal_timeout_first())
    asyncio.run(external_timeout_first())


def test_evict_success_resets_internal_wait_round() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        allocator.reserve(
            model_name="model-a",
            weight_vram_mb=16_000,
            preferred_device_id="0",
        )
        allocator.set_internal_vram_wait_timeout_seconds(0.05)
        allocator._EVICT_WAIT_WINDOW_SECONDS = 0.01
        blocking_id = await allocator.acquire_inference(
            model_name="model-a",
            device_id="0",
            inference_vram_mb=8_000,
        )
        evict_returns: list[bool] = []

        async def evict_callback(_device_id: str, _requester_model_name: str) -> bool:
            result = len(evict_returns) >= 1
            evict_returns.append(result)
            return result

        allocator.set_evict_callback(evict_callback)

        async def release_blocking_allocation_later() -> None:
            await asyncio.sleep(0.055)
            allocator.release_inference(blocking_id)

        release_task = asyncio.create_task(release_blocking_allocation_later())
        try:
            allocation_id = await allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=8_000,
            )
        finally:
            await release_task

        assert allocation_id
        allocator.release_inference(allocation_id)
        assert evict_returns[:2] == [False, True]

    asyncio.run(scenario())


def test_metrics_hook_records_all_acquire_outcomes() -> None:
    acquire_outcomes: list[tuple[str, str]] = []
    acquire_waits: list[tuple[str, float]] = []
    evict_events: list[tuple[str, str]] = []

    hook = VRAMMetricsHook(
        on_acquire_outcome=lambda *, device, outcome: acquire_outcomes.append((device, outcome)),
        on_acquire_wait=lambda *, device, wait_seconds: acquire_waits.append(
            (device, wait_seconds)
        ),
        on_evict=lambda *, device, result: evict_events.append((device, result)),
    )

    async def scenario() -> None:
        # immediate
        immediate_allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        immediate_allocator.set_metrics_hook(hook)
        immediate_allocator.reserve(model_name="model-a", weight_vram_mb=16_000, preferred_device_id="0")
        immediate_id = await immediate_allocator.acquire_inference(
            model_name="model-a",
            device_id="0",
            inference_vram_mb=2_000,
        )
        immediate_allocator.release_inference(immediate_id)

        # after_wait
        wait_allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        wait_allocator.set_metrics_hook(hook)
        wait_allocator.reserve(model_name="model-a", weight_vram_mb=16_000, preferred_device_id="0")
        blocking_id = await wait_allocator.acquire_inference(
            model_name="model-a",
            device_id="0",
            inference_vram_mb=8_000,
        )

        async def release_wait_blocker() -> None:
            await asyncio.sleep(0.03)
            wait_allocator.release_inference(blocking_id)

        release_wait_task = asyncio.create_task(release_wait_blocker())
        try:
            waited_id = await wait_allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=8_000,
            )
        finally:
            await release_wait_task
        wait_allocator.release_inference(waited_id)

        # after_evict
        evict_allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        evict_allocator.set_metrics_hook(hook)
        evict_allocator.reserve(model_name="model-a", weight_vram_mb=16_000, preferred_device_id="0")
        evict_allocator._EVICT_WAIT_WINDOW_SECONDS = 0.01
        evict_blocking_id = await evict_allocator.acquire_inference(
            model_name="model-a",
            device_id="0",
            inference_vram_mb=8_000,
        )
        evicted_once = False

        async def evict_callback(_device_id: str, _requester_model_name: str) -> bool:
            nonlocal evicted_once
            if evicted_once:
                return False
            evicted_once = True
            evict_allocator.release_inference(evict_blocking_id)
            return True

        evict_allocator.set_evict_callback(evict_callback)
        after_evict_id = await evict_allocator.acquire_inference(
            model_name="model-a",
            device_id="0",
            inference_vram_mb=8_000,
        )
        evict_allocator.release_inference(after_evict_id)

        # timeout_internal
        internal_timeout_allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        internal_timeout_allocator.set_metrics_hook(hook)
        internal_timeout_allocator.reserve(
            model_name="model-a",
            weight_vram_mb=16_000,
            preferred_device_id="0",
        )
        internal_timeout_allocator.reserve(
            model_name="model-b",
            weight_vram_mb=6_000,
            preferred_device_id="0",
        )
        internal_timeout_allocator.set_internal_vram_wait_timeout_seconds(0.03)
        with pytest.raises(InternalVRAMContentionTimeoutError):
            await internal_timeout_allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=4_000,
            )

        # timeout_external
        external_timeout_allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        external_timeout_allocator.set_metrics_hook(hook)
        external_timeout_allocator.reserve(
            model_name="model-a",
            weight_vram_mb=16_000,
            preferred_device_id="0",
        )
        external_timeout_allocator.set_vram_probe(lambda _device_id: 0)
        external_timeout_allocator.set_external_vram_wait_timeout_seconds(0.02)
        external_timeout_allocator.set_internal_vram_wait_timeout_seconds(0.20)
        with pytest.raises(ExternalVRAMOccupationTimeoutError):
            await external_timeout_allocator.acquire_inference(
                model_name="model-a",
                device_id="0",
                inference_vram_mb=4_000,
            )

    asyncio.run(scenario())

    seen_outcomes = {outcome for _, outcome in acquire_outcomes}
    assert {
        "immediate",
        "after_wait",
        "after_evict",
        "timeout_internal",
        "timeout_external",
    } <= seen_outcomes
    assert all(wait_seconds >= 0.0 for _, wait_seconds in acquire_waits)
    assert ("0", "success") in evict_events
