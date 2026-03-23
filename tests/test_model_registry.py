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

from gen3d.engine.model_registry import ModelRegistry, ModelRegistryLoadError, ModelRuntime
from gen3d.model.base import BaseModelProvider
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle


class FakeWorker:
    def __init__(self) -> None:
        self.device_id = "0"
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        self.start_calls += 1

    async def stop(self) -> None:
        self.stop_calls += 1


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


def test_model_registry_normalize_name_keeps_empty_string() -> None:
    assert ModelRegistry._normalize_name("") == ""


def test_wait_ready_raises_if_not_loading() -> None:
    async def scenario() -> None:
        async def runtime_loader(model_name: str) -> ModelRuntime:
            raise AssertionError(f"runtime_loader should not be called for {model_name}")

        registry = ModelRegistry(runtime_loader)
        with pytest.raises(ModelRegistryLoadError, match="is not loading"):
            await registry.wait_ready("trellis2")

    asyncio.run(scenario())
