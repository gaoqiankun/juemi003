# ruff: noqa: E402

from __future__ import annotations

import asyncio
from collections import deque
from typing import cast

import pytest

from cubie.model.base import BaseModelProvider, GenerationResult
from cubie.model.gpu import GPUWorkerHandle
from cubie.model.gpu_scheduler import GPUSlot, GPUSlotScheduler
from cubie.model.registry import ModelRegistry, ModelRuntime
from cubie.stage.gpu.stage import GPUStage
from cubie.task.sequence import RequestSequence, TaskStatus
from cubie.vram.allocator import InternalVRAMContentionTimeoutError


class FakeMigratingWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        device_id: str,
        migrate_to_device: str | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.device_id = device_id
        self._migrate_to_device = migrate_to_device
        self.run_calls = 0

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
        self.run_calls += 1
        if self._migrate_to_device is not None:
            self.device_id = self._migrate_to_device
            self._migrate_to_device = None
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
    def __init__(self, *, runtime: ModelRuntime) -> None:
        self._runtime = runtime

    def get_runtime(self, model_name: str) -> ModelRuntime:
        if model_name != self._runtime.model_name:
            raise RuntimeError(f"unknown model: {model_name}")
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
    scheduler: FakeScheduler,
    worker: FakeMigratingWorker,
    device_id: str,
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


def test_stage_relies_on_worker_for_migration() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        worker = FakeMigratingWorker(
            worker_id="worker-0",
            device_id="0",
            migrate_to_device="1",
        )
        slot = GPUSlot(device_id="0", worker=cast(GPUWorkerHandle, worker))
        scheduler = FakeScheduler(outcomes=[slot])
        runtime = _build_runtime(
            model_name=model_name,
            scheduler=scheduler,
            worker=worker,
            device_id="0",
        )
        registry = FakeModelRegistry(runtime=runtime)
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        result = await stage.run(_build_sequence(model_name))

        assert result.generation_result is not None
        assert result.assigned_worker_id == "worker-0"
        assert scheduler.release_calls == ["0"]
        assert worker.run_calls == 1
        assert worker.device_id == "1"

    asyncio.run(scenario())


def test_stage_propagates_internal_vram_contention_timeout() -> None:
    async def scenario() -> None:
        model_name = "trellis2"
        worker = FakeMigratingWorker(worker_id="worker-0", device_id="0")
        scheduler = FakeScheduler(
            outcomes=[InternalVRAMContentionTimeoutError("internal contention timeout")]
        )
        runtime = _build_runtime(
            model_name=model_name,
            scheduler=scheduler,
            worker=worker,
            device_id="0",
        )
        registry = FakeModelRegistry(runtime=runtime)
        stage = GPUStage(
            delay_ms=0,
            model_registry=cast(ModelRegistry, registry),
            task_store=FakeTaskStore(),
        )

        with pytest.raises(InternalVRAMContentionTimeoutError):
            await stage.run(_build_sequence(model_name))

    asyncio.run(scenario())
