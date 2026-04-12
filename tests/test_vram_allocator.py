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
    VRAMAllocator,
    VRAMAllocatorError,
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
