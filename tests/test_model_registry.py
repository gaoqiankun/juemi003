from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path
from typing import cast

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.model_registry import (
    ModelRegistry,
    ModelRegistryLoadError,
    ModelRuntime,
)
from gen3d.engine.vram_allocator import VRAMAllocator
from gen3d.model.base import BaseModelProvider
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle


class FakeWorker:
    def __init__(self, device_id: str = "0") -> None:
        self.device_id = device_id
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1


class BlockingStopWorker(FakeWorker):
    def __init__(self, device_id: str = "0") -> None:
        super().__init__(device_id)
        self.stop_started = asyncio.Event()
        self.allow_stop = asyncio.Event()

    async def stop(self) -> None:
        self.stop_calls += 1
        self.stop_started.set()
        await self.allow_stop.wait()


async def wait_until(predicate, *, timeout_seconds: float = 1.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_model_registry_retry_after_error() -> None:
    async def scenario() -> None:
        worker = FakeWorker()
        attempts = 0

        async def runtime_loader(model_name: str) -> ModelRuntime:
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("simulated load failure")
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
            )

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
        worker = FakeWorker()

        async def runtime_loader(model_name: str) -> ModelRuntime:
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
            )

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

        async def runtime_loader(model_name: str) -> ModelRuntime:
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
            )

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


def test_get_runtime_rejects_unloading() -> None:
    async def scenario() -> None:
        worker = BlockingStopWorker()

        async def runtime_loader(model_name: str) -> ModelRuntime:
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
            )

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2")
        await registry.wait_ready("trellis2")

        unload_task = asyncio.create_task(registry.unload("trellis2"))
        await asyncio.wait_for(worker.stop_started.wait(), timeout=0.5)
        with pytest.raises(RuntimeError, match="state=unloading"):
            registry.get_runtime("trellis2")

        worker.allow_stop.set()
        await asyncio.wait_for(unload_task, timeout=0.5)

    asyncio.run(scenario())


def test_model_registry_normalize_name_keeps_empty_string() -> None:
    assert ModelRegistry._normalize_name("") == ""


def test_wait_ready_waits_for_scheduler_to_load() -> None:
    async def scenario() -> None:
        worker = FakeWorker()
        load_started = asyncio.Event()
        allow_finish = asyncio.Event()

        async def runtime_loader(model_name: str) -> ModelRuntime:
            load_started.set()
            await allow_finish.wait()
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
            )

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


def test_model_registry_load_passes_device_id_to_runtime_loader() -> None:
    async def scenario() -> None:
        worker = FakeWorker()
        seen_device_id: str | None = None

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
        ) -> ModelRuntime:
            nonlocal seen_device_id
            seen_device_id = device_id
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
            )

        registry = ModelRegistry(runtime_loader)
        registry.load("trellis2", device_id="1")
        await registry.wait_ready("trellis2")
        assert seen_device_id == "1"
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_reload_migrates_to_target_device() -> None:
    async def scenario() -> None:
        call_args: list[tuple[str | None, tuple[str, ...]]] = []
        workers_by_device: dict[str, FakeWorker] = {}

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
            exclude_device_ids: tuple[str, ...] | None = None,
        ) -> ModelRuntime:
            excluded = tuple(exclude_device_ids or ())
            call_args.append((device_id, excluded))
            target_device = device_id
            if target_device is None:
                for candidate in ("0", "1"):
                    if candidate not in set(excluded):
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
        first_runtime = await registry.wait_ready("trellis2")
        assert first_runtime.assigned_device_id == "0"

        second_runtime = await registry.reload("trellis2", exclude_device_ids=("0",))
        assert second_runtime.assigned_device_id == "1"
        assert call_args[0] == ("0", ())
        assert call_args[1] == (None, ("0",))
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_reload_updates_allocator_assignments() -> None:
    async def scenario() -> None:
        allocator = VRAMAllocator(device_totals_mb={"0": 24_000, "1": 24_000})
        workers_by_device: dict[str, FakeWorker] = {}

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
            exclude_device_ids: tuple[str, ...] | None = None,
        ) -> ModelRuntime:
            excluded = {
                candidate
                for candidate in (exclude_device_ids or ())
                if candidate in {"0", "1"}
            }
            allowed_devices = tuple(
                candidate
                for candidate in ("0", "1")
                if candidate not in excluded
            )
            assigned_device_id = allocator.reserve(
                model_name=model_name,
                weight_vram_mb=16_000,
                allowed_device_ids=allowed_devices,
                preferred_device_id=device_id,
            )
            worker = workers_by_device.setdefault(
                assigned_device_id,
                FakeWorker(assigned_device_id),
            )
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
                assigned_device_id=assigned_device_id,
            )

        registry = ModelRegistry(runtime_loader)
        registry.add_model_unloaded_listener(allocator.release)
        registry.load("trellis2", device_id="0")
        first_runtime = await registry.wait_ready("trellis2")
        assert first_runtime.assigned_device_id == "0"
        before_snapshot = allocator.snapshot()
        assert before_snapshot["0"]["allocations"] == {"trellis2": 16_000}
        assert before_snapshot["1"]["allocations"] == {}

        second_runtime = await registry.reload("trellis2", exclude_device_ids=("0",))
        assert second_runtime.assigned_device_id == "1"
        after_snapshot = allocator.snapshot()
        assert after_snapshot["0"]["allocations"] == {}
        assert after_snapshot["1"]["allocations"] == {"trellis2": 16_000}
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_reload_serialized_across_concurrent_calls() -> None:
    async def scenario() -> None:
        reload_call_count = 0
        reload_started = asyncio.Event()
        allow_reload_finish = asyncio.Event()
        workers_by_device: dict[str, FakeWorker] = {}

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
            exclude_device_ids: tuple[str, ...] | None = None,
        ) -> ModelRuntime:
            nonlocal reload_call_count
            excluded = tuple(exclude_device_ids or ())
            target_device = device_id
            if target_device is None:
                for candidate in ("0", "1"):
                    if candidate not in set(excluded):
                        target_device = candidate
                        break
            assert target_device is not None

            if excluded:
                reload_call_count += 1
                reload_started.set()
                await allow_reload_finish.wait()

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
        await registry.wait_ready("trellis2")

        tasks = [
            asyncio.create_task(
                registry.reload("trellis2", exclude_device_ids=("0",))
            )
            for _ in range(10)
        ]
        await asyncio.wait_for(reload_started.wait(), timeout=0.5)
        await asyncio.sleep(0.05)
        allow_reload_finish.set()
        runtimes = await asyncio.gather(*tasks)

        assert reload_call_count == 1
        assert len({id(runtime) for runtime in runtimes}) == 1
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_reload_does_not_touch_other_models() -> None:
    async def scenario() -> None:
        workers_by_device: dict[str, FakeWorker] = {}

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
            exclude_device_ids: tuple[str, ...] | None = None,
        ) -> ModelRuntime:
            target_device = device_id
            if target_device is None:
                for candidate in ("0", "1"):
                    if candidate not in set(exclude_device_ids or ()):
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
        registry.load("model-a", device_id="0")
        registry.load("model-b", device_id="1")
        await registry.wait_ready("model-a")
        runtime_b_before = await registry.wait_ready("model-b")

        await registry.reload("model-a", exclude_device_ids=("0",))
        runtime_b_after = registry.get_runtime("model-b")

        assert runtime_b_after is runtime_b_before
        assert runtime_b_after.assigned_device_id == "1"
        await registry.close()

    asyncio.run(scenario())


def test_model_registry_reload_failure_sets_error_state() -> None:
    async def scenario() -> None:
        unload_notifications: list[str] = []
        worker = FakeWorker("0")

        async def runtime_loader(
            model_name: str,
            device_id: str | None = None,
            exclude_device_ids: tuple[str, ...] | None = None,
        ) -> ModelRuntime:
            if exclude_device_ids:
                raise RuntimeError("reload failed")
            return ModelRuntime(
                model_name=model_name,
                provider=cast(BaseModelProvider, object()),
                workers=[cast(GPUWorkerHandle, worker)],
                scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
                assigned_device_id=device_id or "0",
            )

        registry = ModelRegistry(runtime_loader)
        registry.add_model_unloaded_listener(unload_notifications.append)
        registry.load("trellis2", device_id="0")
        await registry.wait_ready("trellis2")

        with pytest.raises(ModelRegistryLoadError):
            await registry.reload("trellis2", exclude_device_ids=("0",))
        assert registry.get_state("trellis2") == "error"
        assert unload_notifications.count("trellis2") >= 2
        with pytest.raises(RuntimeError):
            registry.get_runtime("trellis2")
        await registry.close()

    asyncio.run(scenario())
