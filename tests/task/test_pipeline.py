# ruff: noqa: E402

from __future__ import annotations

import asyncio
import base64
import io
import time
from datetime import timedelta
from pathlib import Path

import pytest

from cubie.artifact.store import (
    ArtifactStore,
    ArtifactStoreOperationError,
    ObjectStorageStreamResult,
)
from cubie.model.gpu import build_gpu_workers
from cubie.model.gpu_scheduler import GPUSlotScheduler
from cubie.model.providers.trellis2.provider import MockTrellis2Provider
from cubie.model.registry import ModelRegistry, ModelRuntime
from cubie.stage.export.preview_renderer_service import PreviewRendererServiceProtocol
from cubie.stage.export.stage import ExportStage
from cubie.stage.gpu.stage import GPUStage
from cubie.stage.preprocess.stage import PreprocessStage
from cubie.task.engine import AsyncGen3DEngine
from cubie.task.pipeline import PipelineCoordinator
from cubie.task.sequence import (
    DEFAULT_PROGRESS_BY_STATUS,
    RequestSequence,
    TaskStatus,
    TaskType,
    utcnow,
)
from cubie.task.store import TaskStore

SAMPLE_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z/C/HwAF/gL+Q6UkWQAAAABJRU5ErkJggg=="
)
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"


class DisabledPreviewRendererService:
    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    async def render_preview_png(
        self,
        *,
        model_path: Path | None = None,
        model_bytes: bytes | None = None,
    ) -> bytes:
        _ = model_path
        _ = model_bytes
        raise RuntimeError("preview renderer disabled in unit tests")


def make_image_bytes(image_format: str) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (2, 2), (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


class FakeObjectStorageClient:
    def __init__(self, *, fail_on_presign: bool = False) -> None:
        self.fail_on_presign = fail_on_presign
        self.validated_bucket: str | None = None
        self.uploads: list[dict[str, object]] = []
        self.objects: dict[tuple[str, str], dict[str, object]] = {}
        self.deleted_keys: list[tuple[str, str]] = []

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
        self.objects[(bucket, key)] = {
            "body": source_path.read_bytes(),
            "content_type": content_type,
        }

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

    def list_object_keys(
        self,
        *,
        bucket: str,
        prefix: str,
    ) -> list[str]:
        return [
            key
            for (stored_bucket, key), _ in self.objects.items()
            if stored_bucket == bucket and key.startswith(prefix)
        ]

    def get_object_stream(
        self,
        *,
        bucket: str,
        key: str,
    ) -> ObjectStorageStreamResult:
        stored = self.objects[(bucket, key)]

        class MemoryStream:
            def __init__(self, payload: bytes) -> None:
                self._payload = payload
                self._offset = 0

            def read(self, amount: int = -1) -> bytes:
                if self._offset >= len(self._payload):
                    return b""
                if amount is None or amount < 0:
                    amount = len(self._payload) - self._offset
                chunk = self._payload[self._offset:self._offset + amount]
                self._offset += len(chunk)
                return chunk

            def close(self) -> None:
                return

        payload = stored["body"]
        assert isinstance(payload, bytes)
        content_type = stored.get("content_type")
        return ObjectStorageStreamResult(
            body=MemoryStream(payload),
            content_type=content_type if isinstance(content_type, str) else None,
            content_length=len(payload),
            etag='"fake-etag"',
        )

    def delete_objects(
        self,
        *,
        bucket: str,
        keys: list[str],
    ) -> None:
        for key in keys:
            self.deleted_keys.append((bucket, key))
            self.objects.pop((bucket, key), None)


def build_engine(
    tmp_path: Path,
    *,
    queue_delay_ms: int = 10,
    task_timeout_seconds: int = 3600,
    gpu_device_ids: tuple[str, ...] = ("0",),
    queue_max_size: int = 20,
    mock_gpu_stage_delay_ms: int = 20,
    uploads_dir: Path | None = None,
    preview_renderer_service: PreviewRendererServiceProtocol | None = None,
) -> tuple[TaskStore, ArtifactStore, AsyncGen3DEngine]:
    task_store = TaskStore(tmp_path / "pipeline.sqlite3")
    artifact_store = ArtifactStore(tmp_path / "artifacts")
    uploads_dir = uploads_dir or (tmp_path / "uploads")
    preview_renderer_service = preview_renderer_service or DisabledPreviewRendererService()

    def build_runtime(model_name: str) -> ModelRuntime:
        provider = MockTrellis2Provider(stage_delay_ms=mock_gpu_stage_delay_ms)
        workers = build_gpu_workers(
            provider=provider,
            provider_mode="mock",
            provider_name="trellis2",
            model_path="microsoft/TRELLIS.2-4B",
            device_ids=gpu_device_ids,
        )
        return ModelRuntime(
            model_name=model_name,
            provider=provider,
            workers=workers,
            scheduler=GPUSlotScheduler(workers),
        )

    model_registry = ModelRegistry(build_runtime)
    gpu_stage = GPUStage(
        delay_ms=queue_delay_ms,
        model_registry=model_registry,
        task_store=task_store,
    )
    pipeline = PipelineCoordinator(
        task_store=task_store,
        stages=[
            PreprocessStage(
                delay_ms=10,
                uploads_dir=uploads_dir,
                artifact_store=artifact_store,
                task_store=task_store,
            ),
            gpu_stage,
            ExportStage(
                model_registry=model_registry,
                artifact_store=artifact_store,
                preview_renderer_service=preview_renderer_service,
                task_store=task_store,
                delay_ms=10,
            ),
        ],
        task_timeout_seconds=task_timeout_seconds,
        queue_max_size=queue_max_size,
        worker_count=len(gpu_device_ids),
    )
    engine = AsyncGen3DEngine(
        task_store=task_store,
        pipeline=pipeline,
        model_registry=model_registry,
        artifact_store=artifact_store,
        parallel_slots=len(gpu_device_ids),
        queue_max_size=queue_max_size,
        uploads_dir=uploads_dir,
    )
    return task_store, artifact_store, engine


def test_preprocess_stage_reads_uploaded_file_from_upload_scheme(tmp_path: Path) -> None:
    async def scenario() -> None:
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        upload_id = "sampleuploadid"
        uploads_dir.joinpath(f"{upload_id}.png").write_bytes(
            base64.b64decode(SAMPLE_IMAGE_DATA_URL.partition(",")[2])
        )

        stage = PreprocessStage(delay_ms=0, uploads_dir=uploads_dir)
        sequence = RequestSequence.new_task(
            input_url=f"upload://{upload_id}",
            options={"resolution": 1024},
            task_type=TaskType.IMAGE_TO_3D,
        )

        result = await stage.run(sequence)

        assert result.prepared_input is not None
        assert result.prepared_input["image_url"] == f"upload://{upload_id}"
        assert result.prepared_input["width"] == 1
        assert result.prepared_input["height"] == 1

    asyncio.run(scenario())


async def wait_for_engine_status(
    engine: AsyncGen3DEngine,
    task_id: str,
    status: TaskStatus,
    *,
    timeout_seconds: float = 3.0,
):
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        current = await engine.get_task(task_id)
        if current is not None and current.status == status:
            return current
        await asyncio.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {status.value} in time")


async def seed_task(
    task_store: TaskStore,
    *,
    task_id: str,
    status: TaskStatus,
    current_stage: str | None = None,
    created_at_offset_seconds: int = 0,
    callback_url: str | None = None,
    idempotency_key: str | None = None,
) -> RequestSequence:
    created_at = utcnow() - timedelta(seconds=max(created_at_offset_seconds, 0))
    sequence = RequestSequence(
        task_id=task_id,
        task_type=TaskType.IMAGE_TO_3D,
        model="trellis",
        input_url=SAMPLE_IMAGE_DATA_URL,
        options={"resolution": 1024},
        callback_url=callback_url,
        idempotency_key=idempotency_key,
        status=status,
        progress=DEFAULT_PROGRESS_BY_STATUS[status],
        current_stage=current_stage or status.value,
        created_at=created_at,
        queued_at=created_at,
        started_at=None if status == TaskStatus.QUEUED else created_at,
        updated_at=created_at,
    )
    await task_store.create_task(sequence)
    return sequence


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
                "queued",
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


def test_pipeline_persists_input_and_preview_artifacts(
    tmp_path: Path,
) -> None:
    preview_bytes = make_image_bytes("PNG")
    input_bytes = make_image_bytes("JPEG")

    class StaticPreviewRendererService:
        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

        async def render_preview_png(
            self,
            *,
            model_path: Path | None = None,
            model_bytes: bytes | None = None,
        ) -> bytes:
            assert model_path is not None
            assert model_path.name == "model.glb"
            assert model_bytes is None
            return preview_bytes

    async def scenario() -> None:
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        uploads_dir.joinpath("preview-source.jpg").write_bytes(input_bytes)

        task_store, artifact_store, engine = build_engine(
            tmp_path,
            uploads_dir=uploads_dir,
            preview_renderer_service=StaticPreviewRendererService(),
        )
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            sequence, created = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url="upload://preview-source",
                options={"resolution": 1024},
            )
            assert created is True

            current = await wait_for_engine_status(engine, sequence.task_id, TaskStatus.SUCCEEDED)
            artifact_names = [Path(artifact["url"]).name for artifact in current.artifacts]

            assert artifact_names == ["model.glb", "preview.png", "input.png"]

            preview_path = await artifact_store.get_local_artifact_path(sequence.task_id, "preview.png")
            input_path = await artifact_store.get_local_artifact_path(sequence.task_id, "input.png")

            assert preview_path is not None
            assert preview_path.read_bytes().startswith(PNG_MAGIC)
            assert input_path is not None
            assert input_path.read_bytes() == input_bytes
            assert input_path.read_bytes().startswith(JPEG_MAGIC)
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_preview_render_failure_does_not_fail_task(
    tmp_path: Path,
) -> None:
    class FailingPreviewRendererService:
        async def start(self) -> None:
            return

        async def stop(self) -> None:
            return

        async def render_preview_png(
            self,
            *,
            model_path: Path | None = None,
            model_bytes: bytes | None = None,
        ) -> bytes:
            _ = model_path
            _ = model_bytes
            raise RuntimeError("pyrender boom")

    async def scenario() -> None:
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir(parents=True, exist_ok=True)
        uploads_dir.joinpath("preview-failure.png").write_bytes(make_image_bytes("PNG"))

        task_store, artifact_store, engine = build_engine(
            tmp_path,
            uploads_dir=uploads_dir,
            preview_renderer_service=FailingPreviewRendererService(),
        )
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            sequence, created = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url="upload://preview-failure",
                options={"resolution": 1024},
            )
            assert created is True

            current = await wait_for_engine_status(engine, sequence.task_id, TaskStatus.SUCCEEDED)
            artifact_names = [Path(artifact["url"]).name for artifact in current.artifacts]

            assert artifact_names == ["model.glb", "input.png"]
            assert current.failed_stage is None
            assert await artifact_store.get_local_artifact_path(sequence.task_id, "preview.png") is None
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


def test_pipeline_recovery_requeues_early_tasks_and_fails_interrupted_tasks(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        seed_store = TaskStore(tmp_path / "pipeline.sqlite3")
        await seed_store.initialize()
        try:
            await seed_task(
                seed_store,
                task_id="recover-submitted",
                status=TaskStatus.QUEUED,
            )
            await seed_task(
                seed_store,
                task_id="recover-preprocessing",
                status=TaskStatus.PREPROCESSING,
            )
            await seed_task(
                seed_store,
                task_id="recover-gpu",
                status=TaskStatus.GPU_QUEUED,
            )
        finally:
            await seed_store.close()

        task_store, artifact_store, engine = build_engine(tmp_path)
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            submitted = await wait_for_engine_status(
                engine,
                "recover-submitted",
                TaskStatus.SUCCEEDED,
            )
            preprocessing = await wait_for_engine_status(
                engine,
                "recover-preprocessing",
                TaskStatus.SUCCEEDED,
            )
            interrupted = await wait_for_engine_status(
                engine,
                "recover-gpu",
                TaskStatus.FAILED,
            )

            assert submitted.artifacts
            assert preprocessing.artifacts
            assert interrupted.error_message == "服务重启，任务中断"
            assert interrupted.failed_stage == "gpu_queued"

            events = await task_store.list_task_events("recover-gpu")
            assert events[-1]["event"] == "failed"
            assert events[-1]["metadata"]["recovery_action"] == "interrupted"
            assert events[-1]["metadata"]["message"] == "服务重启，任务中断"
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_pipeline_recovery_fails_timed_out_tasks(tmp_path: Path) -> None:
    async def scenario() -> None:
        seed_store = TaskStore(tmp_path / "pipeline.sqlite3")
        await seed_store.initialize()
        try:
            await seed_task(
                seed_store,
                task_id="timed-out-task",
                status=TaskStatus.PREPROCESSING,
                created_at_offset_seconds=10,
            )
        finally:
            await seed_store.close()

        task_store, artifact_store, engine = build_engine(
            tmp_path,
            task_timeout_seconds=1,
        )
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            timed_out = await wait_for_engine_status(
                engine,
                "timed-out-task",
                TaskStatus.FAILED,
            )

            assert timed_out.error_message == (
                "task exceeded TASK_TIMEOUT_SECONDS before service recovery"
            )
            assert timed_out.failed_stage == "preprocessing"

            events = await task_store.list_task_events("timed-out-task")
            assert events[-1]["event"] == "failed"
            assert events[-1]["metadata"]["recovery_action"] == "timeout"
            assert "TASK_TIMEOUT_SECONDS" in events[-1]["metadata"]["message"]
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_engine_idempotency_conflict_returns_existing_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        task_store, artifact_store, engine = build_engine(tmp_path, queue_delay_ms=200)
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        try:
            gate = asyncio.Event()
            arrivals = 0

            async def always_miss_idempotency_key(_: str) -> None:
                nonlocal arrivals
                arrivals += 1
                if arrivals == 2:
                    gate.set()
                await gate.wait()
                return None

            monkeypatch.setattr(
                task_store,
                "get_task_by_idempotency_key",
                always_miss_idempotency_key,
            )

            async def submit():
                return await engine.submit_task(
                    task_type=TaskType.IMAGE_TO_3D,
                    image_url=SAMPLE_IMAGE_DATA_URL,
                    options={"resolution": 1024},
                    idempotency_key="race-key",
                )

            results = await asyncio.gather(submit(), submit())
            sequences = [sequence for sequence, _ in results]
            created_flags = sorted(created for _, created in results)

            assert created_flags == [False, True]
            assert sequences[0].task_id == sequences[1].task_id
            assert await engine.get_task(sequences[0].task_id) is not None
        finally:
            await engine.stop()
            await task_store.close()

    asyncio.run(scenario())


def test_pipeline_multi_slot_dispatches_tasks_concurrently(tmp_path: Path) -> None:
    async def scenario() -> None:
        task_store, artifact_store, engine = build_engine(
            tmp_path,
            gpu_device_ids=("0", "1"),
            mock_gpu_stage_delay_ms=120,
        )
        await task_store.initialize()
        await artifact_store.initialize()
        await engine.start()
        started_at = time.perf_counter()
        try:
            first_sequence, _ = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
            )
            second_sequence, _ = await engine.submit_task(
                task_type=TaskType.IMAGE_TO_3D,
                image_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
            )

            first_result = await wait_for_engine_status(
                engine,
                first_sequence.task_id,
                TaskStatus.SUCCEEDED,
            )
            second_result = await wait_for_engine_status(
                engine,
                second_sequence.task_id,
                TaskStatus.SUCCEEDED,
            )
            elapsed_seconds = time.perf_counter() - started_at
            first_duration = (
                first_result.completed_at - first_result.started_at
            ).total_seconds()
            second_duration = (
                second_result.completed_at - second_result.started_at
            ).total_seconds()

            assert {first_result.assigned_worker_id, second_result.assigned_worker_id} == {
                "gpu-worker-0",
                "gpu-worker-1",
            }
            assert elapsed_seconds < (first_duration + second_duration) * 0.8
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
            object_store_bucket="artifacts",
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

        assert fake_client.validated_bucket == "artifacts"
        assert fake_client.uploads[0]["bucket"] == "artifacts"
        assert fake_client.uploads[0]["key"] == "artifacts/task-1/model.glb"
        assert fake_client.uploads[0]["content_type"] == "model/gltf-binary"
        assert fake_client.uploads[0]["body"] == b"GLB"
        assert artifact["backend"] == "minio"
        assert artifact["url"].startswith("http://minio.test/artifacts/artifacts/task-1/model.glb")
        assert artifact["content_type"] == "model/gltf-binary"
        assert artifact["expires_at"] is not None
        assert listed == [artifact]

    asyncio.run(scenario())


def test_minio_artifact_store_opens_streaming_download_without_staging_file(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        fake_client = FakeObjectStorageClient()
        artifact_store = ArtifactStore(
            tmp_path / "artifacts",
            mode="minio",
            object_store_client=fake_client,
            object_store_bucket="artifacts",
        )
        await artifact_store.initialize()

        async with artifact_store.create_staging_path("task-stream", "model.glb") as staging_path:
            staging_path.write_bytes(b"glTF")
            await artifact_store.publish_artifact(
                task_id="task-stream",
                artifact_type="glb",
                file_name="model.glb",
                staging_path=staging_path,
            )

        stream = await artifact_store.open_streaming_download("task-stream", "model.glb")

        assert stream is not None
        assert stream.content_type == "model/gltf-binary"
        assert stream.content_length == 4
        assert stream.etag == '"fake-etag"'
        assert stream.body.read(2) == b"gl"
        assert stream.body.read(2) == b"TF"
        assert stream.body.read(2) == b""
        stream.body.close()

    asyncio.run(scenario())


def test_minio_artifact_store_surfaces_presign_failures_as_uploading_errors(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        artifact_store = ArtifactStore(
            tmp_path / "artifacts",
            mode="minio",
            object_store_client=FakeObjectStorageClient(fail_on_presign=True),
            object_store_bucket="artifacts",
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


def test_minio_artifact_store_delete_artifacts_removes_objects_and_manifest(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        fake_client = FakeObjectStorageClient()
        artifact_store = ArtifactStore(
            tmp_path / "artifacts",
            mode="minio",
            object_store_client=fake_client,
            object_store_bucket="artifacts",
        )
        await artifact_store.initialize()

        async with artifact_store.create_staging_path("task-3", "model.glb") as staging_path:
            staging_path.write_bytes(b"GLB")
            await artifact_store.publish_artifact(
                task_id="task-3",
                artifact_type="glb",
                file_name="model.glb",
                staging_path=staging_path,
            )

        manifest_path = (tmp_path / "artifacts" / "_manifests" / "task-3.json")
        assert manifest_path.exists()

        await artifact_store.delete_artifacts("task-3")

        assert fake_client.deleted_keys == [
            ("artifacts", "artifacts/task-3/model.glb")
        ]
        assert fake_client.objects == {}
        assert manifest_path.exists() is False

    asyncio.run(scenario())
