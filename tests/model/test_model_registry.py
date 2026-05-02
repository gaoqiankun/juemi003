# ruff: noqa: E402

from __future__ import annotations

import asyncio
import time
from typing import cast

import pytest

from cubie.api.server import persist_vram_estimate_measurement, update_vram_estimate
from cubie.model.base import BaseModelProvider, GenerationResult
from cubie.model.registry import (
    ModelRegistry,
    ModelRegistryLoadError,
    ModelRuntime,
)
from cubie.stage.gpu.scheduler import GPUSlotScheduler
from cubie.stage.gpu.worker import GPUWorkerHandle


class FakeGPUWorker:
    def __init__(self, device_id: str = "0") -> None:
        self.device_id = device_id
        self.worker_id = f"gpu-worker-{device_id}"
        self.start_calls = 0
        self.stop_calls = 0

    @property
    def startup_weight_mb(self) -> int | None:
        return None

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


class BlockingStopWorker(FakeGPUWorker):
    def __init__(self, device_id: str = "0") -> None:
        super().__init__(device_id)
        self.stop_started = asyncio.Event()
        self.allow_stop = asyncio.Event()

    async def stop(self) -> None:
        self.stop_calls += 1
        self.stop_started.set()
        await self.allow_stop.wait()


def _build_runtime(model_name: str, worker: FakeGPUWorker) -> ModelRuntime:
    return ModelRuntime(
        model_name=model_name,
        provider=cast(BaseModelProvider, object()),
        workers=[cast(GPUWorkerHandle, worker)],
        scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
        assigned_device_id=worker.device_id,
    )


async def wait_until(predicate, *, timeout_seconds: float = 1.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_model_registry_retry_after_error() -> None:
    async def scenario() -> None:
        attempts = 0

        def runtime_loader(model_name: str) -> ModelRuntime:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("simulated load failure")
            return _build_runtime(model_name, FakeGPUWorker("0"))

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2")
        await wait_until(lambda: registry.get_state("trellis2") == "error")

        registry.load("trellis2")
        runtime = await registry.wait_ready("trellis2")
        assert runtime.model_name == "trellis2"
        assert registry.get_state("trellis2") == "ready"
        assert attempts == 2
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_unload() -> None:
    async def scenario() -> None:
        worker = FakeGPUWorker("0")

        def runtime_loader(model_name: str) -> ModelRuntime:
            return _build_runtime(model_name, worker)

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2")
        await registry.wait_ready("trellis2")
        assert registry.get_state("trellis2") == "ready"

        await registry.unload("trellis2")
        assert registry.get_state("trellis2") == "not_loaded"
        assert registry.get_error("trellis2") is None
        assert worker.stop_calls == 1
        with pytest.raises(RuntimeError):
            registry.get_runtime("trellis2")
        await registry.close()

    asyncio.run(scenario())


def test_unload_sets_intermediate_state() -> None:
    async def scenario() -> None:
        worker = BlockingStopWorker()

        def runtime_loader(model_name: str) -> ModelRuntime:
            return _build_runtime(model_name, worker)

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2")
        await registry.wait_ready("trellis2")

        unload_task = asyncio.create_task(registry.unload("trellis2"))
        await asyncio.wait_for(worker.stop_started.wait(), timeout=0.5)
        assert registry.get_state("trellis2") == "unloading"

        worker.allow_stop.set()
        await asyncio.wait_for(unload_task, timeout=0.5)
        assert registry.get_state("trellis2") == "not_loaded"

    asyncio.run(scenario())


def test_wait_ready_waits_for_scheduler_to_load() -> None:
    async def scenario() -> None:
        load_started = asyncio.Event()
        allow_finish = asyncio.Event()

        async def runtime_loader(model_name: str) -> ModelRuntime:
            load_started.set()
            await allow_finish.wait()
            return _build_runtime(model_name, FakeGPUWorker("0"))

        registry = ModelRegistry(runtime_loader)
        wait_task = asyncio.create_task(registry.wait_ready("trellis2", timeout_seconds=1.0))
        await asyncio.sleep(0.05)
        assert not wait_task.done()
        assert registry.get_state("trellis2") == "not_loaded"

        registry.load("trellis2")
        await asyncio.wait_for(load_started.wait(), timeout=0.5)
        assert registry.get_state("trellis2") == "loading"

        allow_finish.set()
        runtime = await asyncio.wait_for(wait_task, timeout=0.5)
        assert runtime.model_name == "trellis2"
        assert registry.get_state("trellis2") == "ready"
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_reload_replaces_runtime() -> None:
    async def scenario() -> None:
        call_index = 0

        def runtime_loader(model_name: str) -> ModelRuntime:
            nonlocal call_index
            device_id = str(call_index)
            call_index += 1
            return _build_runtime(model_name, FakeGPUWorker(device_id))

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2")
        first_runtime = await registry.wait_ready("trellis2")

        second_runtime = await registry.reload("trellis2", exclude_device_ids=("0",))

        assert first_runtime is not second_runtime
        assert registry.get_state("trellis2") == "ready"
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_wait_ready_surfaces_error_state() -> None:
    async def scenario() -> None:
        def runtime_loader(_model_name: str) -> ModelRuntime:
            raise RuntimeError("boom")

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2")

        with pytest.raises(ModelRegistryLoadError):
            await registry.wait_ready("trellis2")
        assert registry.get_state("trellis2") == "error"

    asyncio.run(scenario())


def test_model_registry_normalize_name_keeps_empty_string() -> None:
    assert ModelRegistry.normalize_name("") == ""


def test_update_vram_estimate_weight_uses_measured_value() -> None:
    first_measurement = update_vram_estimate(
        "trellis2",
        "weight_vram_mb",
        12_000,
        stored_mb=None,
    )
    assert first_measurement.should_update is True
    assert first_measurement.new_mb == 12_000

    changed_measurement = update_vram_estimate(
        "trellis2",
        "weight_vram_mb",
        10_900,
        stored_mb=10_000,
    )
    assert changed_measurement.should_update is True
    assert changed_measurement.new_mb == 10_900


def test_persist_vram_estimate_measurement_weight_uses_measured_value() -> None:
    class FakeModelStore:
        def __init__(self) -> None:
            self.model = {
                "id": "trellis2",
                "weight_vram_mb": 10_000,
                "inference_vram_mb": 5_000,
            }
            self.updates: list[tuple[str, dict[str, object]]] = []

        async def get_model(self, model_id: str) -> dict[str, object] | None:
            if model_id == "trellis2":
                return dict(self.model)
            return None

        async def update_model(self, model_id: str, **updates: object) -> dict[str, object]:
            self.updates.append((model_id, dict(updates)))
            self.model.update(updates)
            return dict(self.model)

    async def scenario() -> None:
        store = FakeModelStore()

        decision = await persist_vram_estimate_measurement(
            store,  # type: ignore[arg-type]
            model_id="trellis2",
            field_name="weight_vram_mb",
            measured_mb=12_600,
            device_id="0",
        )

        assert decision is not None
        assert decision.should_update is True
        assert store.updates == [("trellis2", {"weight_vram_mb": 12_600})]

    asyncio.run(scenario())
