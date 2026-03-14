from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.async_engine import AsyncGen3DEngine
from gen3d.engine.pipeline import PipelineCoordinator
from gen3d.engine.sequence import TaskStatus, TaskType
from gen3d.model.trellis2.provider import MockTrellis2Provider
from gen3d.stages.export.stage import ExportStage
from gen3d.stages.gpu.stage import GPUStage
from gen3d.stages.gpu.worker import GPUWorker
from gen3d.stages.preprocess.stage import PreprocessStage
from gen3d.storage.artifact_store import ArtifactStore, ArtifactStoreOperationError
from gen3d.storage.task_store import TaskStore

SAMPLE_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z/C/HwAF/gL+Q6UkWQAAAABJRU5ErkJggg=="
)


class FakeObjectStorageClient:
    def __init__(self, *, fail_on_presign: bool = False) -> None:
        self.fail_on_presign = fail_on_presign
        self.validated_bucket: str | None = None
        self.uploads: list[dict[str, object]] = []

    def ensure_bucket_exists(self, bucket: str) -> None:
        self.validated_bucket = bucket

    def upload_file(
        self,
        *,
        bucket: str,
        key: str,
        source_path: Path,
        content_type: str | None = None,
    ) -> None:
        self.uploads.append(
            {
                "bucket": bucket,
                "key": key,
                "content_type": content_type,
                "body": source_path.read_bytes(),
            }
        )

    def generate_presigned_get_url(
        self,
        *,
        bucket: str,
        key: str,
        expires_in_seconds: int,
    ) -> str:
        if self.fail_on_presign:
            raise RuntimeError("presign boom")
        return (
            f"http://minio.test/{bucket}/{key}"
            f"?X-Amz-Expires={expires_in_seconds}&X-Amz-Signature=fake"
        )


def build_engine(
    tmp_path: Path,
    *,
    queue_delay_ms: int = 10,
) -> tuple[TaskStore, ArtifactStore, AsyncGen3DEngine]:
    task_store = TaskStore(tmp_path / "pipeline.sqlite3")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    provider = MockTrellis2Provider(stage_delay_ms=20)
    worker = GPUWorker(worker_id="test-worker", provider=provider)
    pipeline = PipelineCoordinator(
        task_store=task_store,
        stages=[
            PreprocessStage(delay_ms=10),
            GPUStage(delay_ms=queue_delay_ms, worker=worker, task_store=task_store),
            ExportStage(provider=provider, artifact_store=artifact_store, delay_ms=10),
        ],
    )
    engine = AsyncGen3DEngine(
        task_store=task_store,
        pipeline=pipeline,
        artifact_store=artifact_store,
    )
    return task_store, artifact_store, engine


def test_pipeline_persists_full_success_history(tmp_path: Path) -> None:
    async def scenario() -> None:
        task_store, artifact_store, engine = build_engine(tmp_path)
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            sequence, created = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
            )
            assert created is True

            deadline = time.time() + 3
            current = await engine.get_task(sequence.task_id)
            while current is not None and current.status != TaskStatus.SUCCEEDED:
                if time.time() >= deadline:
                    raise AssertionError("task did not reach succeeded in time")
                await asyncio.sleep(0.01)
                current = await engine.get_task(sequence.task_id)

            assert current is not None
            assert current.status == TaskStatus.SUCCEEDED
            assert current.artifacts
            assert current.artifacts[0]["url"].startswith(
                f"/v1/tasks/{sequence.task_id}/artifacts/"
            )

            events = await task_store.list_task_events(sequence.task_id)
            event_statuses = [event["metadata"].get("status") for event in events]
            assert event_statuses == [
                "submitted",
                "preprocessing",
                "gpu_queued",
                "gpu_ss",
                "gpu_shape",
                "gpu_material",
                "exporting",
                "uploading",
                "succeeded",
            ]
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_pipeline_persists_failed_stage_diagnostics(tmp_path: Path) -> None:
    async def scenario() -> None:
        task_store, artifact_store, engine = build_engine(tmp_path)
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            sequence, _ = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url=SAMPLE_IMAGE_DATA_URL,
                options={
                    "resolution": 1024,
                    "mock_failure_stage": "exporting",
                },
            )

            deadline = time.time() + 3
            current = await engine.get_task(sequence.task_id)
            while current is not None and current.status != TaskStatus.FAILED:
                if time.time() >= deadline:
                    raise AssertionError("task did not reach failed in time")
                await asyncio.sleep(0.01)
                current = await engine.get_task(sequence.task_id)

            assert current is not None
            assert current.status == TaskStatus.FAILED
            assert current.failed_stage == "exporting"
            assert current.error_message == "mock failure injected at exporting"

            events = await task_store.list_task_events(sequence.task_id)
            assert events[-1]["event"] == "failed"
            assert events[-1]["metadata"]["stage"] == "exporting"
            assert events[-1]["metadata"]["message"] == "mock failure injected at exporting"
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_pipeline_persists_uploading_failure_diagnostics(tmp_path: Path) -> None:
    async def scenario() -> None:
        task_store, artifact_store, engine = build_engine(tmp_path)
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            sequence, _ = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url=SAMPLE_IMAGE_DATA_URL,
                options={
                    "resolution": 1024,
                    "mock_failure_stage": "uploading",
                },
            )

            deadline = time.time() + 3
            current = await engine.get_task(sequence.task_id)
            while current is not None and current.status != TaskStatus.FAILED:
                if time.time() >= deadline:
                    raise AssertionError("task did not reach failed in time")
                await asyncio.sleep(0.01)
                current = await engine.get_task(sequence.task_id)

            assert current is not None
            assert current.status == TaskStatus.FAILED
            assert current.failed_stage == "uploading"
            assert current.error_message == "mock failure injected at uploading"

            events = await task_store.list_task_events(sequence.task_id)
            assert events[-2]["metadata"]["status"] == "uploading"
            assert events[-1]["event"] == "failed"
            assert events[-1]["metadata"]["stage"] == "uploading"
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_pipeline_records_cancelled_event_for_gpu_queued_task(tmp_path: Path) -> None:
    async def scenario() -> None:
        task_store, artifact_store, engine = build_engine(tmp_path, queue_delay_ms=200)
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            sequence, _ = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
            )

            deadline = time.time() + 3
            current = await engine.get_task(sequence.task_id)
            while current is not None and current.status != TaskStatus.GPU_QUEUED:
                if time.time() >= deadline:
                    raise AssertionError("task did not reach gpu_queued in time")
                await asyncio.sleep(0.01)
                current = await engine.get_task(sequence.task_id)

            cancel_result = await engine.cancel_task(sequence.task_id)
            assert cancel_result.outcome == "cancelled"

            current = await engine.get_task(sequence.task_id)
            assert current is not None
            assert current.status == TaskStatus.CANCELLED

            events = await task_store.list_task_events(sequence.task_id)
            assert events[-1]["event"] == "cancelled"
            assert events[-1]["metadata"]["status"] == "cancelled"
            assert events[-1]["metadata"]["current_stage"] == "cancelled"
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_minio_artifact_store_returns_presigned_metadata_without_real_minio(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        fake_client = FakeObjectStorageClient()
        artifact_store = ArtifactStore(
            tmp_path / "artifacts",
            mode="minio",
            object_store_client=fake_client,
            object_store_bucket="gen3d-artifacts",
            object_store_presign_ttl_seconds=900,
        )
        await artifact_store.initialize()

        async with artifact_store.create_staging_path("task-1", "model.glb") as staging_path:
            staging_path.write_bytes(b"GLB")
            artifact = await artifact_store.publish_artifact(
                task_id="task-1",
                artifact_type="glb",
                file_name="model.glb",
                staging_path=staging_path,
            )

        listed = await artifact_store.list_artifacts("task-1")

        assert fake_client.validated_bucket == "gen3d-artifacts"
        assert fake_client.uploads[0]["bucket"] == "gen3d-artifacts"
        assert fake_client.uploads[0]["key"] == "artifacts/task-1/model.glb"
        assert fake_client.uploads[0]["content_type"] == "model/gltf-binary"
        assert fake_client.uploads[0]["body"] == b"GLB"
        assert artifact["backend"] == "minio"
        assert artifact["url"].startswith("http://minio.test/gen3d-artifacts/artifacts/task-1/model.glb")
        assert artifact["content_type"] == "model/gltf-binary"
        assert artifact["expires_at"] is not None
        assert listed == [artifact]

    asyncio.run(scenario())


def test_minio_artifact_store_surfaces_presign_failures_as_uploading_errors(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        artifact_store = ArtifactStore(
            tmp_path / "artifacts",
            mode="minio",
            object_store_client=FakeObjectStorageClient(fail_on_presign=True),
            object_store_bucket="gen3d-artifacts",
        )
        await artifact_store.initialize()

        async with artifact_store.create_staging_path("task-2", "model.glb") as staging_path:
            staging_path.write_bytes(b"GLB")
            with pytest.raises(
                ArtifactStoreOperationError,
                match="failed to create presigned artifact URL: presign boom",
            ) as exc_info:
                await artifact_store.publish_artifact(
                    task_id="task-2",
                    artifact_type="glb",
                    file_name="model.glb",
                    staging_path=staging_path,
                )

        assert exc_info.value.stage_name == "uploading"

    asyncio.run(scenario())
