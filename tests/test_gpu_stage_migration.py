# ruff: noqa: E402

from __future__ import annotations

import asyncio
import sys
from collections import deque
from pathlib import Path
from typing import cast

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.model_registry import ModelRegistry, ModelRuntime
from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.engine.vram_allocator import (
    ExternalVRAMOccupationTimeoutError,
    VRAMAllocatorError,
)
from gen3d.model.base import BaseModelProvider, GenerationResult
from gen3d.stages.gpu.scheduler import GPUSlot, GPUSlotScheduler, SchedulerShutdownError
from gen3d.stages.gpu.stage import GPUStage
from gen3d.stages.gpu.worker import GPUWorkerHandle


class FakeWorker:
    def __init__(self, *, worker_id: str, device_id: str) -> None:
        self.worker_id = worker_id
        self.device_id = device_id

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb=None,
    ) -> list[GenerationResult]:
        _ = prepared_inputs
        _ = options
        _ = progress_cb
        return [GenerationResult(mesh={"ok": True})]


class FakeScheduler:
    def __init__(self, outcomes: list[GPUSlot | Exception]) -> None:
        self._outcomes = deque(outcomes)
        self.acquire_calls = 0
        self.release_calls: list[str] = []

    async def acquire(
        self,
        *,
        batch_size: int = 1,
        options: dict | None = None,
    ) -> GPUSlot:
        _ = batch_size
        _ = options
        self.acquire_calls += 1
        if not self._outcomes:
            raise AssertionError("unexpected acquire call")
        outcome = self._outcomes.popleft()
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def release(self, device_id: str) -> None:
        self.release_calls.append(device_id)

    def slot_count(self) -> int:
        return 1


class FakeModelRegistry:
    def __init__(
        self,
        *,
        runtime: ModelRuntime,
        reload_runtime: ModelRuntime,
        wait_ready_runtime: ModelRuntime | None = None,
    ) -> None:
        self._runtime = runtime
        self._reload_runtime = reload_runtime
        self._wait_ready_runtime = wait_ready_runtime or reload_runtime
        self.reload_calls: list[tuple[str, tuple[str, ...]]] = []
        self.wait_ready_calls: list[str] = []

    def get_runtime(self, model_name: str) -> ModelRuntime:
        if model_name != self._runtime.model_name:
            raise RuntimeError(f"unknown model: {model_name}")
        return self._runtime

    async def reload(
        self,
        model_name: str,
        *,
        exclude_device_ids,
    ) -> ModelRuntime:
        self.reload_calls.append((model_name, tuple(exclude_device_ids)))
        self._runtime = self._reload_runtime
        return self._runtime

    async def wait_ready(
        self,
        model_name: str,
        timeout_seconds: float = 1800.0,
    ) -> ModelRuntime:
        _ = timeout_seconds
        self.wait_ready_calls.append(model_name)
        self._runtime = self._wait_ready_runtime
        return self._runtime

    def ready_models(self) -> tuple[str, ...]:
        return (self._runtime.model_name,)


class FakeTaskStore:
    async def get_task(self, task_id: str):
        _ = task_id
        return None

    async def update_stage_stats(self, *, model: str, stage: str, duration_seconds: float) -> None:
        _ = model
        _ = stage
        _ = duration_seconds
        return None


def _build_runtime(
    *,
    model_name: str,
    device_id: str,
    scheduler: FakeScheduler,
    worker: FakeWorker,
) -> ModelRuntime:
    return ModelRuntime(
        model_name=model_name,
        provider=cast(BaseModelProvider, object()),
        workers=[cast(GPUWorkerHandle, worker)],
        scheduler=cast(GPUSlotScheduler, scheduler),
        assigned_device_id=device_id,
    )


def _build_sequence(model_name: str) -> RequestSequence:
    sequence = RequestSequence.new_task(
        model=model_name,
        input_url="https://example.com/demo.png",
        options={},
    )
    sequence.transition_to(TaskStatus.PREPROCESSING)
    sequence.prepared_input = {"image_url": sequence.input_url}
    return sequence


def test_acquire_retries_once_on_external_timeout() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        old_worker = FakeWorker(worker_id="worker-0", device_id="0")
        old_scheduler = FakeScheduler(
            outcomes=[ExternalVRAMOccupationTimeoutError("external occupation timeout")]
        )
        old_runtime = _build_runtime(
            model_name=model_name,
            device_id="0",
            scheduler=old_scheduler,
            worker=old_worker,
        )

        new_worker = FakeWorker(worker_id="worker-1", device_id="1")
        new_slot = GPUSlot(device_id="1", worker=cast(GPUWorkerHandle, new_worker))
        new_scheduler = FakeScheduler(outcomes=[new_slot])
        new_runtime = _build_runtime(
            model_name=model_name,
            device_id="1",
            scheduler=new_scheduler,
            worker=new_worker,
        )
        registry = FakeModelRegistry(runtime=old_runtime, reload_runtime=new_runtime)
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        result = await stage.run(_build_sequence(model_name))

        assert result.generation_result is not None
        assert result.assigned_worker_id == "worker-1"
        assert registry.reload_calls == [(model_name, ("0",))]
        assert old_scheduler.acquire_calls == 1
        assert new_scheduler.acquire_calls == 1
        assert new_scheduler.release_calls == ["1"]

    asyncio.run(scenario())


def test_acquire_does_not_retry_on_other_vram_errors() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        worker = FakeWorker(worker_id="worker-0", device_id="0")
        scheduler = FakeScheduler(outcomes=[VRAMAllocatorError("insufficient vram")])
        runtime = _build_runtime(
            model_name=model_name,
            device_id="0",
            scheduler=scheduler,
            worker=worker,
        )
        registry = FakeModelRegistry(runtime=runtime, reload_runtime=runtime)
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        with pytest.raises(VRAMAllocatorError):
            await stage.run(_build_sequence(model_name))
        assert registry.reload_calls == []

    asyncio.run(scenario())


def test_acquire_single_migration_only() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        old_worker = FakeWorker(worker_id="worker-0", device_id="0")
        old_scheduler = FakeScheduler(
            outcomes=[ExternalVRAMOccupationTimeoutError("external timeout old device")]
        )
        old_runtime = _build_runtime(
            model_name=model_name,
            device_id="0",
            scheduler=old_scheduler,
            worker=old_worker,
        )

        new_worker = FakeWorker(worker_id="worker-1", device_id="1")
        new_scheduler = FakeScheduler(
            outcomes=[ExternalVRAMOccupationTimeoutError("external timeout new device")]
        )
        new_runtime = _build_runtime(
            model_name=model_name,
            device_id="1",
            scheduler=new_scheduler,
            worker=new_worker,
        )

        registry = FakeModelRegistry(runtime=old_runtime, reload_runtime=new_runtime)
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        with pytest.raises(ExternalVRAMOccupationTimeoutError):
            await stage.run(_build_sequence(model_name))
        assert registry.reload_calls == [(model_name, ("0",))]
        assert new_scheduler.acquire_calls == 1

    asyncio.run(scenario())


def test_retry_on_scheduler_shutdown() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        old_worker = FakeWorker(worker_id="worker-0", device_id="0")
        old_scheduler = FakeScheduler(
            outcomes=[SchedulerShutdownError("scheduler shutdown")]
        )
        old_runtime = _build_runtime(
            model_name=model_name,
            device_id="0",
            scheduler=old_scheduler,
            worker=old_worker,
        )

        new_worker = FakeWorker(worker_id="worker-1", device_id="1")
        new_slot = GPUSlot(device_id="1", worker=cast(GPUWorkerHandle, new_worker))
        new_scheduler = FakeScheduler(outcomes=[new_slot])
        new_runtime = _build_runtime(
            model_name=model_name,
            device_id="1",
            scheduler=new_scheduler,
            worker=new_worker,
        )

        registry = FakeModelRegistry(
            runtime=old_runtime,
            reload_runtime=old_runtime,
            wait_ready_runtime=new_runtime,
        )
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        result = await stage.run(_build_sequence(model_name))

        assert result.generation_result is not None
        assert result.assigned_worker_id == "worker-1"
        assert registry.reload_calls == []
        assert registry.wait_ready_calls == [model_name]
        assert old_scheduler.acquire_calls == 1
        assert new_scheduler.acquire_calls == 1
        assert new_scheduler.release_calls == ["1"]

    asyncio.run(scenario())


def test_scheduler_shutdown_and_external_timeout_share_single_retry_guard() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        old_worker = FakeWorker(worker_id="worker-0", device_id="0")
        old_scheduler = FakeScheduler(
            outcomes=[SchedulerShutdownError("scheduler shutdown")]
        )
        old_runtime = _build_runtime(
            model_name=model_name,
            device_id="0",
            scheduler=old_scheduler,
            worker=old_worker,
        )

        migrated_worker = FakeWorker(worker_id="worker-1", device_id="1")
        migrated_scheduler = FakeScheduler(
            outcomes=[ExternalVRAMOccupationTimeoutError("external timeout after shutdown")]
        )
        migrated_runtime = _build_runtime(
            model_name=model_name,
            device_id="1",
            scheduler=migrated_scheduler,
            worker=migrated_worker,
        )

        registry = FakeModelRegistry(
            runtime=old_runtime,
            reload_runtime=old_runtime,
            wait_ready_runtime=migrated_runtime,
        )
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        with pytest.raises(ExternalVRAMOccupationTimeoutError):
            await stage.run(_build_sequence(model_name))
        assert registry.reload_calls == []
        assert registry.wait_ready_calls == [model_name]
        assert old_scheduler.acquire_calls == 1
        assert migrated_scheduler.acquire_calls == 1

    asyncio.run(scenario())
