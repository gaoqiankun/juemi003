# ruff: noqa: E402

from __future__ import annotations

from typing import Any, Callable, cast

from cubie.model.base import BaseModelProvider, GenerationResult
from cubie.model.registry import ModelRuntime
from cubie.model.worker import ModelWorker
from cubie.stage.base import BaseStage, StageExecutionError, StageUpdateHandler
from cubie.stage.gpu.scheduler import GPUSlotScheduler
from cubie.stage.gpu.worker import GPUWorkerHandle
from cubie.task.sequence import RequestSequence, TaskStatus
from cubie.vram.allocator import VRAMAllocator


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


class ScriptedGPUWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        device_id: str,
        startup_weight_mb: int,
        outcomes: list[Exception | list[GenerationResult]],
        measurement_callback: Callable[[str, str, int], None] | None,
        model_id: str,
        measured_peak_mb: int = 2_400,
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


class FakeTaskStore:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    async def update_task(
        self,
        sequence: RequestSequence,
        *,
        event: str,
        metadata: dict[str, Any],
    ) -> None:
        self.events.append((sequence.task_id, event, dict(metadata)))

    async def get_task(self, task_id: str):
        _ = task_id
        return None

    async def list_incomplete_tasks(self) -> list[RequestSequence]:
        return []

    async def requeue_task(self, task_id: str) -> None:
        _ = task_id
        return None


class FakeRegistry:
    def __init__(self, worker: ModelWorker) -> None:
        self._worker = worker

    def get_worker(self, model_name: str) -> ModelWorker | None:
        if model_name != self._worker.model_id:
            return None
        return self._worker


class TrackingVRAMAllocator(VRAMAllocator):
    def __init__(self, *, device_totals_mb: dict[str, int]) -> None:
        super().__init__(device_totals_mb=device_totals_mb)
        self.requested_inference_ids: list[str] = []
        self.released_inference_ids: list[str] = []

    async def request_inference(
        self,
        model_id: str,
        device_id: str,
        inference_mb: int,
        weight_mb: int,
    ):
        allocation = await super().request_inference(
            model_id=model_id,
            device_id=device_id,
            inference_mb=inference_mb,
            weight_mb=weight_mb,
        )
        self.requested_inference_ids.append(str(allocation.inference_allocation_id))
        return allocation

    def release_inference(self, allocation_id) -> None:
        self.released_inference_ids.append(str(allocation_id))
        super().release_inference(allocation_id)


class LeaseGPUStage(BaseStage):
    name = "gpu"

    def __init__(self, worker: ModelWorker) -> None:
        self._worker = worker

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        sequence.transition_to(
            TaskStatus.GPU_QUEUED,
            current_stage=TaskStatus.GPU_QUEUED.value,
            queue_position=0,
            estimated_wait_seconds=0,
        )
        await self._emit_update(sequence, on_update)

        sequence.assigned_worker_id = self._worker.worker_id
        try:
            results = await self._worker.run_batch(
                batch=[sequence.prepared_input or {"image_url": sequence.input_url}],
                options=sequence.options,
                progress_cb=None,
            )
        except Exception as exc:  # pragma: no cover - exercised by OOM test
            raise StageExecutionError(TaskStatus.GPU_SS.value, str(exc)) from exc

        for status in (TaskStatus.GPU_SS, TaskStatus.GPU_SHAPE, TaskStatus.GPU_MATERIAL):
            sequence.transition_to(status, current_stage=status.value)
            await self._emit_update(sequence, on_update)
        sequence.generation_result = results[0]
        return sequence


class LeaseExportStage(BaseStage):
    name = "export"

    def __init__(self, allocator: VRAMAllocator, *, fail: bool = False) -> None:
        self._allocator = allocator
        self._fail = fail
        self.observed_inference_mb: list[int] = []

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        sequence.transition_to(TaskStatus.EXPORTING, current_stage=TaskStatus.EXPORTING.value)
        await self._emit_update(sequence, on_update)
        self.observed_inference_mb.append(
            int(self._allocator.snapshot()["0"]["used_inference_vram_mb"])
        )
        if self._fail:
            raise StageExecutionError(TaskStatus.EXPORTING.value, "export failed")

        sequence.generation_result = None
        sequence.transition_to(TaskStatus.UPLOADING, current_stage=TaskStatus.UPLOADING.value)
        await self._emit_update(sequence, on_update)
        sequence.transition_to(TaskStatus.SUCCEEDED, current_stage=TaskStatus.SUCCEEDED.value)
        await self._emit_update(
            sequence,
            on_update,
            event="succeeded",
            metadata={"status": sequence.status.value, "stage": TaskStatus.UPLOADING.value},
        )
        return sequence


def runtime_with_worker(model_name: str, worker: ScriptedGPUWorker) -> ModelRuntime:
    return ModelRuntime(
        model_name=model_name,
        provider=cast(BaseModelProvider, object()),
        workers=[cast(GPUWorkerHandle, worker)],
        scheduler=GPUSlotScheduler([cast(GPUWorkerHandle, worker)]),
        assigned_device_id=worker.device_id,
    )


async def build_loaded_worker(
    *,
    allocator: VRAMAllocator,
    outcomes: list[Exception | list[GenerationResult]],
    measured_peak_mb: int = 2_400,
) -> tuple[ModelWorker, ScriptedGPUWorker]:
    store = FakeModelStore(
        {"trellis2": {"id": "trellis2", "weight_vram_mb": 8_000, "inference_vram_mb": 1_000}}
    )
    created_workers: list[ScriptedGPUWorker] = []

    async def factory(model_name: str, *, device_id: str, measurement_callback=None):
        scripted_worker = ScriptedGPUWorker(
            worker_id=f"gpu-{device_id}",
            device_id=device_id,
            startup_weight_mb=8_000,
            outcomes=outcomes,
            measurement_callback=measurement_callback,
            model_id=model_name,
            measured_peak_mb=measured_peak_mb,
        )
        created_workers.append(scripted_worker)
        return runtime_with_worker(model_name, scripted_worker)

    worker = ModelWorker("trellis2", allocator, factory, store)
    await worker.load()
    return worker, created_workers[0]


def build_sequence(model_name: str = "trellis2") -> RequestSequence:
    sequence = RequestSequence.new_task(
        model=model_name,
        input_url="https://example.com/demo.png",
        options={},
    )
    sequence.transition_to(TaskStatus.PREPROCESSING)
    sequence.prepared_input = {"image_url": sequence.input_url}
    return sequence
