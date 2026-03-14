from __future__ import annotations

import asyncio
import importlib
import json
import sys
import time
from pathlib import Path
from typing import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.api import server as server_module
from gen3d.api.server import create_app, run_real_mode_preflight
from gen3d.config import ServingConfig, ServingConfigurationError
from gen3d.model.base import GenerationResult, ModelProviderConfigurationError
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.storage.artifact_store import ArtifactStoreConfigurationError

WebhookSender = Callable[[str, dict], Awaitable[None]]
SAMPLE_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z/C/HwAF/gL+Q6UkWQAAAABJRU5ErkJggg=="
)


def make_client(
    tmp_path: Path,
    *,
    queue_delay_ms: int = 200,
    webhook_sender: WebhookSender | None = None,
    api_token: str | None = "test-token",
    rate_limit_concurrent: int = 5,
    rate_limit_per_hour: int = 100,
) -> TestClient:
    config = ServingConfig(
        api_token=api_token,
        database_path=tmp_path / "gen3d.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
        preprocess_delay_ms=40,
        queue_delay_ms=queue_delay_ms,
        mock_gpu_stage_delay_ms=60,
        mock_export_delay_ms=40,
        rate_limit_concurrent=rate_limit_concurrent,
        rate_limit_per_hour=rate_limit_per_hour,
    )
    return TestClient(create_app(config, webhook_sender=webhook_sender))


def make_real_mode_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed_callback_domains: tuple[str, ...] = (),
) -> TestClient:
    monkeypatch.setattr(
        server_module,
        "build_provider",
        lambda config: MockTrellis2Provider(stage_delay_ms=0),
    )
    config = ServingConfig(
        provider_mode="real",
        api_token="test-token",
        database_path=tmp_path / "gen3d-real.sqlite3",
        artifacts_dir=tmp_path / "artifacts-real",
        preprocess_delay_ms=0,
        queue_delay_ms=20,
        mock_gpu_stage_delay_ms=0,
        mock_export_delay_ms=0,
        allowed_callback_domains=allowed_callback_domains,
    )
    return TestClient(create_app(config))


def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def collect_task_snapshots(
    client: TestClient,
    task_id: str,
    *,
    terminal_status: str,
    timeout_seconds: float = 4.0,
) -> list[dict]:
    snapshots: list[dict] = []
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/v1/tasks/{task_id}", headers=auth_headers())
        assert response.status_code == 200
        payload = response.json()
        snapshots.append(payload)
        if payload["status"] == terminal_status:
            return snapshots
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {terminal_status} in time")


def wait_for_status(
    client: TestClient,
    task_id: str,
    status: str,
    *,
    timeout_seconds: float = 3.0,
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        response = client.get(f"/v1/tasks/{task_id}", headers=auth_headers())
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == status:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {status} in time")


def collect_sse_events(client: TestClient, task_id: str) -> list[dict]:
    events: list[dict] = []
    with client.stream("GET", f"/v1/tasks/{task_id}/events", headers=auth_headers()) as response:
        assert response.status_code == 200
        current_event: str | None = None
        for line in response.iter_lines():
            if not line:
                continue
            if line.startswith("event: "):
                current_event = line.removeprefix("event: ")
                continue
            if line.startswith("data: "):
                payload = json.loads(line.removeprefix("data: "))
                payload["event"] = current_event
                events.append(payload)
                if payload["status"] in {"succeeded", "failed", "cancelled"}:
                    break
    return events


def test_health_and_ready_endpoints(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health_response = client.get("/health")
        ready_response = client.get("/ready")

    with make_client(tmp_path / "mock-open", api_token=None) as open_client:
        open_create_response = open_client.post(
            "/v1/tasks",
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "service": "gen3d"}
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready", "service": "gen3d"}
    assert open_create_response.status_code == 201


def test_bearer_auth_is_required_for_task_routes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            json={"type": "image_to_3d", "image_url": "https://example.com/a.png"},
        )
        get_response = client.get("/v1/tasks/some-task-id")
        metrics_response = client.get("/metrics")
        metrics_authorized_response = client.get("/metrics", headers=auth_headers())

    assert create_response.status_code == 401
    assert get_response.status_code == 401
    assert metrics_response.status_code == 401
    assert metrics_authorized_response.status_code == 200


def test_sse_stream_replays_full_task_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        events = collect_sse_events(client, task_id)

    statuses = [event["status"] for event in events]
    assert statuses[0] == "submitted"
    assert "preprocessing" in statuses
    assert "gpu_queued" in statuses
    assert "gpu_ss" in statuses
    assert "gpu_shape" in statuses
    assert "gpu_material" in statuses
    assert "exporting" in statuses
    assert "uploading" in statuses
    assert statuses[-1] == "succeeded"
    assert events[-1]["event"] == "succeeded"
    assert events[-1]["metadata"]["artifacts"][0]["type"] == "glb"
    assert events[-1]["metadata"]["artifacts"][0]["backend"] == "local"


def test_create_task_runs_full_mock_pipeline_and_exposes_artifact_metadata(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        assert payload["status"] == "submitted"

        snapshots = collect_task_snapshots(
            client,
            payload["taskId"],
            terminal_status="succeeded",
        )
        artifacts_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts",
            headers=auth_headers(),
        )
        download_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts/model.glb",
            headers=auth_headers(),
        )

    statuses = [snapshot["status"] for snapshot in snapshots]
    assert "preprocessing" in statuses
    assert "gpu_queued" in statuses
    assert any(status in statuses for status in ("gpu_ss", "gpu_shape", "gpu_material"))
    assert "exporting" in statuses
    assert statuses[-1] == "succeeded"

    final_payload = snapshots[-1]
    assert final_payload["progress"] == 100
    assert final_payload["currentStage"] == "succeeded"
    assert final_payload["artifacts"]
    assert final_payload["artifacts"][0]["type"] == "glb"
    assert final_payload["artifacts"][0]["url"] == f"/v1/tasks/{payload['taskId']}/artifacts/model.glb"
    assert final_payload["artifacts"][0]["backend"] == "local"
    assert final_payload["artifacts"][0]["content_type"] == "model/gltf-binary"
    assert final_payload["artifacts"][0]["created_at"] is not None

    assert artifacts_response.status_code == 200
    assert artifacts_response.json()["artifacts"][0]["type"] == "glb"
    assert artifacts_response.json()["artifacts"][0] == final_payload["artifacts"][0]
    assert download_response.status_code == 200
    assert download_response.content == b"MOCK_GLB"


def test_gpu_queued_task_can_be_cancelled_and_repeat_cancel_is_rejected(tmp_path: Path) -> None:
    with make_client(
        tmp_path,
        queue_delay_ms=300,
        rate_limit_concurrent=1,
        rate_limit_per_hour=3,
    ) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        queued_payload = wait_for_status(client, task_id, "gpu_queued")
        assert queued_payload["status"] == "gpu_queued"

        concurrent_limit_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        cancel_response = client.post(f"/v1/tasks/{task_id}/cancel", headers=auth_headers())
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"

        second_cancel_response = client.post(
            f"/v1/tasks/{task_id}/cancel",
            headers=auth_headers(),
        )
        final_task_response = client.get(f"/v1/tasks/{task_id}", headers=auth_headers())
        artifacts_response = client.get(
            f"/v1/tasks/{task_id}/artifacts",
            headers=auth_headers(),
        )
        after_cancel_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert after_cancel_create_response.status_code == 201
        wait_for_status(client, after_cancel_create_response.json()["taskId"], "succeeded")
        hourly_limit_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )

    assert concurrent_limit_response.status_code == 429
    assert "concurrent tasks" in concurrent_limit_response.json()["detail"]
    assert second_cancel_response.status_code == 409
    assert "terminal status" in second_cancel_response.json()["detail"]
    assert final_task_response.status_code == 200
    assert final_task_response.json()["status"] == "cancelled"
    assert artifacts_response.status_code == 409
    assert hourly_limit_response.status_code == 429
    assert "per hour" in hourly_limit_response.json()["detail"]


def test_failed_task_returns_error_details_and_failed_stage(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {
                    "resolution": 1024,
                    "mock_failure_stage": "gpu_shape",
                },
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()

        snapshots = collect_task_snapshots(
            client,
            payload["taskId"],
            terminal_status="failed",
        )
        artifacts_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts",
            headers=auth_headers(),
        )

    statuses = [snapshot["status"] for snapshot in snapshots]
    assert "preprocessing" in statuses
    assert "gpu_queued" in statuses
    assert "gpu_ss" in statuses
    assert statuses[-1] == "failed"

    final_payload = snapshots[-1]
    assert final_payload["currentStage"] == "gpu_shape"
    assert final_payload["error"] == {
        "message": "mock failure injected at gpu_shape",
        "failed_stage": "gpu_shape",
    }
    assert final_payload["artifacts"] == []
    assert artifacts_response.status_code == 409


def test_uploading_failure_returns_error_details_and_failed_stage(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {
                    "resolution": 1024,
                    "mock_failure_stage": "uploading",
                },
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()

        events = collect_sse_events(client, payload["taskId"])
        final_task_response = client.get(
            f"/v1/tasks/{payload['taskId']}",
            headers=auth_headers(),
        )

    statuses = [event["status"] for event in events]
    assert "exporting" in statuses
    assert "uploading" in statuses
    assert statuses[-1] == "failed"
    assert events[-1]["metadata"]["stage"] == "uploading"

    assert final_task_response.status_code == 200
    assert final_task_response.json()["error"] == {
        "message": "mock failure injected at uploading",
        "failed_stage": "uploading",
    }


def test_success_and_failure_terminal_states_trigger_webhooks(tmp_path: Path) -> None:
    webhook_calls: list[tuple[str, dict]] = []

    async def webhook_sender(callback_url: str, payload: dict) -> None:
        webhook_calls.append((callback_url, payload))

    with make_client(tmp_path, webhook_sender=webhook_sender) as client:
        success_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "callback_url": "https://callback.test/success",
                "options": {"resolution": 1024},
            },
        )
        failed_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "callback_url": "https://callback.test/failure",
                "options": {
                    "resolution": 1024,
                    "mock_failure_stage": "exporting",
                },
            },
        )

        success_task_id = success_response.json()["taskId"]
        failed_task_id = failed_response.json()["taskId"]

        wait_for_status(client, success_task_id, "succeeded")
        wait_for_status(client, failed_task_id, "failed")

    assert len(webhook_calls) == 2
    payload_by_url = {url: payload for url, payload in webhook_calls}

    assert payload_by_url["https://callback.test/success"]["status"] == "succeeded"
    assert payload_by_url["https://callback.test/success"]["artifacts"][0]["type"] == "glb"
    assert payload_by_url["https://callback.test/success"]["artifacts"][0]["backend"] == "local"
    assert payload_by_url["https://callback.test/success"]["artifacts"][0]["url"].startswith(
        "/v1/tasks/"
    )
    assert payload_by_url["https://callback.test/success"]["error"] is None

    assert payload_by_url["https://callback.test/failure"]["status"] == "failed"
    assert payload_by_url["https://callback.test/failure"]["error"] == {
        "message": "mock failure injected at exporting",
        "failed_stage": "exporting",
    }


def test_invalid_image_input_fails_during_preprocessing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": "data:text/plain;base64,Zm9v",
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()

        snapshots = collect_task_snapshots(
            client,
            payload["taskId"],
            terminal_status="failed",
        )

    final_payload = snapshots[-1]
    assert final_payload["currentStage"] == "preprocessing"
    assert "decode input image" in final_payload["error"]["message"]

    with make_real_mode_client(
        tmp_path,
        monkeypatch,
        allowed_callback_domains=("callback.test",),
    ) as real_client:
        file_url_response = real_client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": "file:///tmp/input.png",
                "options": {"resolution": 1024},
            },
        )
        invalid_callback_response = real_client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": "http://127.0.0.1:9/input.png",
                "callback_url": "ftp://callback.test/task",
                "options": {"resolution": 1024},
            },
        )
        disallowed_callback_response = real_client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": "http://127.0.0.1:9/input.png",
                "callback_url": "https://evil.test/task",
                "options": {"resolution": 1024},
            },
        )
        allowed_callback_response = real_client.post(
            "/v1/tasks",
            headers=auth_headers(),
            json={
                "type": "image_to_3d",
                "image_url": "http://127.0.0.1:9/input.png",
                "callback_url": "https://callback.test/task",
                "options": {"resolution": 1024},
            },
        )

    assert file_url_response.status_code == 422
    assert "image_url must use http:// or https://" in file_url_response.json()["detail"]
    assert invalid_callback_response.status_code == 422
    assert "callback_url must use http:// or https://" in invalid_callback_response.json()["detail"]
    assert disallowed_callback_response.status_code == 422
    assert "ALLOWED_CALLBACK_DOMAINS" in disallowed_callback_response.json()["detail"]
    assert allowed_callback_response.status_code == 201


def test_real_mode_fails_fast_when_model_path_is_missing(tmp_path: Path) -> None:
    missing_token_config = ServingConfig(
        provider_mode="real",
        model_provider="trellis2",
        model_path=str(tmp_path / "missing-model"),
        database_path=tmp_path / "gen3d-no-token.sqlite3",
        artifacts_dir=tmp_path / "artifacts-no-token",
    )

    with pytest.raises(
        ServingConfigurationError,
        match="API_TOKEN is required when PROVIDER_MODE != mock",
    ):
        create_app(missing_token_config)

    config = ServingConfig(
        provider_mode="real",
        api_token="test-token",
        model_provider="trellis2",
        model_path=str(tmp_path / "missing-model"),
        database_path=tmp_path / "gen3d.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
    )

    with pytest.raises(ModelProviderConfigurationError, match="model path does not exist"):
        create_app(config)


def test_trellis2_provider_accepts_huggingface_repo_id_model_path() -> None:
    source_type, model_reference = Trellis2Provider._resolve_model_reference(
        "microsoft/TRELLIS.2-4B"
    )

    assert source_type == "huggingface"
    assert model_reference == "microsoft/TRELLIS.2-4B"


def test_trellis2_provider_run_single_uses_official_pipeline_kwargs() -> None:
    observed: dict[str, object] = {}

    class FakePipeline:
        def run(self, image, **kwargs):
            observed["image"] = image
            observed["kwargs"] = kwargs
            return ["mesh"]

    provider = Trellis2Provider(
        pipeline=FakePipeline(),
        model_path="microsoft/TRELLIS.2-4B",
    )

    result = provider._run_single(
        image="image-object",
        options={
            "resolution": 512,
            "ss_steps": 4,
            "shape_steps": 8,
            "material_steps": 4,
            "ss_guidance_scale": 6.5,
            "shape_guidance_scale": 7.5,
            "material_guidance_scale": 3.0,
        },
    )

    assert result == "mesh"
    assert observed["image"] == "image-object"
    assert observed["kwargs"] == {
        "pipeline_type": "512",
        "sparse_structure_sampler_params": {
            "steps": 4,
            "guidance_strength": 6.5,
        },
        "shape_slat_sampler_params": {
            "steps": 8,
            "guidance_strength": 7.5,
        },
        "tex_slat_sampler_params": {
            "steps": 4,
            "guidance_strength": 3.0,
        },
        "max_num_tokens": 49_152,
    }


def test_trellis2_provider_export_glb_uses_mesh_with_voxel_fields(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed: dict[str, object] = {}

    class FakeGlb:
        def export(self, output_path: str, extension_webp: bool = False) -> None:
            observed["export_path"] = output_path
            observed["extension_webp"] = extension_webp

    class FakePostprocess:
        @staticmethod
        def to_glb(**kwargs):
            observed["to_glb_kwargs"] = kwargs
            return FakeGlb()

    class FakeOVoxel:
        postprocess = FakePostprocess()

    original_import_module = importlib.import_module

    def fake_import_module(name: str, package: str | None = None):
        if name == "o_voxel":
            return FakeOVoxel()
        return original_import_module(name, package)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)

    class FakeMesh:
        vertices = "vertices"
        faces = "faces"
        attrs = "attrs"
        coords = "coords"
        layout = "layout"
        voxel_size = 0.01

    provider = Trellis2Provider(
        pipeline=object(),
        model_path="microsoft/TRELLIS.2-4B",
    )

    provider.export_glb(
        GenerationResult(mesh=FakeMesh()),
        tmp_path / "model.glb",
        {
            "decimation_target": 200_000,
            "texture_size": 1024,
        },
    )

    assert observed["to_glb_kwargs"] == {
        "vertices": "vertices",
        "faces": "faces",
        "attr_volume": "attrs",
        "coords": "coords",
        "attr_layout": "layout",
        "voxel_size": 0.01,
        "aabb": [[-0.5, -0.5, -0.5], [0.5, 0.5, 0.5]],
        "decimation_target": 200_000,
        "texture_size": 1024,
        "remesh": True,
        "remesh_band": 1,
        "remesh_project": 0,
        "verbose": False,
    }
    assert observed["export_path"] == str(tmp_path / "model.glb")
    assert observed["extension_webp"] is True


def test_real_mode_preflight_requires_provider_mode_real(tmp_path: Path) -> None:
    config = ServingConfig(
        provider_mode="mock",
        model_provider="trellis2",
        model_path=str(tmp_path / "model"),
        database_path=tmp_path / "gen3d.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
    )

    with pytest.raises(
        ModelProviderConfigurationError,
        match="--check-real-env requires PROVIDER_MODE=real",
    ):
        asyncio.run(run_real_mode_preflight(config))


def test_real_mode_preflight_reports_runtime_and_artifact_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_dir = tmp_path / "trellis2"
    model_dir.mkdir()
    observed: dict[str, object] = {}

    async def fake_initialize(self) -> None:
        observed["artifact_mode"] = self.mode

    def fake_inspect_runtime(cls, model_path: str, *, load_pipeline: bool = True) -> dict:
        observed["model_path"] = model_path
        observed["load_pipeline"] = load_pipeline
        return {
            "provider": "trellis2",
            "model_path": model_path,
            "torch_version": "2.6.0",
            "cuda_available": True,
            "cuda_device_count": 1,
            "pipeline_class": "trellis2.pipelines.Trellis2ImageTo3DPipeline",
            "pipeline_loaded": load_pipeline,
        }

    monkeypatch.setattr(server_module.ArtifactStore, "initialize", fake_initialize)
    monkeypatch.setattr(
        server_module.Trellis2Provider,
        "inspect_runtime",
        classmethod(fake_inspect_runtime),
    )

    config = ServingConfig(
        provider_mode="real",
        api_token=None,
        model_provider="trellis2",
        model_path=str(model_dir),
        artifact_store_mode="local",
        database_path=tmp_path / "gen3d.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
    )

    report = asyncio.run(run_real_mode_preflight(config))

    assert observed == {
        "artifact_mode": "local",
        "model_path": str(model_dir),
        "load_pipeline": True,
    }
    assert report["provider_mode"] == "real"
    assert report["artifact_store"] == {
        "mode": "local",
        "artifacts_dir": str(tmp_path / "artifacts"),
    }
    assert report["provider"]["pipeline_loaded"] is True


def test_minio_artifact_store_requires_complete_config(tmp_path: Path) -> None:
    config = ServingConfig(
        artifact_store_mode="minio",
        database_path=tmp_path / "gen3d.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
    )

    with pytest.raises(
        ArtifactStoreConfigurationError,
        match="OBJECT_STORE_ENDPOINT, OBJECT_STORE_BUCKET, OBJECT_STORE_ACCESS_KEY, OBJECT_STORE_SECRET_KEY",
    ):
        create_app(config)
