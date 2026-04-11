from __future__ import annotations

import sys
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.vram_allocator import VRAMAllocator, VRAMAllocatorError


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
