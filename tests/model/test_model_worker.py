# ruff: noqa: E402

from __future__ import annotations

import asyncio
from typing import Any, Callable, cast

import pytest

from cubie.model.base import BaseModelProvider, GenerationResult
from cubie.model.registry import ModelRuntime
from cubie.model.worker import ModelWorker
from cubie.stage.gpu.scheduler import GPUSlotScheduler
from cubie.stage.gpu.worker import GPUWorkerHandle
from cubie.vram.allocator import VRAMAllocator, WeightAllocation


class FakeModelStore:
    def __init__(self, rows: dict[str, dict[str, Any]]) -> None:
        self._rows = {key: dict(value) for key, value in rows.items()}
        self.updates: list[tuple[str, dict[str, object]]] = []

    async def get_model(self, model_id: str) -> dict[str, Any] | None:
        row = self._rows.get(model_id)
        return dict(row) if row is not None else None

    async def update_model(self, model_id: str, **updates: object) -> dict[str, Any] | None:
        row = self._rows.setdefault(model_id, {"id": model_id})
        row.update(updates)
        self.updates.append((model_id, dict(updates)))
        return dict(row)


class FakeGPUWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        device_id: str,
        startup_weight_mb: int,
        outcomes: list[Exception | list[GenerationResult]],
        measurement_callback: Callable[[str, str, int], None] | None,
        model_id: str,
        measured_peak_mb: int = 2400,
    ) -> None:
        self.worker_id = worker_id
        self.device_id = device_id
        self.startup_weight_mb = startup_weight_mb
        self._outcomes = list(outcomes)
        self._measurement_callback = measurement_callback
        self._model_id = model_id
        self._measured_peak_mb = measured_peak_mb
        self.start_calls = 0
        self.stop_calls = 0
        self.run_calls = 0

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
        self.run_calls += 1
        if not self._outcomes:
            result = [GenerationResult(mesh={"ok": True})]
        else:
            outcome = self._outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            result = outcome
        if self._measurement_callback is not None:
            self._measurement_callback(
                self._model_id,
                self.device_id,
                self._measured_peak_mb,
            )
        return result


class BusyWorker:
    def __init__(
        self,
        *,
        allocator: VRAMAllocator,
        model_id: str,
        weight_allocation: WeightAllocation,
    ) -> None:
        self._allocator = allocator
        self._model_id = model_id
        self._weight_allocation = weight_allocation
        self.device_id = weight_allocation.device_id
        self.weight_allocated = True
        self.inference_busy = True
        self.evicting = False
        self.last_used_tick = 1

    async def evict(self) -> None:
        pytest.fail("busy worker should not be evicted")


def _runtime_with_worker(model_name: str, worker: FakeGPUWorker) -> ModelRuntime:
    return ModelRuntime(
        model_name=model_name,
        provider=cast(BaseModelProvider, object()),
        workers=[cast(GPUWorkerHandle, worker)],
        scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
        assigned_device_id=worker.device_id,
    )


def test_model_worker_evict_flow_releases_weight_and_unregisters() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        store = FakeModelStore(
            {
                "trellis2": {
                    "id": "trellis2",
                    "weight_vram_mb": 12_000,
                    "inference_vram_mb": 2_000,
                }
            }
        )
        created_workers: list[FakeGPUWorker] = []

        async def factory(model_name: str, *, device_id: str, measurement_callback=None):
            worker = FakeGPUWorker(
                worker_id=f"gpu-{device_id}",
                device_id=device_id,
                startup_weight_mb=12_500,
                outcomes=[[GenerationResult(mesh={"ok": True})]],
                measurement_callback=measurement_callback,
                model_id=model_name,
            )
            created_workers.append(worker)
            return _runtime_with_worker(model_name, worker)

        worker = ModelWorker("trellis2", allocator, factory, store)
        await worker.load()

        assert worker.weight_allocated is True
        assert allocator.assignment_for("trellis2") == "0"

        await worker.evict()

        assert worker.weight_allocated is False
        assert allocator.assignment_for("trellis2") is None
        assert created_workers[0].stop_calls == 1

    asyncio.run(scenario())


def test_model_worker_migrates_on_inference_allocation_response() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000, "1": 24_000})
        allocator._MIGRATION_WAIT_SECONDS = 0.01
        store = FakeModelStore(
            {
                "model-a": {
                    "id": "model-a",
                    "weight_vram_mb": 12_000,
                    "inference_vram_mb": 4_000,
                },
                "blocker": {
                    "id": "blocker",
                    "weight_vram_mb": 9_000,
                    "inference_vram_mb": 2_000,
                },
            }
        )
        created_workers: list[FakeGPUWorker] = []

        async def factory(model_name: str, *, device_id: str, measurement_callback=None):
            worker = FakeGPUWorker(
                worker_id=f"gpu-{device_id}-{len(created_workers)}",
                device_id=device_id,
                startup_weight_mb=12_000,
                outcomes=[[GenerationResult(mesh={"ok": True})]],
                measurement_callback=measurement_callback,
                model_id=model_name,
            )
            created_workers.append(worker)
            return _runtime_with_worker(model_name, worker)

        worker = ModelWorker("model-a", allocator, factory, store)
        await worker.load()
        assert worker.device_id == "0"

        blocker_weight = await allocator.request_weight("blocker", 9_000)
        blocker = BusyWorker(
            allocator=allocator,
            model_id="blocker",
            weight_allocation=blocker_weight,
        )
        allocator.register_worker("blocker", blocker)

        lease = allocator.reserve_for_task(
            model_id="model-a",
            estimate_mb=worker.estimate_inference_mb({}),
            weight_mb=worker.weight_vram_mb,
        )
        async with lease:
            await worker.apply_inference_allocation(lease.allocation)
            result = await worker.run_batch(
                batch=[{"image_url": "https://example.com/demo.png"}],
                options={},
                progress_cb=None,
            )

        assert result[0].mesh == {"ok": True}
        assert worker.device_id == "1"
        assert allocator.assignment_for("model-a") == "1"
        assert len(created_workers) >= 2

    asyncio.run(scenario())


def test_model_worker_public_inference_estimate_helpers() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000})
        store = FakeModelStore(
            {
                "trellis2": {
                    "id": "trellis2",
                    "weight_vram_mb": 8_000,
                    "inference_vram_mb": 1_000,
                }
            }
        )
        created_workers: list[FakeGPUWorker] = []

        async def factory(model_name: str, *, device_id: str, measurement_callback=None):
            worker = FakeGPUWorker(
                worker_id=f"gpu-{device_id}",
                device_id=device_id,
                startup_weight_mb=8_000,
                outcomes=[[GenerationResult(mesh={"ok": True})]],
                measurement_callback=measurement_callback,
                model_id=model_name,
                measured_peak_mb=2_200,
            )
            created_workers.append(worker)
            return _runtime_with_worker(model_name, worker)

        worker = ModelWorker("trellis2", allocator, factory, store)
        await worker.load()

        estimate = worker.estimate_inference_mb({})
        assert estimate == 1_000

        result = await worker.run_batch(
            batch=[{"image_url": "https://example.com/demo.png"}],
            options={},
            progress_cb=None,
        )
        await worker.apply_successful_inference_measurement()

        assert result[0].mesh == {"ok": True}
        assert created_workers[0].run_calls == 1
        assert worker.inference_vram_mb >= 2_200

        worker.on_inference_measured("trellis2", "0", 2_600)
        bump_target_mb = worker.resolve_oom_bump_target_mb()
        assert bump_target_mb >= 2_600
        await worker.apply_oom_bump_target_mb(bump_target_mb)
        assert worker.inference_vram_mb > 1_000
        assert any(
            model_id == "trellis2" and "inference_vram_mb" in updates
            for model_id, updates in store.updates
        )

    asyncio.run(scenario())
