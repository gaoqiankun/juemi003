# ruff: noqa: E402

from __future__ import annotations

import asyncio
from typing import Any, cast

from gen3d.model.base import GenerationResult
from gen3d.task.pipeline import PipelineCoordinator
from gen3d.task.sequence import TaskStatus

from tests.inference_lease_test_utils import (
    FakeRegistry,
    FakeTaskStore,
    LeaseExportStage,
    LeaseGPUStage,
    TrackingVRAMAllocator,
    build_loaded_worker,
    build_sequence,
)


def test_pipeline_lease_spans_gpu_and_export() -> None:
    async def scenario() -> None:
        allocator = TrackingVRAMAllocator(device_totals_mb={"0": 24_000})
        worker, scripted_worker = await build_loaded_worker(
            allocator=allocator,
            outcomes=[[GenerationResult(mesh={"ok": True})]],
        )
        export_stage = LeaseExportStage(allocator)
        pipeline = PipelineCoordinator(
            task_store=FakeTaskStore(),
            stages=[LeaseGPUStage(worker), export_stage],
            inference_allocator=allocator,
            model_registry=cast(Any, FakeRegistry(worker)),
        )

        result = await pipeline.run_sequence(build_sequence())

        assert result.status == TaskStatus.SUCCEEDED
        assert scripted_worker.run_calls == 1
        assert export_stage.observed_inference_mb
        assert export_stage.observed_inference_mb[0] > 0
        assert allocator.snapshot()["0"]["used_inference_vram_mb"] == 0
        assert worker.inference_busy is False

    asyncio.run(scenario())


def test_pipeline_oom_retry_rebooks_lease_allocation_once() -> None:
    async def scenario() -> None:
        allocator = TrackingVRAMAllocator(device_totals_mb={"0": 24_000})
        worker, scripted_worker = await build_loaded_worker(
            allocator=allocator,
            outcomes=[
                RuntimeError("CUDA out of memory"),
                [GenerationResult(mesh={"ok": True})],
            ],
        )
        export_stage = LeaseExportStage(allocator)
        pipeline = PipelineCoordinator(
            task_store=FakeTaskStore(),
            stages=[LeaseGPUStage(worker), export_stage],
            inference_allocator=allocator,
            model_registry=cast(Any, FakeRegistry(worker)),
        )

        result = await pipeline.run_sequence(build_sequence())

        assert result.status == TaskStatus.SUCCEEDED
        assert scripted_worker.run_calls == 2
        assert len(allocator.requested_inference_ids) == 2
        assert allocator.requested_inference_ids[0] != allocator.requested_inference_ids[1]
        assert allocator.requested_inference_ids[0] in allocator.released_inference_ids
        assert allocator.snapshot()["0"]["used_inference_vram_mb"] == 0

    asyncio.run(scenario())


def test_pipeline_releases_lease_on_export_failure() -> None:
    async def scenario() -> None:
        allocator = TrackingVRAMAllocator(device_totals_mb={"0": 24_000})
        worker, scripted_worker = await build_loaded_worker(
            allocator=allocator,
            outcomes=[[GenerationResult(mesh={"ok": True})]],
        )
        export_stage = LeaseExportStage(allocator, fail=True)
        pipeline = PipelineCoordinator(
            task_store=FakeTaskStore(),
            stages=[LeaseGPUStage(worker), export_stage],
            inference_allocator=allocator,
            model_registry=cast(Any, FakeRegistry(worker)),
        )

        result = await pipeline.run_sequence(build_sequence())

        assert result.status == TaskStatus.FAILED
        assert result.failed_stage == TaskStatus.EXPORTING.value
        assert scripted_worker.run_calls == 1
        assert allocator.snapshot()["0"]["used_inference_vram_mb"] == 0
        assert worker.inference_busy is False

    asyncio.run(scenario())
