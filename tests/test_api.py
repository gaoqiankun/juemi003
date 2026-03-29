from __future__ import annotations

import asyncio
import importlib
import io
import json
import sqlite3
import sys
import threading
import time
import types
from datetime import timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.api import server as server_module
from gen3d.api.server import create_app, run_real_mode_preflight
from gen3d.config import ServingConfig
from gen3d.engine import async_engine as async_engine_module
from gen3d.engine.sequence import RequestSequence, TaskStatus, TaskType, utcnow
from gen3d.model.base import (
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
)
from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider, MockHunyuan3DProvider
from gen3d.model.step1x3d import provider as step1x3d_provider_module
from gen3d.model.step1x3d.provider import MockStep1X3DProvider, Step1X3DProvider
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.stages.export.preview_renderer_service import (
    PreviewRendererService,
    PreviewRendererServiceProtocol,
)
from gen3d.storage.artifact_store import (
    ArtifactStoreConfigurationError,
    ArtifactStoreOperationError,
    ObjectStorageStreamResult,
)
from gen3d.storage.model_store import ModelStore
from gen3d.storage.task_store import TaskStore

WebhookSender = Callable[[str, dict], Awaitable[None]]
SAMPLE_IMAGE_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADUlEQVR42mP8z/C/HwAF/gL+Q6UkWQAAAABJRU5ErkJggg=="
)


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


def create_test_app(
    config: ServingConfig,
    *,
    webhook_sender: WebhookSender | None = None,
    preview_renderer_service: PreviewRendererServiceProtocol | None = None,
):
    return create_app(
        config,
        webhook_sender=webhook_sender,
        preview_renderer_service=preview_renderer_service or DisabledPreviewRendererService(),
    )


def make_client(
    tmp_path: Path,
    *,
    queue_delay_ms: int = 200,
    webhook_sender: WebhookSender | None = None,
    admin_token: str | None = "admin-token",
    rate_limit_concurrent: int = 5,
    rate_limit_per_hour: int = 100,
    webhook_max_retries: int = 3,
    task_timeout_seconds: int = 3600,
    database_path: Path | None = None,
    artifacts_dir: Path | None = None,
    uploads_dir: Path | None = None,
    artifact_store_mode: str = "local",
    object_store_endpoint: str | None = None,
    object_store_external_endpoint: str | None = None,
    object_store_bucket: str | None = None,
    object_store_access_key: str | None = None,
    object_store_secret_key: str | None = None,
    gpu_device_ids: tuple[str, ...] = ("0",),
    queue_max_size: int = 20,
    preprocess_max_image_bytes: int = 10 * 1024 * 1024,
    preview_renderer_service: PreviewRendererServiceProtocol | None = None,
) -> TestClient:
    database_path = database_path or (tmp_path / "app.sqlite3")
    artifacts_dir = artifacts_dir or (tmp_path / "artifacts")
    uploads_dir = uploads_dir or (tmp_path / "uploads")
    config = ServingConfig(
        admin_token=admin_token,
        database_path=database_path,
        artifact_store_mode=artifact_store_mode,
        artifacts_dir=artifacts_dir,
        uploads_dir=uploads_dir,
        object_store_endpoint=object_store_endpoint,
        object_store_external_endpoint=object_store_external_endpoint,
        object_store_bucket=object_store_bucket,
        object_store_access_key=object_store_access_key,
        object_store_secret_key=object_store_secret_key,
        preprocess_delay_ms=40,
        preprocess_max_image_bytes=preprocess_max_image_bytes,
        queue_delay_ms=queue_delay_ms,
        gpu_device_ids=gpu_device_ids,
        queue_max_size=queue_max_size,
        mock_gpu_stage_delay_ms=60,
        mock_export_delay_ms=40,
        rate_limit_concurrent=rate_limit_concurrent,
        rate_limit_per_hour=rate_limit_per_hour,
        webhook_max_retries=webhook_max_retries,
        task_timeout_seconds=task_timeout_seconds,
    )
    return TestClient(
        create_test_app(
            config,
            webhook_sender=webhook_sender,
            preview_renderer_service=preview_renderer_service,
        )
    )


def make_real_mode_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed_callback_domains: tuple[str, ...] = (),
    admin_token: str | None = "admin-token",
    uploads_dir: Path | None = None,
    preview_renderer_service: PreviewRendererServiceProtocol | None = None,
) -> TestClient:
    monkeypatch.setattr(
        server_module,
        "build_provider",
        lambda provider_name, provider_mode, model_path, mock_delay_ms=60: MockTrellis2Provider(stage_delay_ms=0),
    )
    config = ServingConfig(
        provider_mode="real",
        admin_token=admin_token,
        database_path=tmp_path / "app-real.sqlite3",
        artifacts_dir=tmp_path / "artifacts-real",
        uploads_dir=uploads_dir or (tmp_path / "uploads-real"),
        preprocess_delay_ms=0,
        queue_delay_ms=20,
        mock_gpu_stage_delay_ms=0,
        mock_export_delay_ms=0,
        allowed_callback_domains=allowed_callback_domains,
    )
    return TestClient(
        create_test_app(
            config,
            preview_renderer_service=preview_renderer_service,
        )
    )


def auth_headers(token: str = "test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_privileged_api_key(
    client: TestClient,
    *,
    scope: str,
    label: str,
    admin_token: str = "admin-token",
    allowed_ips: list[str] | None = None,
) -> dict:
    payload: dict[str, object] = {
        "scope": scope,
        "label": label,
    }
    if allowed_ips is not None:
        payload["allowed_ips"] = allowed_ips
    response = client.post(
        "/api/admin/privileged-keys",
        headers=admin_headers(admin_token),
        json=payload,
    )
    assert response.status_code == 201
    return response.json()


def _cached_privileged_headers(
    client: TestClient,
    *,
    scope: str,
    label: str,
    admin_token: str = "admin-token",
) -> dict[str, str]:
    cache_name = f"_cached_{scope}_token"
    token = getattr(client, cache_name, None)
    if token is None:
        token = create_privileged_api_key(
            client,
            scope=scope,
            label=label,
            admin_token=admin_token,
        )["token"]
        setattr(client, cache_name, token)
    return auth_headers(token)


def metrics_headers(
    client: TestClient,
    *,
    admin_token: str = "admin-token",
) -> dict[str, str]:
    return _cached_privileged_headers(
        client,
        scope="metrics",
        label="Default Metrics",
        admin_token=admin_token,
    )


def task_auth_headers(
    client: TestClient,
    *,
    admin_token: str = "admin-token",
) -> dict[str, str]:
    token = getattr(client, "_default_task_token", None)
    if token is None:
        token = create_managed_api_key(
            client,
            label="Default Task Key",
            admin_token=admin_token,
        )["token"]
        setattr(client, "_default_task_token", token)
    return auth_headers(token)


def create_managed_api_key(
    client: TestClient,
    *,
    label: str = "QA Key",
    admin_token: str = "admin-token",
) -> dict:
    response = client.post(
        "/api/admin/keys",
        headers=admin_headers(admin_token),
        json={"label": label},
    )
    assert response.status_code == 201
    return response.json()


def make_image_bytes(image_format: str) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (2, 2), (255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format=image_format)
    return buffer.getvalue()


@pytest.fixture
def reset_preview_render_state():
    server_module._preview_rendering.clear()
    server_module._preview_render_tasks.clear()
    yield
    server_module._preview_rendering.clear()
    server_module._preview_render_tasks.clear()


def upload_input_url(
    client: TestClient,
    *,
    token: str | None = None,
    image_format: str = "PNG",
) -> str:
    content_type = {
        "PNG": "image/png",
        "JPEG": "image/jpeg",
        "WEBP": "image/webp",
        "GIF": "image/gif",
    }[image_format]
    suffix = image_format.lower() if image_format != "JPEG" else "jpg"
    headers = auth_headers(token) if token is not None else task_auth_headers(client)
    response = client.post(
        "/v1/upload",
        headers=headers,
        files={
            "file": (
                f"pixel.{suffix}",
                make_image_bytes(image_format),
                content_type,
            )
        },
    )
    assert response.status_code == 201
    return response.json()["url"]


def collect_task_snapshots(
    client: TestClient,
    task_id: str,
    *,
    terminal_status: str,
    token: str | None = None,
    timeout_seconds: float = 15.0,
) -> list[dict]:
    snapshots: list[dict] = []
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        headers = auth_headers(token) if token is not None else task_auth_headers(client)
        response = client.get(f"/v1/tasks/{task_id}", headers=headers)
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
    token: str | None = None,
    timeout_seconds: float = 15.0,
) -> dict:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        headers = auth_headers(token) if token is not None else task_auth_headers(client)
        response = client.get(f"/v1/tasks/{task_id}", headers=headers)
        assert response.status_code == 200
        payload = response.json()
        if payload["status"] == status:
            return payload
        time.sleep(0.01)
    raise AssertionError(f"task {task_id} did not reach {status} in time")


def collect_sse_events(
    client: TestClient,
    task_id: str,
    *,
    token: str | None = None,
) -> list[dict]:
    events: list[dict] = []
    headers = auth_headers(token) if token is not None else task_auth_headers(client)
    with client.stream(
        "GET",
        f"/v1/tasks/{task_id}/events",
        headers=headers,
    ) as response:
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


def fetch_metrics_payload(
    client: TestClient,
    *,
    token: str | None = None,
    admin_token: str = "admin-token",
) -> str:
    headers = auth_headers(token) if token is not None else metrics_headers(
        client,
        admin_token=admin_token,
    )
    response = client.get("/metrics", headers=headers)
    assert response.status_code == 200
    return response.text


def task_page_items(response: Any) -> list[dict]:
    payload = response.json()
    return payload["items"]


def metric_sample_value(
    metrics_payload: str,
    sample_name: str,
    labels: dict[str, str] | None = None,
) -> float:
    expected_labels = labels or {}
    for family in text_string_to_metric_families(metrics_payload):
        for sample in family.samples:
            if sample.name == sample_name and sample.labels == expected_labels:
                return float(sample.value)
    raise AssertionError(f"metric sample {sample_name}{expected_labels} not found")


def wait_for_metric_sample(
    client: TestClient,
    sample_name: str,
    *,
    labels: dict[str, str],
    minimum_value: float,
    timeout_seconds: float = 2.0,
) -> float:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        metrics_payload = fetch_metrics_payload(client)
        value = metric_sample_value(metrics_payload, sample_name, labels)
        if value >= minimum_value:
            return value
        time.sleep(0.01)
    raise AssertionError(
        f"metric sample {sample_name}{labels} did not reach {minimum_value} in time"
    )


def wait_for_condition(
    predicate: Callable[[], bool],
    *,
    timeout_seconds: float = 2.0,
) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied in time")


def read_task_events(database_path: Path, task_id: str) -> list[dict]:
    async def scenario() -> list[dict]:
        task_store = TaskStore(database_path)
        await task_store.initialize()
        try:
            return await task_store.list_task_events(task_id)
        finally:
            await task_store.close()

    return asyncio.run(scenario())


def seed_tasks(database_path: Path, sequences: list[RequestSequence]) -> None:
    async def scenario() -> None:
        task_store = TaskStore(database_path)
        await task_store.initialize()
        try:
            for sequence in sequences:
                await task_store.create_task(sequence)
        finally:
            await task_store.close()

    asyncio.run(scenario())


def make_succeeded_sequence(task_id: str) -> RequestSequence:
    timestamp = utcnow()
    return RequestSequence(
        task_id=task_id,
        task_type=TaskType.IMAGE_TO_3D,
        model="trellis",
        input_url=SAMPLE_IMAGE_DATA_URL,
        options={"resolution": 1024},
        status=TaskStatus.SUCCEEDED,
        progress=100,
        current_stage=TaskStatus.SUCCEEDED.value,
        created_at=timestamp,
        queued_at=timestamp,
        started_at=timestamp,
        completed_at=timestamp,
        updated_at=timestamp,
    )


def test_health_and_ready_endpoints(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        health_response = client.get("/health")
        wait_for_condition(
            lambda: client.get("/readiness").status_code == 200,
            timeout_seconds=2.0,
        )
        readiness_response = client.get("/readiness")
        ready_alias_response = client.get("/ready")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "service": "cubie3d"}
    assert readiness_response.status_code == 200
    assert readiness_response.json() == {
        "status": "ready",
        "service": "cubie3d",
    }
    assert ready_alias_response.status_code == 200
    assert ready_alias_response.json() == {
        "status": "ready",
        "service": "cubie3d",
    }


def test_dev_proxy_is_disabled_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    class UnexpectedProxyClient:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("dev proxy client should not be created when unset")

    monkeypatch.setattr(server_module.httpx, "AsyncClient", UnexpectedProxyClient)

    config = ServingConfig(
        database_path=tmp_path / "app.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
        uploads_dir=tmp_path / "uploads",
    )
    with TestClient(create_test_app(config)) as client:
        health_response = client.get("/health")
        root_response = client.get("/")

    assert health_response.status_code == 200
    assert health_response.json() == {"status": "ok", "service": "cubie3d"}
    expected_root_status = 200 if server_module.SPA_INDEX_PATH.is_file() else 204
    assert root_response.status_code == expected_root_status


def test_dev_proxy_forwards_non_static_requests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    forwarded_requests: list[dict[str, Any]] = []
    proxy_clients: list[Any] = []

    class FakeProxyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.closed = False
            proxy_clients.append(self)

        def build_request(self, method: str, url: str, headers=None, content=None) -> httpx.Request:
            return httpx.Request(method, url, headers=headers, content=content)

        async def send(self, request: httpx.Request, stream: bool = False) -> httpx.Response:
            forwarded_requests.append(
                {
                    "method": request.method,
                    "url": str(request.url),
                    "headers": {key.lower(): value for key, value in request.headers.items()},
                    "body": request.content,
                    "stream": stream,
                }
            )
            payload = {
                "proxied": True,
                "path": request.url.path,
                "query": dict(request.url.params),
            }
            return httpx.Response(
                status_code=200,
                headers={"content-type": "application/json", "x-dev-proxy": "1"},
                stream=httpx.ByteStream(json.dumps(payload).encode("utf-8")),
                request=request,
            )

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeProxyClient)

    config = ServingConfig(
        database_path=tmp_path / "app.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
        uploads_dir=tmp_path / "uploads",
        dev_proxy_target="https://cubie3d.example.com",
    )
    with TestClient(create_test_app(config)) as client:
        ready_response = client.get(
            "/ready?check=1",
            headers={"Authorization": "Bearer upstream-token", "X-Debug": "true"},
        )
        static_response = client.get("/static/index.html")
        tasks_response = client.post(
            "/v1/tasks?debug=1",
            headers={
                "Authorization": "Bearer upstream-token",
                "Content-Type": "application/json",
                "X-Trace": "proxy-test",
            },
            content=json.dumps({"type": "image_to_3d", "input_url": "upload://demo"}),
        )

    assert ready_response.status_code == 200
    assert ready_response.json() == {
        "proxied": True,
        "path": "/ready",
        "query": {"check": "1"},
    }
    assert ready_response.headers["x-dev-proxy"] == "1"
    assert static_response.status_code == 200
    assert tasks_response.status_code == 200
    assert tasks_response.json() == {
        "proxied": True,
        "path": "/v1/tasks",
        "query": {"debug": "1"},
    }
    assert len(forwarded_requests) == 2
    assert forwarded_requests[0]["method"] == "GET"
    assert forwarded_requests[0]["url"] == "https://cubie3d.example.com/ready?check=1"
    assert forwarded_requests[0]["headers"]["authorization"] == "Bearer upstream-token"
    assert forwarded_requests[0]["headers"]["x-debug"] == "true"
    assert forwarded_requests[0]["stream"] is True
    assert forwarded_requests[1]["method"] == "POST"
    assert forwarded_requests[1]["url"] == "https://cubie3d.example.com/v1/tasks?debug=1"
    assert forwarded_requests[1]["headers"]["authorization"] == "Bearer upstream-token"
    assert forwarded_requests[1]["headers"]["x-trace"] == "proxy-test"
    assert json.loads(forwarded_requests[1]["body"].decode("utf-8")) == {
        "type": "image_to_3d",
        "input_url": "upload://demo",
    }
    assert proxy_clients and proxy_clients[0].closed is True


def test_dev_proxy_serves_local_model_override_for_artifact_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_requests: list[str] = []
    local_model = tmp_path / "model.glb"
    local_model.write_bytes(b"glTF-local-model")

    class FakeProxyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.closed = False

        def build_request(self, method: str, url: str, headers=None, content=None) -> httpx.Request:
            return httpx.Request(method, url, headers=headers, content=content)

        async def send(self, request: httpx.Request, stream: bool = False) -> httpx.Response:
            forwarded_requests.append(str(request.url))
            payload = {
                "proxied": True,
                "path": request.url.path,
            }
            return httpx.Response(
                status_code=200,
                headers={"content-type": "application/json", "x-dev-proxy": "1"},
                stream=httpx.ByteStream(json.dumps(payload).encode("utf-8")),
                request=request,
            )

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeProxyClient)

    config = ServingConfig(
        database_path=tmp_path / "app.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
        uploads_dir=tmp_path / "uploads",
        dev_proxy_target="https://cubie3d.example.com",
        dev_local_model_path=local_model,
    )

    with TestClient(create_test_app(config)) as client:
        model_response = client.get("/v1/tasks/remote-task/artifacts/model.glb")
        ready_response = client.get("/ready")

    assert model_response.status_code == 200
    assert model_response.content == b"glTF-local-model"
    assert model_response.headers["content-type"].startswith("model/gltf-binary")
    assert ready_response.status_code == 200
    assert ready_response.headers["x-dev-proxy"] == "1"
    assert forwarded_requests == ["https://cubie3d.example.com/ready"]


def test_root_and_spa_routes_serve_built_index_when_present(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spa_index = tmp_path / "dist" / "index.html"
    spa_index.parent.mkdir(parents=True, exist_ok=True)
    spa_index.write_text("<!doctype html><html><body>cubie3d spa</body></html>", encoding="utf-8")
    monkeypatch.setattr(server_module, "SPA_INDEX_PATH", spa_index)

    with make_client(tmp_path) as client:
        root_response = client.get("/")
        generate_response = client.get("/generate")
        generations_response = client.get("/generations")
        admin_dashboard_response = client.get("/admin/dashboard")

    assert root_response.status_code == 200
    assert "cubie3d spa" in root_response.text
    assert generate_response.status_code == 200
    assert "cubie3d spa" in generate_response.text
    assert generations_response.status_code == 200
    assert "cubie3d spa" in generations_response.text
    assert admin_dashboard_response.status_code == 200
    assert "cubie3d spa" in admin_dashboard_response.text


def test_root_assets_and_legacy_static_routes_work_with_built_spa(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spa_dist = tmp_path / "dist"
    spa_index = spa_dist / "index.html"
    spa_dist.mkdir(parents=True, exist_ok=True)
    spa_index.write_text("<!doctype html><html><body>cubie3d static spa</body></html>", encoding="utf-8")
    (spa_dist / "favicon.svg").write_text("<svg></svg>", encoding="utf-8")
    monkeypatch.setattr(server_module, "WEB_DIST_DIR", spa_dist)
    monkeypatch.setattr(server_module, "SPA_INDEX_PATH", spa_index)

    with make_client(tmp_path) as client:
        generate_response = client.get("/generate")
        admin_dashboard_response = client.get("/admin/dashboard")
        asset_response = client.get("/favicon.svg")
        static_redirect_response = client.get("/static", follow_redirects=False)
        static_generate_redirect_response = client.get("/static/generate", follow_redirects=False)

    assert generate_response.status_code == 200
    assert "cubie3d static spa" in generate_response.text
    assert admin_dashboard_response.status_code == 200
    assert "cubie3d static spa" in admin_dashboard_response.text
    assert asset_response.status_code == 200
    assert asset_response.text == "<svg></svg>"
    assert static_redirect_response.status_code == 308
    assert static_redirect_response.headers["location"] == "/"
    assert static_generate_redirect_response.status_code == 308
    assert static_generate_redirect_response.headers["location"] == "/generate"


def test_dev_proxy_does_not_forward_spa_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded_requests: list[str] = []
    spa_index = tmp_path / "dist" / "index.html"
    spa_index.parent.mkdir(parents=True, exist_ok=True)
    spa_index.write_text("<!doctype html><html><body>local spa</body></html>", encoding="utf-8")
    monkeypatch.setattr(server_module, "SPA_INDEX_PATH", spa_index)

    class FakeProxyClient:
        def __init__(self, *args, **kwargs) -> None:
            self.closed = False

        def build_request(self, *args, **kwargs):
            raise AssertionError("spa routes should not be proxied")

        async def send(self, *args, **kwargs):
            forwarded_requests.append("send")
            raise AssertionError("spa routes should not be proxied")

        async def aclose(self) -> None:
            self.closed = True

    monkeypatch.setattr(server_module.httpx, "AsyncClient", FakeProxyClient)

    config = ServingConfig(
        dev_proxy_target="https://cubie3d.example.com",
        database_path=tmp_path / "app.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
        uploads_dir=tmp_path / "uploads",
    )

    with TestClient(create_test_app(config)) as client:
        response = client.get("/generate")

    assert response.status_code == 200
    assert "local spa" in response.text
    assert forwarded_requests == []


def test_api_v1_alias_routes_to_task_api(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/api/v1/tasks", headers=task_auth_headers(client))

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "hasMore": False,
        "nextCursor": None,
    }


def test_app_startup_triggers_async_model_prewarm_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_build_model_runtime = server_module.build_model_runtime
    calls: list[str] = []

    async def tracking_build_model_runtime(model_store: ModelStore, config: ServingConfig, model_name: str):
        calls.append(model_name)
        await asyncio.sleep(0.5)
        return await original_build_model_runtime(model_store, config, model_name)

    monkeypatch.setattr(
        server_module,
        "build_model_runtime",
        tracking_build_model_runtime,
    )

    startup_started_at = time.perf_counter()
    with make_client(tmp_path) as client:
        startup_elapsed_seconds = time.perf_counter() - startup_started_at
        readiness_loading_response = client.get("/readiness")
        wait_for_condition(lambda: calls == ["trellis2"], timeout_seconds=1.0)
        wait_for_condition(
            lambda: client.get("/readiness").status_code == 200,
            timeout_seconds=2.0,
        )
        readiness_ready_response = client.get("/readiness")

    assert startup_elapsed_seconds < 1.0
    assert readiness_loading_response.status_code == 503
    assert readiness_loading_response.json() == {
        "status": "not_ready",
        "service": "cubie3d",
    }
    assert calls == ["trellis2"]
    assert readiness_ready_response.status_code == 200
    assert readiness_ready_response.json() == {
        "status": "ready",
        "service": "cubie3d",
    }


def test_create_task_returns_immediately_while_model_loads_in_background(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_build_model_runtime = server_module.build_model_runtime

    async def slow_build_model_runtime(model_store: ModelStore, config: ServingConfig, model_name: str):
        await asyncio.sleep(0.7)
        return await original_build_model_runtime(model_store, config, model_name)

    monkeypatch.setattr(
        server_module,
        "build_model_runtime",
        slow_build_model_runtime,
    )

    with make_client(tmp_path, queue_delay_ms=0) as client:
        readiness_before_response = client.get("/readiness")
        assert readiness_before_response.status_code == 503
        input_url = upload_input_url(client)

        started_at = time.perf_counter()
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": input_url,
                "options": {"resolution": 1024},
            },
        )
        elapsed_seconds = time.perf_counter() - started_at

        assert create_response.status_code == 201
        assert create_response.json()["status"] == "queued"
        assert elapsed_seconds < 0.25

        readiness_during_response = client.get("/readiness")
        assert readiness_during_response.status_code in {200, 503}

        wait_for_status(client, create_response.json()["taskId"], "succeeded", timeout_seconds=5.0)
        readiness_after_response = client.get("/readiness")

    assert readiness_after_response.status_code == 200
    assert readiness_after_response.json() == {
        "status": "ready",
        "service": "cubie3d",
    }


def test_worker_calls_request_load_before_wait_ready(tmp_path: Path) -> None:
    with make_client(tmp_path, queue_delay_ms=0) as client:
        container = client.app.state.container
        call_state = {
            "request_load_calls": 0,
            "wait_ready_checked": False,
        }

        original_request_load = container.model_scheduler.request_load
        original_wait_ready = container.model_registry.wait_ready

        async def tracking_request_load(model_name: str):
            call_state["request_load_calls"] += 1
            return await original_request_load(model_name)

        async def checking_wait_ready(model_name: str):
            assert call_state["request_load_calls"] > 0
            call_state["wait_ready_checked"] = True
            return await original_wait_ready(model_name)

        container.model_scheduler.request_load = tracking_request_load
        container.model_registry.wait_ready = checking_wait_ready

        response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert response.status_code == 201
        wait_for_status(
            client,
            response.json()["taskId"],
            "succeeded",
            timeout_seconds=5.0,
        )

    assert call_state["wait_ready_checked"] is True
    assert call_state["request_load_calls"] >= 1


def test_mock_mode_scheduler_disabled_with_eager_loaded_model_still_processes_tasks(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, queue_delay_ms=0) as client:
        container = client.app.state.container
        assert container.config.is_mock_provider is True
        assert container.model_scheduler._enabled is False
        wait_for_condition(
            lambda: client.get("/readiness").status_code == 200,
            timeout_seconds=3.0,
        )
        assert container.model_registry.get_state("trellis2") == "ready"

        response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "model": "trellis2",
                "options": {"resolution": 1024},
            },
        )
        assert response.status_code == 201
        final_payload = wait_for_status(
            client,
            response.json()["taskId"],
            "succeeded",
            timeout_seconds=5.0,
        )

    assert final_payload["model"] == "trellis2"


def test_bearer_auth_is_required_for_task_routes(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            json={"type": "image_to_3d", "image_url": "https://example.com/a.png"},
        )
        get_response = client.get("/v1/tasks/some-task-id")
        metrics_response = client.get("/metrics")
        metrics_authorized_response = client.get(
            "/metrics",
            headers=metrics_headers(client),
        )

    assert create_response.status_code == 401
    assert get_response.status_code == 401
    assert metrics_response.status_code == 401
    assert metrics_authorized_response.status_code == 200


def test_list_models_requires_auth(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.get("/v1/models")

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid bearer token"


def test_list_models_returns_enabled(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        enable_hunyuan_response = client.patch(
            "/api/admin/models/hunyuan3d",
            headers=admin_headers(),
            json={"isEnabled": True},
        )
        response = client.get("/v1/models", headers=task_auth_headers(client))

    assert enable_hunyuan_response.status_code == 200
    assert response.status_code == 200
    payload = response.json()
    assert [model["id"] for model in payload["models"]] == ["trellis2", "hunyuan3d"]
    assert payload["models"][0]["display_name"] == "TRELLIS2"
    assert payload["models"][0]["is_default"] is True
    assert payload["models"][1]["display_name"] == "HunYuan3D-2"
    assert payload["models"][1]["is_default"] is False
    assert payload["models"][0]["runtime_state"] in {"not_loaded", "loading", "ready", "error"}
    assert payload["models"][1]["runtime_state"] in {"not_loaded", "loading", "ready", "error"}


def test_admin_model_load_endpoint_returns_runtime_state(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        response = client.post(
            "/api/admin/models/trellis2/load",
            headers=admin_headers(),
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "trellis2"
    assert payload["runtime_state"] in {"not_loaded", "loading", "ready", "error"}
    assert payload["runtimeState"] == payload["runtime_state"]


def test_admin_create_model_requires_weight_source(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        response = client.post(
            "/api/admin/models",
            headers=admin_headers(),
            json={
                "id": "new-model",
                "providerType": "trellis2",
                "displayName": "New Model",
                "modelPath": "owner/new-model",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "weightSource must be one of: huggingface, url, local"


def test_admin_create_model_local_weight_source_resolves_synchronously(
    tmp_path: Path,
) -> None:
    local_weights_dir = tmp_path / "local-weights"
    local_weights_dir.mkdir(parents=True, exist_ok=True)
    (local_weights_dir / "weights.bin").write_bytes(b"ok")

    with make_client(tmp_path, admin_token="admin-token") as client:
        response = client.post(
            "/api/admin/models",
            headers=admin_headers(),
            json={
                "id": "local-model",
                "providerType": "trellis2",
                "displayName": "Local Model",
                "modelPath": str(local_weights_dir),
                "weightSource": "local",
            },
        )
        models_response = client.get(
            "/api/admin/models",
            headers=admin_headers(),
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["id"] == "local-model"
    assert payload["weight_source"] == "local"
    assert payload["download_status"] == "done"
    assert payload["download_progress"] == 100
    assert payload["resolved_path"] == str(local_weights_dir.resolve())

    assert models_response.status_code == 200
    model_ids = {model["id"] for model in models_response.json()["models"]}
    assert "local-model" in model_ids


def test_admin_models_include_pending_query_and_delete_cancels_download_task(
    tmp_path: Path,
) -> None:
    started = threading.Event()
    cancelled = threading.Event()

    with make_client(tmp_path, admin_token="admin-token") as client:
        container = client.app.state.container

        async def blocking_download(model_id: str, weight_source: str, model_path: str) -> str:
            del model_id, weight_source, model_path
            started.set()
            try:
                while True:
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                cancelled.set()
                raise

        container.weight_manager.download = blocking_download

        create_response = client.post(
            "/api/admin/models",
            headers=admin_headers(),
            json={
                "id": "pending-hf",
                "providerType": "trellis2",
                "displayName": "Pending HF",
                "modelPath": "owner/repo",
                "weightSource": "huggingface",
            },
        )
        assert create_response.status_code == 201
        wait_for_condition(started.is_set, timeout_seconds=2.0)

        default_list_response = client.get(
            "/api/admin/models",
            headers=admin_headers(),
        )
        pending_list_response = client.get(
            "/api/admin/models?include_pending=true",
            headers=admin_headers(),
        )
        delete_response = client.delete(
            "/api/admin/models/pending-hf",
            headers=admin_headers(),
        )

    assert default_list_response.status_code == 200
    assert "pending-hf" not in {model["id"] for model in default_list_response.json()["models"]}

    assert pending_list_response.status_code == 200
    pending_model = next(
        model for model in pending_list_response.json()["models"] if model["id"] == "pending-hf"
    )
    assert pending_model["download_status"] == "downloading"
    assert pending_model["weight_source"] == "huggingface"

    assert delete_response.status_code == 200
    wait_for_condition(cancelled.is_set, timeout_seconds=2.0)


def test_admin_create_model_url_rejects_non_archive_suffix(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        response = client.post(
            "/api/admin/models",
            headers=admin_headers(),
            json={
                "id": "url-model",
                "providerType": "trellis2",
                "displayName": "URL Model",
                "modelPath": "https://example.com/weights.bin",
                "weightSource": "url",
            },
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "url source only supports .zip and .tar.gz archives"


def test_create_task_rejects_disabled_model_from_model_store(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Model Tester")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client, token=managed_key["token"]),
                "model": "hunyuan3d",
                "options": {"resolution": 1024},
            },
        )

    assert create_response.status_code == 422
    assert create_response.json()["detail"] == "该模型已被管理员禁用"


def test_create_task_allows_model_not_in_model_store_for_backward_compat(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Compat Tester")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client, token=managed_key["token"]),
                "model": "trellis",
                "options": {"resolution": 1024},
            },
        )

    assert create_response.status_code == 201


def test_admin_settings_returns_dynamic_provider_options_and_excludes_deploy_fields(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        rename_response = client.patch(
            "/api/admin/models/step1x3d",
            headers=admin_headers(),
            json={"displayName": "Step1X-3D Custom"},
        )
        settings_response = client.get(
            "/api/admin/settings",
            headers=admin_headers(),
        )

    assert rename_response.status_code == 200
    assert settings_response.status_code == 200
    sections = settings_response.json()["sections"]
    assert all(section["key"] != "storage" for section in sections)
    generation_section = next(section for section in sections if section["key"] == "generation")
    generation_fields = generation_section["fields"]
    field_keys = {field["key"] for field in generation_fields}
    assert "maxParallelJobs" not in field_keys
    default_provider_field = next(
        field for field in generation_fields if field["key"] == "defaultProvider"
    )
    options = default_provider_field["options"]
    assert {"value": "trellis2", "label": "TRELLIS2"} in options
    assert {"value": "hunyuan3d", "label": "HunYuan3D-2"} in options
    assert {"value": "step1x3d", "label": "Step1X-3D Custom"} in options
    assert all("labelKey" not in option for option in options)
    assert all("Large" not in str(option.get("label", "")) for option in options)

    generation_field_keys = {field["key"] for field in generation_fields}
    assert "maxLoadedModels" in generation_field_keys
    assert "maxTasksPerSlot" in generation_field_keys


def test_admin_settings_patch_updates_scheduler_limits(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        patch_response = client.patch(
            "/api/admin/settings",
            headers=admin_headers(),
            json={"maxLoadedModels": 1, "maxTasksPerSlot": 6},
        )

    assert patch_response.status_code == 200
    assert set(patch_response.json()["updated"]) == {"maxLoadedModels", "maxTasksPerSlot"}


def test_admin_settings_patch_hot_updates_rate_limit_and_queue_capacity(
    tmp_path: Path,
) -> None:
    with make_client(
        tmp_path,
        admin_token="admin-token",
        rate_limit_per_hour=20,
        queue_delay_ms=500,
    ) as client:
        managed_key_a = create_managed_api_key(client, label="Hot Reload A")
        managed_key_b = create_managed_api_key(client, label="Hot Reload B")
        patch_response = client.patch(
            "/api/admin/settings",
            headers=admin_headers(),
            json={"rateLimitPerHour": 1, "queueMaxSize": 0},
        )
        first_task_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_a["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client, token=managed_key_a["token"]),
                "options": {"resolution": 1024},
            },
        )
        second_task_same_key_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_a["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client, token=managed_key_a["token"]),
                "options": {"resolution": 1024},
            },
        )
        third_task_other_key_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_b["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client, token=managed_key_b["token"]),
                "options": {"resolution": 1024},
            },
        )

    assert patch_response.status_code == 200
    assert set(patch_response.json()["updated"]) == {"rateLimitPerHour", "queueMaxSize"}
    assert first_task_response.status_code == 201
    assert second_task_same_key_response.status_code == 429
    assert "max 1 task requests per hour" in second_task_same_key_response.json()["detail"]
    assert third_task_other_key_response.status_code == 503
    assert third_task_other_key_response.json()["detail"]["code"] == "queue_full"


def test_admin_models_returns_friendly_error_message_when_runtime_load_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_build_model_runtime = server_module.build_model_runtime

    async def failing_build_model_runtime(model_store: ModelStore, config: ServingConfig, model_name: str):
        if str(model_name).strip().lower() == "hunyuan3d":
            raise RuntimeError("CUDA out of memory while loading model")
        return await original_build_model_runtime(model_store, config, model_name)

    monkeypatch.setattr(
        server_module,
        "build_model_runtime",
        failing_build_model_runtime,
    )

    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Model Error Tester")
        enable_response = client.patch(
            "/api/admin/models/hunyuan3d",
            headers=admin_headers(),
            json={"isEnabled": True},
        )
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client, token=managed_key["token"]),
                "model": "hunyuan3d",
                "options": {"resolution": 1024},
            },
        )
        assert enable_response.status_code == 200
        assert create_response.status_code == 201
        wait_for_status(
            client,
            create_response.json()["taskId"],
            "failed",
            token=managed_key["token"],
            timeout_seconds=5.0,
        )
        models_response = client.get(
            "/api/admin/models",
            headers=admin_headers(),
        )

    assert models_response.status_code == 200
    hunyuan_model = next(
        model
        for model in models_response.json()["models"]
        if model["id"] == "hunyuan3d"
    )
    assert hunyuan_model["runtimeState"] == "error"
    assert hunyuan_model["runtime_state"] == "error"
    assert hunyuan_model["error_message"] == "GPU 显存不足"
    assert hunyuan_model["maxTasksPerSlot"] == hunyuan_model["max_tasks_per_slot"]
    assert isinstance(hunyuan_model["max_tasks_per_slot"], int)
    assert hunyuan_model["max_tasks_per_slot"] >= 1


def test_privileged_key_routes_return_401_when_admin_token_is_unset(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token=None) as client:
        response = client.get("/api/admin/privileged-keys", headers=admin_headers())

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid admin token"


def test_privileged_key_crud_flow_returns_token_once_and_list_hides_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        create_response = client.post(
            "/api/admin/privileged-keys",
            headers=admin_headers(),
            json={
                "scope": "metrics",
                "label": "Metrics Team",
                "allowed_ips": ["10.0.0.1", "10.0.0.2"],
            },
        )
        assert create_response.status_code == 201
        created_payload = create_response.json()
        key_id = created_payload["keyId"]

        list_response = client.get("/api/admin/privileged-keys", headers=admin_headers())
        delete_response = client.delete(
            f"/api/admin/privileged-keys/{key_id}",
            headers=admin_headers(),
        )
        missing_response = client.delete(
            "/api/admin/privileged-keys/missing-key",
            headers=admin_headers(),
        )

    assert set(created_payload) == {
        "keyId",
        "token",
        "scope",
        "label",
        "allowedIps",
        "createdAt",
        "isActive",
    }
    assert created_payload["label"] == "Metrics Team"
    assert created_payload["token"]
    assert created_payload["scope"] == "metrics"
    assert created_payload["allowedIps"] == ["10.0.0.1", "10.0.0.2"]
    assert created_payload["isActive"] is True

    assert list_response.status_code == 200
    assert all("token" not in item for item in list_response.json())
    assert list_response.json()[0]["keyId"] == key_id
    assert list_response.json()[0]["scope"] == "metrics"
    assert list_response.json()[0]["allowedIps"] == ["10.0.0.1", "10.0.0.2"]
    assert list_response.json()[0]["isActive"] is True

    assert delete_response.status_code == 204

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "privileged token not found"


def test_admin_key_routes_require_admin_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        missing_token_response = client.get("/api/admin/keys")
        admin_token_response = client.get("/api/admin/keys", headers=admin_headers())
        invalid_token_response = client.get(
            "/api/admin/keys",
            headers=auth_headers("wrong-token"),
        )
        key_manager_token = create_privileged_api_key(
            client,
            scope="key_manager",
            label="Key Manager",
        )["token"]
        key_manager_response = client.get(
            "/api/admin/keys",
            headers=auth_headers(key_manager_token),
        )

    assert missing_token_response.status_code == 401
    assert missing_token_response.json()["detail"] == "invalid admin token"
    assert admin_token_response.status_code == 200
    assert invalid_token_response.status_code == 401
    assert invalid_token_response.json()["detail"] == "invalid admin token"
    assert key_manager_response.status_code == 401
    assert key_manager_response.json()["detail"] == "invalid admin token"


def test_admin_hf_routes_require_admin_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr(server_module, "_hf_get_token", lambda: None)
    monkeypatch.setattr(server_module, "_hf_login", lambda token: None)
    monkeypatch.setattr(server_module, "_hf_logout", lambda: None)
    monkeypatch.setattr(server_module, "_hf_whoami", lambda token=None: {"name": "cubie-user"})

    with make_client(tmp_path, admin_token="admin-token") as client:
        missing_token_response = client.get("/api/admin/hf-status")
        invalid_token_response = client.get(
            "/api/admin/hf-status",
            headers=auth_headers("wrong-token"),
        )
        admin_token_response = client.get(
            "/api/admin/hf-status",
            headers=admin_headers(),
        )
        missing_endpoint_token_response = client.patch(
            "/api/admin/hf-endpoint",
            json={"endpoint": "https://hf-mirror.com"},
        )
        invalid_endpoint_token_response = client.patch(
            "/api/admin/hf-endpoint",
            headers=auth_headers("wrong-token"),
            json={"endpoint": "https://hf-mirror.com"},
        )
        admin_endpoint_response = client.patch(
            "/api/admin/hf-endpoint",
            headers=admin_headers(),
            json={"endpoint": "https://hf-mirror.com"},
        )

    assert missing_token_response.status_code == 401
    assert missing_token_response.json()["detail"] == "invalid admin token"
    assert invalid_token_response.status_code == 401
    assert invalid_token_response.json()["detail"] == "invalid admin token"
    assert admin_token_response.status_code == 200
    assert admin_token_response.json() == {
        "logged_in": False,
        "username": None,
        "endpoint": "https://huggingface.co",
    }
    assert missing_endpoint_token_response.status_code == 401
    assert missing_endpoint_token_response.json()["detail"] == "invalid admin token"
    assert invalid_endpoint_token_response.status_code == 401
    assert invalid_endpoint_token_response.json()["detail"] == "invalid admin token"
    assert admin_endpoint_response.status_code == 200
    assert admin_endpoint_response.json() == {"endpoint": "https://hf-mirror.com"}


def test_admin_hf_login_status_logout_flow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    state = {"token": ""}

    def fake_get_token() -> str | None:
        return state["token"] or None

    def fake_whoami(token: str | None = None) -> dict[str, str]:
        resolved_token = token or state["token"]
        if resolved_token != "hf-valid-token":
            raise RuntimeError("invalid token")
        return {"name": "cubie-user"}

    def fake_login(token: str) -> None:
        if token != "hf-valid-token":
            raise ValueError("invalid token")
        state["token"] = token

    def fake_logout() -> None:
        state["token"] = ""

    monkeypatch.setattr(server_module, "_hf_get_token", fake_get_token)
    monkeypatch.setattr(server_module, "_hf_login", fake_login)
    monkeypatch.setattr(server_module, "_hf_logout", fake_logout)
    monkeypatch.setattr(server_module, "_hf_whoami", fake_whoami)

    with make_client(tmp_path, admin_token="admin-token") as client:
        before_response = client.get("/api/admin/hf-status", headers=admin_headers())
        set_endpoint_response = client.patch(
            "/api/admin/hf-endpoint",
            headers=admin_headers(),
            json={"endpoint": "https://hf-mirror.com"},
        )
        failed_login_response = client.post(
            "/api/admin/hf-login",
            headers=admin_headers(),
            json={"token": "bad-token"},
        )
        login_response = client.post(
            "/api/admin/hf-login",
            headers=admin_headers(),
            json={"token": "hf-valid-token"},
        )
        after_response = client.get("/api/admin/hf-status", headers=admin_headers())
        logout_response = client.post("/api/admin/hf-logout", headers=admin_headers())
        reset_endpoint_response = client.patch(
            "/api/admin/hf-endpoint",
            headers=admin_headers(),
            json={"endpoint": ""},
        )
        final_response = client.get("/api/admin/hf-status", headers=admin_headers())

    assert before_response.status_code == 200
    assert before_response.json() == {
        "logged_in": False,
        "username": None,
        "endpoint": "https://huggingface.co",
    }

    assert set_endpoint_response.status_code == 200
    assert set_endpoint_response.json() == {"endpoint": "https://hf-mirror.com"}

    assert failed_login_response.status_code == 422
    assert failed_login_response.json()["detail"] == "invalid token"

    assert login_response.status_code == 200
    assert login_response.json() == {
        "logged_in": True,
        "username": "cubie-user",
        "endpoint": "https://hf-mirror.com",
    }

    assert after_response.status_code == 200
    assert after_response.json() == {
        "logged_in": True,
        "username": "cubie-user",
        "endpoint": "https://hf-mirror.com",
    }

    assert logout_response.status_code == 200
    assert logout_response.json() == {
        "logged_in": False,
        "username": None,
        "endpoint": "https://hf-mirror.com",
    }

    assert reset_endpoint_response.status_code == 200
    assert reset_endpoint_response.json() == {"endpoint": "https://huggingface.co"}

    assert final_response.status_code == 200
    assert final_response.json() == {
        "logged_in": False,
        "username": None,
        "endpoint": "https://huggingface.co",
    }


def test_admin_hf_status_keeps_logged_in_when_whoami_unreachable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_ENDPOINT", raising=False)
    monkeypatch.setattr(server_module, "_hf_get_token", lambda: "hf-valid-token")
    monkeypatch.setattr(server_module, "_hf_login", lambda token: None)
    monkeypatch.setattr(server_module, "_hf_logout", lambda: None)

    def failing_whoami(token: str | None = None) -> dict[str, str]:
        raise RuntimeError("network unreachable")

    monkeypatch.setattr(server_module, "_hf_whoami", failing_whoami)

    with make_client(tmp_path, admin_token="admin-token") as client:
        response = client.get("/api/admin/hf-status", headers=admin_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["logged_in"] is True
    assert body["username"] is None


def test_admin_key_crud_flow_returns_token_once_and_list_hides_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        create_response = client.post(
            "/api/admin/keys",
            headers=admin_headers(),
            json={"label": "QA Team"},
        )
        assert create_response.status_code == 201
        created_payload = create_response.json()
        key_id = created_payload["keyId"]

        list_response = client.get("/api/admin/keys", headers=admin_headers())
        patch_response = client.patch(
            f"/api/admin/keys/{key_id}",
            headers=admin_headers(),
            json={"isActive": False},
        )
        missing_response = client.patch(
            "/api/admin/keys/missing-key",
            headers=admin_headers(),
            json={"isActive": False},
        )
        delete_response = client.delete(
            f"/api/admin/keys/{key_id}",
            headers=admin_headers(),
        )
        list_after_delete_response = client.get("/api/admin/keys", headers=admin_headers())
        delete_missing_response = client.delete(
            "/api/admin/keys/missing-key",
            headers=admin_headers(),
        )

    assert set(created_payload) == {"keyId", "token", "label", "createdAt"}
    assert created_payload["label"] == "QA Team"
    assert created_payload["token"]

    assert list_response.status_code == 200
    assert all("token" not in item for item in list_response.json())
    assert list_response.json()[0]["keyId"] == key_id
    assert list_response.json()[0]["isActive"] is True

    assert patch_response.status_code == 200
    assert patch_response.json()["keyId"] == key_id
    assert patch_response.json()["isActive"] is False

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "api key not found"
    assert delete_response.status_code == 204
    assert list_after_delete_response.status_code == 200
    assert all(item["keyId"] != key_id for item in list_after_delete_response.json())
    assert delete_missing_response.status_code == 404
    assert delete_missing_response.json()["detail"] == "api key not found"


def test_user_key_auth_accepts_user_keys_and_rejects_other_token_scopes(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Tester A")
        key_manager_token = create_privileged_api_key(
            client,
            scope="key_manager",
            label="Key Manager",
        )["token"]
        task_viewer_token = create_privileged_api_key(
            client,
            scope="task_viewer",
            label="Task Viewer",
        )["token"]
        metrics_token = create_privileged_api_key(
            client,
            scope="metrics",
            label="Metrics",
        )["token"]

        managed_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        invalid_response = client.post(
            "/v1/tasks",
            headers=auth_headers("invalid-key"),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        key_manager_response = client.post(
            "/v1/tasks",
            headers=auth_headers(key_manager_token),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        task_viewer_response = client.get(
            "/v1/tasks",
            headers=auth_headers(task_viewer_token),
        )
        metrics_scope_response = client.get(
            "/v1/tasks",
            headers=auth_headers(metrics_token),
        )
        admin_token_response = client.get(
            "/v1/tasks",
            headers=admin_headers(),
        )

        assert managed_response.status_code == 201
        wait_for_status(
            client,
            managed_response.json()["taskId"],
            "succeeded",
            token=managed_key["token"],
        )

    assert invalid_response.status_code == 401
    assert invalid_response.json()["detail"] == "invalid bearer token"
    assert key_manager_response.status_code == 401
    assert key_manager_response.json()["detail"] == "invalid bearer token"
    assert task_viewer_response.status_code == 401
    assert task_viewer_response.json()["detail"] == "invalid bearer token"
    assert metrics_scope_response.status_code == 401
    assert metrics_scope_response.json()["detail"] == "invalid bearer token"
    assert admin_token_response.status_code == 401
    assert admin_token_response.json()["detail"] == "invalid bearer token"


def test_inactive_managed_api_key_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Tester B")
        deactivate_response = client.patch(
            f"/api/admin/keys/{managed_key['keyId']}",
            headers=admin_headers(),
            json={"is_active": False},
        )
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )

    assert deactivate_response.status_code == 200
    assert deactivate_response.json()["isActive"] is False
    assert create_response.status_code == 401
    assert create_response.json()["detail"] == "invalid bearer token"


def test_task_list_is_scoped_to_managed_api_keys(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key_a = create_managed_api_key(client, label="Tester A")
        managed_key_b = create_managed_api_key(client, label="Tester B")

        key_a_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_a["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        time.sleep(0.01)
        key_b_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_b["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )

        key_a_list_response = client.get(
            "/v1/tasks",
            headers=auth_headers(managed_key_a["token"]),
        )
        key_b_list_response = client.get(
            "/v1/tasks",
            headers=auth_headers(managed_key_b["token"]),
        )

    assert key_a_create_response.status_code == 201
    assert key_b_create_response.status_code == 201

    assert key_a_list_response.status_code == 200
    assert [task["taskId"] for task in task_page_items(key_a_list_response)] == [
        key_a_create_response.json()["taskId"]
    ]
    assert key_a_list_response.json()["hasMore"] is False
    assert key_a_list_response.json()["nextCursor"] is None

    assert key_b_list_response.status_code == 200
    assert [task["taskId"] for task in task_page_items(key_b_list_response)] == [
        key_b_create_response.json()["taskId"]
    ]


def test_admin_tasks_returns_all_tasks_and_supports_key_filter(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key_a = create_managed_api_key(client, label="Tester A")
        managed_key_b = create_managed_api_key(client, label="Tester B")

        key_a_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_a["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        time.sleep(0.01)
        key_b_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_b["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )

        all_response = client.get(
            "/api/admin/tasks",
            headers=admin_headers(),
        )
        key_a_response = client.get(
            f"/api/admin/tasks?key_id={managed_key_a['keyId']}",
            headers=admin_headers(),
        )

    assert key_a_create_response.status_code == 201
    assert key_b_create_response.status_code == 201

    assert all_response.status_code == 200
    assert [task["taskId"] for task in task_page_items(all_response)] == [
        key_b_create_response.json()["taskId"],
        key_a_create_response.json()["taskId"],
    ]

    assert key_a_response.status_code == 200
    assert [task["taskId"] for task in task_page_items(key_a_response)] == [
        key_a_create_response.json()["taskId"]
    ]


def test_admin_task_owner_prefers_key_label(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Studio Team")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        tasks_response = client.get(
            "/api/admin/tasks",
            headers=admin_headers(),
        )
        dashboard_response = client.get(
            "/api/admin/dashboard",
            headers=admin_headers(),
        )

    assert create_response.status_code == 201
    assert tasks_response.status_code == 200
    task = task_page_items(tasks_response)[0]
    assert task["keyId"] == managed_key["keyId"]
    assert task["keyLabel"] == "Studio Team"
    assert task["owner"] == "Studio Team"
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["recentTasks"][0]["owner"] == "Studio Team"


def test_admin_task_owner_falls_back_to_key_prefix(tmp_path: Path) -> None:
    database_path = tmp_path / "app.sqlite3"
    key_id = "448572a7a8ab479b920c1efee99dcf88"
    now = utcnow()
    seed_tasks(
        database_path,
        [
            RequestSequence(
                task_id="owner-fallback-task",
                task_type=TaskType.IMAGE_TO_3D,
                model="trellis",
                input_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
                status=TaskStatus.QUEUED,
                progress=0,
                current_stage=TaskStatus.QUEUED.value,
                key_id=key_id,
                created_at=now,
                queued_at=now,
                updated_at=now,
            )
        ],
    )

    with make_client(tmp_path, database_path=database_path, admin_token="admin-token") as client:
        tasks_response = client.get(
            "/api/admin/tasks",
            headers=admin_headers(),
        )
        dashboard_response = client.get(
            "/api/admin/dashboard",
            headers=admin_headers(),
        )

    assert tasks_response.status_code == 200
    task = task_page_items(tasks_response)[0]
    assert task["keyId"] == key_id
    assert task["keyLabel"] == ""
    assert task["owner"] == "448572a7\u2026"
    assert dashboard_response.status_code == 200
    assert dashboard_response.json()["recentTasks"][0]["owner"] == "448572a7\u2026"


def test_admin_tasks_requires_valid_admin_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        missing_token_response = client.get("/api/admin/tasks")
        invalid_token_response = client.get(
            "/api/admin/tasks",
            headers=auth_headers("wrong-token"),
        )
        admin_token_response = client.get(
            "/api/admin/tasks",
            headers=admin_headers(),
        )
        task_viewer_token = create_privileged_api_key(
            client,
            scope="task_viewer",
            label="Task Viewer",
        )["token"]
        task_viewer_response = client.get(
            "/api/admin/tasks",
            headers=auth_headers(task_viewer_token),
        )

    assert missing_token_response.status_code == 401
    assert missing_token_response.json()["detail"] == "invalid admin token"
    assert invalid_token_response.status_code == 401
    assert invalid_token_response.json()["detail"] == "invalid admin token"
    assert admin_token_response.status_code == 200
    assert task_viewer_response.status_code == 401
    assert task_viewer_response.json()["detail"] == "invalid admin token"


def test_metrics_requires_metrics_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Metrics User")
        key_manager_token = create_privileged_api_key(
            client,
            scope="key_manager",
            label="Metrics Key Manager",
        )["token"]
        task_viewer_token = create_privileged_api_key(
            client,
            scope="task_viewer",
            label="Metrics Task Viewer",
        )["token"]

        missing_token_response = client.get("/metrics")
        user_key_response = client.get(
            "/metrics",
            headers=auth_headers(managed_key["token"]),
        )
        key_manager_response = client.get(
            "/metrics",
            headers=auth_headers(key_manager_token),
        )
        task_viewer_response = client.get(
            "/metrics",
            headers=auth_headers(task_viewer_token),
        )
        admin_token_response = client.get(
            "/metrics",
            headers=admin_headers(),
        )
        metrics_token_response = client.get(
            "/metrics",
            headers=metrics_headers(client),
        )

    assert missing_token_response.status_code == 401
    assert missing_token_response.json()["detail"] == "invalid bearer token"
    assert user_key_response.status_code == 401
    assert user_key_response.json()["detail"] == "invalid bearer token"
    assert key_manager_response.status_code == 401
    assert key_manager_response.json()["detail"] == "invalid bearer token"
    assert task_viewer_response.status_code == 401
    assert task_viewer_response.json()["detail"] == "invalid bearer token"
    assert admin_token_response.status_code == 401
    assert admin_token_response.json()["detail"] == "invalid bearer token"
    assert metrics_token_response.status_code == 200


def test_task_list_returns_requested_page_and_cursor_metadata(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.sqlite3"
    base_time = utcnow()
    seed_tasks(
        database_path,
        [
            RequestSequence(
                task_id=f"task-{index:02d}",
                task_type=TaskType.IMAGE_TO_3D,
                model="trellis",
                input_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
                status=TaskStatus.QUEUED,
                progress=0,
                current_stage=TaskStatus.QUEUED.value,
                created_at=base_time - timedelta(seconds=54 - index),
                queued_at=base_time - timedelta(seconds=54 - index),
                updated_at=base_time - timedelta(seconds=54 - index),
            )
            for index in range(55)
        ],
    )

    with make_client(tmp_path, database_path=database_path) as client:
        response = client.get(
            "/api/admin/tasks?limit=50",
            headers=admin_headers(),
        )

    assert response.status_code == 200
    tasks = task_page_items(response)
    assert len(tasks) == 50
    assert tasks[0]["taskId"] == "task-54"
    assert tasks[-1]["taskId"] == "task-05"
    assert response.json()["hasMore"] is True
    assert response.json()["nextCursor"] == tasks[-1]["createdAt"]


def test_service_startup_migrates_existing_tasks_table_and_preserves_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    created_at = utcnow().isoformat()

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'image_to_3d',
                input_url TEXT NOT NULL,
                options_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                callback_url TEXT,
                output_artifacts_json TEXT NOT NULL DEFAULT '[]',
                error_message TEXT,
                failed_stage TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                assigned_worker_id TEXT,
                current_stage TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                queue_position INTEGER,
                estimated_wait_seconds INTEGER,
                estimated_finish_at TEXT,
                created_at TEXT NOT NULL,
                queued_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO tasks (
                id, status, type, input_url, options_json, idempotency_key,
                callback_url, output_artifacts_json, error_message, failed_stage,
                retry_count, assigned_worker_id, current_stage, progress,
                queue_position, estimated_wait_seconds, estimated_finish_at,
                created_at, queued_at, started_at, completed_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-task",
                "submitted",
                "image_to_3d",
                SAMPLE_IMAGE_DATA_URL,
                json.dumps({"resolution": 1024}),
                None,
                None,
                "[]",
                None,
                None,
                0,
                None,
                "submitted",
                0,
                None,
                None,
                None,
                created_at,
                created_at,
                None,
                None,
                created_at,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    with make_client(tmp_path, database_path=database_path) as client:
        response = client.get("/api/admin/tasks", headers=admin_headers())

    migrated_connection = sqlite3.connect(database_path)
    try:
        columns = {
            row[1]
            for row in migrated_connection.execute("PRAGMA table_info(tasks)").fetchall()
        }
    finally:
        migrated_connection.close()

    assert response.status_code == 200
    assert task_page_items(response)[0]["taskId"] == "legacy-task"
    assert "key_id" in columns
    assert "deleted_at" in columns
    assert "cleanup_done" in columns


def test_service_startup_migrates_existing_api_keys_table_and_preserves_legacy_rows(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-api-keys.sqlite3"
    created_at = utcnow().isoformat()

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE api_keys (
                key_id TEXT PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        connection.execute(
            """
            INSERT INTO api_keys (key_id, token, label, created_at, is_active)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("legacy-user-key", "legacy-user-token", "Legacy User", created_at, 1),
        )
        connection.commit()
    finally:
        connection.close()

    with make_client(tmp_path, database_path=database_path) as client:
        bootstrap_response = client.post(
            "/api/admin/privileged-keys",
            headers=admin_headers(),
            json={"scope": "key_manager", "label": "Migrated Key Manager"},
        )
        assert bootstrap_response.status_code == 201
        list_response = client.get(
            "/api/admin/keys",
            headers=admin_headers(),
        )
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers("legacy-user-token"),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )

    migrated_connection = sqlite3.connect(database_path)
    try:
        columns = {
            row[1]
            for row in migrated_connection.execute("PRAGMA table_info(api_keys)").fetchall()
        }
        migrated_row = migrated_connection.execute(
            "SELECT scope, allowed_ips FROM api_keys WHERE key_id = ?",
            ("legacy-user-key",),
        ).fetchone()
    finally:
        migrated_connection.close()

    assert list_response.status_code == 200
    assert list_response.json()[0]["keyId"] == "legacy-user-key"
    assert create_response.status_code == 201
    assert "scope" in columns
    assert "allowed_ips" in columns
    assert migrated_row == ("user", None)


def test_delete_task_soft_deletes_own_terminal_task_and_removes_artifacts(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    uploads_dir = tmp_path / "uploads"
    with make_client(
        tmp_path,
        admin_token="admin-token",
        artifacts_dir=artifacts_dir,
        uploads_dir=uploads_dir,
    ) as client:
        managed_key = create_managed_api_key(client, label="Owner")
        uploaded_url = upload_input_url(client, token=managed_key["token"])
        upload_id = uploaded_url.removeprefix("upload://")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": uploaded_url,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        wait_for_status(
            client,
            task_id,
            "succeeded",
            token=managed_key["token"],
        )
        assert artifacts_dir.joinpath(task_id).exists()
        assert uploads_dir.joinpath(f"{upload_id}.png").exists()

        delete_response = client.delete(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(managed_key["token"]),
        )
        list_response = client.get(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
        )
        artifact_response = client.get(
            f"/v1/tasks/{task_id}/artifacts",
            headers=auth_headers(managed_key["token"]),
        )

    assert delete_response.status_code == 204
    wait_for_condition(
        lambda: artifacts_dir.joinpath(task_id).exists() is False,
        timeout_seconds=2.0,
    )
    wait_for_condition(
        lambda: uploads_dir.joinpath(f"{upload_id}.png").exists() is False,
        timeout_seconds=2.0,
    )
    assert [task["taskId"] for task in task_page_items(list_response)] == []
    assert artifact_response.status_code == 404


def test_delete_task_returns_204_without_waiting_for_artifact_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    cleanup_started = threading.Event()
    allow_cleanup = threading.Event()

    with make_client(
        tmp_path,
        admin_token="admin-token",
        artifacts_dir=artifacts_dir,
    ) as client:
        managed_key = create_managed_api_key(client, label="Owner")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        wait_for_status(
            client,
            task_id,
            "succeeded",
            token=managed_key["token"],
        )
        assert artifacts_dir.joinpath(task_id).exists()

        artifact_store = client.app.state.container.artifact_store
        original_delete_artifacts = artifact_store.delete_artifacts

        async def slow_delete_artifacts(task_id: str) -> None:
            cleanup_started.set()
            await asyncio.to_thread(allow_cleanup.wait, 2.0)
            await original_delete_artifacts(task_id)

        monkeypatch.setattr(artifact_store, "delete_artifacts", slow_delete_artifacts)

        started_at = time.perf_counter()
        delete_response = client.delete(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(managed_key["token"]),
        )
        elapsed_seconds = time.perf_counter() - started_at

        assert delete_response.status_code == 204
        assert elapsed_seconds < 0.5
        assert cleanup_started.wait(timeout=0.5)
        assert artifacts_dir.joinpath(task_id).exists()

        allow_cleanup.set()
        wait_for_condition(
            lambda: artifacts_dir.joinpath(task_id).exists() is False,
            timeout_seconds=2.0,
        )


def test_delete_task_artifact_cleanup_failure_only_logs_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[str, dict]] = []

    class WarningLogger:
        def warning(self, event: str, **kwargs) -> None:
            warnings.append((event, kwargs))

    with make_client(
        tmp_path,
        admin_token="admin-token",
        artifacts_dir=tmp_path / "artifacts",
    ) as client:
        managed_key = create_managed_api_key(client, label="Owner")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]
        wait_for_status(
            client,
            task_id,
            "succeeded",
            token=managed_key["token"],
        )

        artifact_store = client.app.state.container.artifact_store
        engine = client.app.state.container.engine

        async def failing_delete_artifacts(_: str) -> None:
            raise ArtifactStoreOperationError("cleanup", "boom")

        monkeypatch.setattr(artifact_store, "delete_artifacts", failing_delete_artifacts)
        monkeypatch.setattr(engine, "_logger", WarningLogger())

        delete_response = client.delete(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(managed_key["token"]),
        )

        assert delete_response.status_code == 204
        wait_for_condition(lambda: len(warnings) == 1, timeout_seconds=2.0)

    event, metadata = warnings[0]
    assert event == "task.artifact_cleanup_failed"
    assert metadata["stage"] == "cleanup"
    assert "boom" in metadata["error"]


def test_cleanup_worker_recovers_pending_cleanup_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "app.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    cleanup_started = threading.Event()
    allow_cleanup = threading.Event()

    with make_client(
        tmp_path,
        admin_token="admin-token",
        database_path=database_path,
        artifacts_dir=artifacts_dir,
    ) as client:
        managed_key = create_managed_api_key(client, label="Owner")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]
        wait_for_status(
            client,
            task_id,
            "succeeded",
            token=managed_key["token"],
        )
        assert artifacts_dir.joinpath(task_id).exists()

        artifact_store = client.app.state.container.artifact_store
        original_delete_artifacts = artifact_store.delete_artifacts

        async def slow_delete_artifacts(task_id: str) -> None:
            cleanup_started.set()
            await asyncio.to_thread(allow_cleanup.wait, 2.0)
            await original_delete_artifacts(task_id)

        monkeypatch.setattr(artifact_store, "delete_artifacts", slow_delete_artifacts)

        delete_response = client.delete(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(managed_key["token"]),
        )
        assert delete_response.status_code == 204
        assert cleanup_started.wait(timeout=0.5)

    assert artifacts_dir.joinpath(task_id).exists()

    allow_cleanup.set()
    with make_client(
        tmp_path,
        admin_token="admin-token",
        database_path=database_path,
        artifacts_dir=artifacts_dir,
    ):
        wait_for_condition(
            lambda: artifacts_dir.joinpath(task_id).exists() is False,
            timeout_seconds=2.0,
        )


def test_delete_non_terminal_task_returns_409(tmp_path: Path) -> None:
    with make_client(
        tmp_path,
        admin_token="admin-token",
        queue_delay_ms=1000,
    ) as client:
        managed_key = create_managed_api_key(client, label="Owner")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        delete_response = client.delete(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(managed_key["token"]),
        )

    assert delete_response.status_code == 409
    assert "cannot be deleted" in delete_response.json()["detail"]


def test_delete_other_keys_task_returns_403(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key_a = create_managed_api_key(client, label="Owner")
        managed_key_b = create_managed_api_key(client, label="Other")
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_a["token"]),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        wait_for_status(
            client,
            task_id,
            "succeeded",
            token=managed_key_a["token"],
        )
        delete_response = client.delete(
            f"/v1/tasks/{task_id}",
            headers=auth_headers(managed_key_b["token"]),
        )

    assert delete_response.status_code == 403
    assert delete_response.json()["detail"] == "forbidden"


def test_task_list_cursor_pagination_is_stable_when_newer_task_arrives(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "app.sqlite3"
    base_time = utcnow()
    seed_tasks(
        database_path,
        [
            RequestSequence(
                task_id=f"seed-{index}",
                task_type=TaskType.IMAGE_TO_3D,
                model="trellis",
                input_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
                status=TaskStatus.SUCCEEDED,
                progress=100,
                current_stage=TaskStatus.SUCCEEDED.value,
                created_at=base_time - timedelta(seconds=4 - index),
                queued_at=base_time - timedelta(seconds=4 - index),
                completed_at=base_time - timedelta(seconds=4 - index),
                updated_at=base_time - timedelta(seconds=4 - index),
            )
            for index in range(5)
        ],
    )

    with make_client(tmp_path, database_path=database_path) as client:
        first_page_response = client.get(
            "/api/admin/tasks?limit=2",
            headers=admin_headers(),
        )
        assert first_page_response.status_code == 200
        first_page_items = task_page_items(first_page_response)

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201

        second_page_response = client.get(
            "/api/admin/tasks",
            params={
                "limit": 2,
                "before": first_page_response.json()["nextCursor"],
            },
            headers=admin_headers(),
        )

    assert [task["taskId"] for task in first_page_items] == ["seed-4", "seed-3"]
    assert second_page_response.status_code == 200
    assert [task["taskId"] for task in task_page_items(second_page_response)] == [
        "seed-2",
        "seed-1",
    ]


def test_upload_endpoint_accepts_png_and_jpg_and_uploaded_url_can_run_task(
    tmp_path: Path,
) -> None:
    uploads_dir = tmp_path / "uploads"
    with make_client(tmp_path, uploads_dir=uploads_dir) as client:
        png_response = client.post(
            "/v1/upload",
            headers=task_auth_headers(client),
            files={
                "file": (
                    "pixel.png",
                    make_image_bytes("PNG"),
                    "image/png",
                )
            },
        )
        jpg_response = client.post(
            "/v1/upload",
            headers=task_auth_headers(client),
            files={
                "file": (
                    "pixel.jpg",
                    make_image_bytes("JPEG"),
                    "image/jpeg",
                )
            },
        )

        assert png_response.status_code == 201
        assert jpg_response.status_code == 201

        png_payload = png_response.json()
        jpg_payload = jpg_response.json()
        assert uploads_dir.joinpath(f"{png_payload['uploadId']}.png").exists()
        assert uploads_dir.joinpath(f"{jpg_payload['uploadId']}.jpg").exists()

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": png_payload["url"],
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        wait_for_status(
            client,
            create_response.json()["taskId"],
            "succeeded",
            timeout_seconds=5.0,
        )

    assert png_payload["url"] == f"upload://{png_payload['uploadId']}"
    assert jpg_payload["url"] == f"upload://{jpg_payload['uploadId']}"


def test_upload_endpoint_rejects_unsupported_file_type(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/upload",
            headers=task_auth_headers(client),
            files={
                "file": (
                    "note.txt",
                    b"not an image",
                    "text/plain",
                )
            },
        )

    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"]


def test_upload_endpoint_rejects_oversized_file(tmp_path: Path) -> None:
    with make_client(tmp_path, preprocess_max_image_bytes=8) as client:
        response = client.post(
            "/v1/upload",
            headers=task_auth_headers(client),
            files={
                "file": (
                    "huge.png",
                    b"123456789",
                    "image/png",
                )
            },
        )

    assert response.status_code == 400
    assert "exceeds max size" in response.json()["detail"]


def test_create_task_rejects_http_input_url(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": "https://example.com/image.png",
                "options": {"resolution": 1024},
            },
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "input_url must start with upload://"


def test_create_task_defaults_type_and_model_when_omitted(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )

    assert response.status_code == 201
    assert response.json()["status"] == "queued"
    assert response.json()["model"] == "trellis"


def test_create_task_persists_selected_model_id(tmp_path: Path) -> None:
    with make_client(tmp_path, queue_delay_ms=0) as client:
        response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "input_url": upload_input_url(client),
                "model": "trellis2",
                "options": {"resolution": 1024},
            },
        )
        assert response.status_code == 201
        task_id = response.json()["taskId"]
        wait_for_status(client, task_id, "succeeded", timeout_seconds=5.0)
        detail_response = client.get(
            f"/v1/tasks/{task_id}",
            headers=task_auth_headers(client),
        )

    assert detail_response.status_code == 200
    assert detail_response.json()["model"] == "trellis2"


def test_create_task_with_empty_model_uses_default_model_from_store(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        enable_and_set_default_response = client.patch(
            "/api/admin/models/step1x3d",
            headers=admin_headers(),
            json={"isEnabled": True, "isDefault": True},
        )
        assert enable_and_set_default_response.status_code == 200

        response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "input_url": upload_input_url(client),
                "model": "",
                "options": {"resolution": 1024},
            },
        )

    assert response.status_code == 201
    assert response.json()["model"] == "step1x3d"


def test_task_detail_includes_input_url_and_dynamic_eta_after_stage_history(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, queue_delay_ms=300) as client:
        warmup_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert warmup_response.status_code == 201
        wait_for_status(client, warmup_response.json()["taskId"], "succeeded")

        first_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        second_input_url = upload_input_url(client)
        second_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": second_input_url,
                "options": {"resolution": 1024},
            },
        )
        assert first_response.status_code == 201
        assert second_response.status_code == 201
        processing_statuses = {
            "preprocessing",
            "gpu_queued",
            "gpu_ss",
            "gpu_shape",
            "gpu_material",
            "exporting",
            "uploading",
        }

        def first_task_is_processing_and_second_is_queued() -> bool:
            first_detail = client.get(
                f"/v1/tasks/{first_response.json()['taskId']}",
                headers=task_auth_headers(client),
            )
            second_detail = client.get(
                f"/v1/tasks/{second_response.json()['taskId']}",
                headers=task_auth_headers(client),
            )
            assert first_detail.status_code == 200
            assert second_detail.status_code == 200
            return (
                first_detail.json()["status"] in processing_statuses
                and second_detail.json()["status"] == "queued"
            )

        wait_for_condition(
            first_task_is_processing_and_second_is_queued,
            timeout_seconds=15.0,
        )

        queued_detail = client.get(
            f"/v1/tasks/{second_response.json()['taskId']}",
            headers=task_auth_headers(client),
        )
        processing_detail = client.get(
            f"/v1/tasks/{first_response.json()['taskId']}",
            headers=task_auth_headers(client),
        )

    assert queued_detail.status_code == 200
    assert queued_detail.json()["input_url"] == second_input_url
    assert queued_detail.json()["status"] == "queued"
    assert queued_detail.json()["queuePosition"] == 1
    assert isinstance(queued_detail.json()["estimatedWaitSeconds"], int)
    assert queued_detail.json()["estimatedWaitSeconds"] > 0

    assert processing_detail.status_code == 200
    assert processing_detail.json()["input_url"].startswith("upload://")
    assert isinstance(processing_detail.json()["estimatedWaitSeconds"], int)
    assert processing_detail.json()["estimatedWaitSeconds"] > 0


def test_tasks_are_processed_in_fifo_order(tmp_path: Path) -> None:
    with make_client(tmp_path, queue_delay_ms=300) as client:
        task_ids: list[str] = []
        for _ in range(3):
            response = client.post(
                "/v1/tasks",
                headers=task_auth_headers(client),
                json={
                    "type": "image_to_3d",
                    "input_url": upload_input_url(client),
                    "options": {"resolution": 1024},
                },
            )
            assert response.status_code == 201
            task_ids.append(response.json()["taskId"])

        completed = [wait_for_status(client, task_id, "succeeded") for task_id in task_ids]

    started_at = [payload["startedAt"] for payload in completed]
    assert started_at == sorted(started_at)


def test_sse_stream_replays_full_task_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        events = collect_sse_events(client, task_id)

    statuses = [event["status"] for event in events]
    assert statuses[0] == "queued"
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
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()
        assert payload["status"] == "queued"

        snapshots = collect_task_snapshots(
            client,
            payload["taskId"],
            terminal_status="succeeded",
        )
        artifacts_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts",
            headers=task_auth_headers(client),
        )
        download_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts/model.glb",
            headers=task_auth_headers(client),
        )
        metrics_response = client.get("/metrics", headers=metrics_headers(client))

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
    assert download_response.content.startswith(b"glTF")
    assert metrics_response.status_code == 200
    metrics_payload = metrics_response.text
    assert "queue_depth" in metrics_payload


def test_create_task_serves_preview_and_input_artifacts(
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

    with make_client(
        tmp_path,
        preview_renderer_service=StaticPreviewRendererService(),
    ) as client:
        upload_response = client.post(
            "/v1/upload",
            headers=task_auth_headers(client),
            files={"file": ("pixel.jpg", input_bytes, "image/jpeg")},
        )
        assert upload_response.status_code == 201

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_response.json()["url"],
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        final_payload = wait_for_status(client, task_id, "succeeded")
        preview_response = client.get(
            f"/v1/tasks/{task_id}/artifacts/preview.png",
            headers=task_auth_headers(client),
        )
        input_response = client.get(
            f"/v1/tasks/{task_id}/artifacts/input.png",
            headers=task_auth_headers(client),
        )

    artifact_names = [Path(artifact["url"]).name for artifact in final_payload["artifacts"]]
    assert artifact_names == ["model.glb", "preview.png", "input.png"]

    assert preview_response.status_code == 200
    assert preview_response.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert preview_response.headers["content-type"].startswith("image/png")

    assert input_response.status_code == 200
    assert input_response.content == input_bytes
    assert input_response.headers["content-type"].startswith("image/jpeg")


def test_preview_renderer_warmup_failure_does_not_break_startup_or_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_bytes = make_image_bytes("JPEG")
    preview_renderer_service = PreviewRendererService()

    async def failing_ensure_process_ready_locked(*, timeout_seconds: int) -> None:
        _ = timeout_seconds
        raise RuntimeError("warmup failed")

    monkeypatch.setattr(
        preview_renderer_service,
        "_ensure_process_ready_locked",
        failing_ensure_process_ready_locked,
    )

    with make_client(
        tmp_path,
        preview_renderer_service=preview_renderer_service,
    ) as client:
        upload_response = client.post(
            "/v1/upload",
            headers=task_auth_headers(client),
            files={"file": ("pixel.jpg", input_bytes, "image/jpeg")},
        )
        assert upload_response.status_code == 201

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_response.json()["url"],
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201

        final_payload = wait_for_status(client, create_response.json()["taskId"], "succeeded")

    artifact_names = [Path(artifact["url"]).name for artifact in final_payload["artifacts"]]
    assert artifact_names == ["model.glb", "input.png"]


def test_missing_preview_artifact_triggers_background_render_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_preview_render_state,
) -> None:
    task_id = "preview-missing-once"
    database_path = tmp_path / "app.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    seed_tasks(database_path, [make_succeeded_sequence(task_id)])
    task_dir = artifacts_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    task_dir.joinpath("model.glb").write_bytes(b"glTF-preview")

    preview_bytes = make_image_bytes("PNG")
    render_started = threading.Event()
    render_release = threading.Event()
    render_finished = threading.Event()

    class BlockingPreviewRendererService:
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
            render_started.set()
            await asyncio.to_thread(render_release.wait, 1.0)
            render_finished.set()
            return preview_bytes

    try:
        with make_client(
            tmp_path,
            database_path=database_path,
            artifacts_dir=artifacts_dir,
            preview_renderer_service=BlockingPreviewRendererService(),
        ) as client:
            create_task_calls = 0
            original_create_task = server_module.asyncio.create_task

            def counting_create_task(coro, *args, **kwargs):
                nonlocal create_task_calls
                coro_name = getattr(getattr(coro, "cr_code", None), "co_name", "")
                if coro_name == "_render_preview_artifact_on_demand":
                    create_task_calls += 1
                return original_create_task(coro, *args, **kwargs)

            monkeypatch.setattr(server_module.asyncio, "create_task", counting_create_task)

            response = client.get(
                f"/v1/tasks/{task_id}/artifacts/preview.png",
                headers=task_auth_headers(client),
            )
            assert response.status_code == 404
            wait_for_condition(render_started.is_set, timeout_seconds=1.0)
            assert task_id in server_module._preview_rendering

            render_release.set()
            wait_for_condition(render_finished.is_set, timeout_seconds=1.0)
            wait_for_condition(
                lambda: task_id not in server_module._preview_rendering,
                timeout_seconds=1.0,
            )
            assert create_task_calls == 1
    finally:
        render_release.set()


def test_missing_preview_artifact_deduplicates_background_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_preview_render_state,
) -> None:
    task_id = "preview-missing-dedup"
    database_path = tmp_path / "app.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    seed_tasks(database_path, [make_succeeded_sequence(task_id)])
    task_dir = artifacts_dir / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    task_dir.joinpath("model.glb").write_bytes(b"glTF-preview")

    preview_bytes = make_image_bytes("PNG")
    render_started = threading.Event()
    render_release = threading.Event()
    render_finished = threading.Event()

    class BlockingPreviewRendererService:
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
            render_started.set()
            await asyncio.to_thread(render_release.wait, 1.0)
            render_finished.set()
            return preview_bytes

    try:
        with make_client(
            tmp_path,
            database_path=database_path,
            artifacts_dir=artifacts_dir,
            preview_renderer_service=BlockingPreviewRendererService(),
        ) as client:
            create_task_calls = 0
            original_create_task = server_module.asyncio.create_task

            def counting_create_task(coro, *args, **kwargs):
                nonlocal create_task_calls
                coro_name = getattr(getattr(coro, "cr_code", None), "co_name", "")
                if coro_name == "_render_preview_artifact_on_demand":
                    create_task_calls += 1
                return original_create_task(coro, *args, **kwargs)

            monkeypatch.setattr(server_module.asyncio, "create_task", counting_create_task)

            first_response = client.get(
                f"/v1/tasks/{task_id}/artifacts/preview.png",
                headers=task_auth_headers(client),
            )
            second_response = client.get(
                f"/v1/tasks/{task_id}/artifacts/preview.png",
                headers=task_auth_headers(client),
            )

            assert first_response.status_code == 404
            assert second_response.status_code == 404
            assert create_task_calls == 1
            assert task_id in server_module._preview_rendering

            wait_for_condition(render_started.is_set, timeout_seconds=1.0)
            render_release.set()
            wait_for_condition(render_finished.is_set, timeout_seconds=1.0)
            wait_for_condition(
                lambda: task_id not in server_module._preview_rendering,
                timeout_seconds=1.0,
            )
    finally:
        render_release.set()


def test_missing_preview_and_model_does_not_trigger_background_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reset_preview_render_state,
) -> None:
    task_id = "preview-missing-no-model"
    database_path = tmp_path / "app.sqlite3"
    artifacts_dir = tmp_path / "artifacts"
    seed_tasks(database_path, [make_succeeded_sequence(task_id)])

    with make_client(
        tmp_path,
        database_path=database_path,
        artifacts_dir=artifacts_dir,
    ) as client:
        create_task_calls = 0
        original_create_task = server_module.asyncio.create_task

        def counting_create_task(coro, *args, **kwargs):
            nonlocal create_task_calls
            coro_name = getattr(getattr(coro, "cr_code", None), "co_name", "")
            if coro_name == "_render_preview_artifact_on_demand":
                create_task_calls += 1
            return original_create_task(coro, *args, **kwargs)

        monkeypatch.setattr(server_module.asyncio, "create_task", counting_create_task)

        response = client.get(
            f"/v1/tasks/{task_id}/artifacts/preview.png",
            headers=task_auth_headers(client),
        )

    assert response.status_code == 404
    assert create_task_calls == 0
    assert task_id not in server_module._preview_rendering


def test_create_task_downloads_artifact_via_same_origin_proxy_for_minio_backend(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeObjectStoreClient:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], dict[str, object]] = {}

        def ensure_bucket_exists(self, bucket: str) -> None:
            _ = bucket

        def upload_file(
            self,
            *,
            bucket: str,
            key: str,
            source_path: Path,
            content_type: str | None = None,
        ) -> None:
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
            _ = expires_in_seconds
            return f"https://artifacts.example.com/{bucket}/{key}?signature=fake"

        def download_file(
            self,
            *,
            bucket: str,
            key: str,
            destination_path: Path,
        ) -> None:
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            stored = self.objects[(bucket, key)]
            body = stored["body"]
            assert isinstance(body, bytes)
            destination_path.write_bytes(body)

        def get_object_stream(
            self,
            *,
            bucket: str,
            key: str,
        ) -> ObjectStorageStreamResult:
            stored = self.objects[(bucket, key)]
            body = stored["body"]
            assert isinstance(body, bytes)

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

            content_type = stored.get("content_type")
            return ObjectStorageStreamResult(
                body=MemoryStream(body),
                content_type=content_type if isinstance(content_type, str) else None,
                content_length=len(body),
                etag='"fake-etag"',
            )

        def list_object_keys(
            self,
            *,
            bucket: str,
            prefix: str,
        ) -> list[str]:
            return [
                key
                for stored_bucket, key in self.objects
                if stored_bucket == bucket and key.startswith(prefix)
            ]

        def delete_objects(
            self,
            *,
            bucket: str,
            keys: list[str],
        ) -> None:
            for key in keys:
                self.objects.pop((bucket, key), None)

    fake_object_store_client = FakeObjectStoreClient()
    monkeypatch.setattr(
        server_module,
        "build_boto3_object_storage_client",
        lambda **_: fake_object_store_client,
    )

    with make_client(
        tmp_path,
        artifact_store_mode="minio",
        object_store_endpoint="http://minio:9000",
        object_store_bucket="artifacts",
        object_store_access_key="minioadmin",
        object_store_secret_key="minioadmin",
    ) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()

        snapshots = collect_task_snapshots(
            client,
            payload["taskId"],
            terminal_status="succeeded",
        )
        download_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts/model.glb",
            headers=task_auth_headers(client),
        )

    final_payload = snapshots[-1]
    assert final_payload["artifacts"][0]["backend"] == "minio"
    assert final_payload["artifacts"][0]["url"].startswith("https://artifacts.example.com/")
    assert download_response.status_code == 200
    assert download_response.content.startswith(b"glTF")
    assert download_response.headers["etag"] == '"fake-etag"'
    assert int(download_response.headers["content-length"]) >= 4


def test_minio_artifact_proxy_streams_without_buffering_temp_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StreamingOnlyObjectStoreClient:
        def __init__(self) -> None:
            self.objects: dict[tuple[str, str], bytes] = {}
            self.download_file_called = False
            self.stream_opened = False

        def ensure_bucket_exists(self, bucket: str) -> None:
            _ = bucket

        def upload_file(
            self,
            *,
            bucket: str,
            key: str,
            source_path: Path,
            content_type: str | None = None,
        ) -> None:
            _ = content_type
            self.objects[(bucket, key)] = source_path.read_bytes()

        def generate_presigned_get_url(
            self,
            *,
            bucket: str,
            key: str,
            expires_in_seconds: int,
        ) -> str:
            _ = expires_in_seconds
            return f"https://artifacts.example.com/{bucket}/{key}?signature=fake"

        def download_file(
            self,
            *,
            bucket: str,
            key: str,
            destination_path: Path,
        ) -> None:
            _ = bucket
            _ = key
            _ = destination_path
            self.download_file_called = True
            raise AssertionError("download_file should not be called for streamed proxy downloads")

        def get_object_stream(
            self,
            *,
            bucket: str,
            key: str,
        ) -> ObjectStorageStreamResult:
            _ = bucket
            payload = self.objects[(bucket, key)]
            self.stream_opened = True

            class ChunkedStream:
                def __init__(self, chunks: list[bytes]) -> None:
                    self._chunks = chunks

                def read(self, amount: int = -1) -> bytes:
                    _ = amount
                    if not self._chunks:
                        return b""
                    return self._chunks.pop(0)

                def close(self) -> None:
                    return

            return ObjectStorageStreamResult(
                body=ChunkedStream([payload[:2], payload[2:]]),
                content_type="model/gltf-binary",
                content_length=len(payload),
                etag='"stream-etag"',
            )

        def list_object_keys(
            self,
            *,
            bucket: str,
            prefix: str,
        ) -> list[str]:
            return [
                key
                for stored_bucket, key in self.objects
                if stored_bucket == bucket and key.startswith(prefix)
            ]

        def delete_objects(
            self,
            *,
            bucket: str,
            keys: list[str],
        ) -> None:
            for key in keys:
                self.objects.pop((bucket, key), None)

    fake_object_store_client = StreamingOnlyObjectStoreClient()
    monkeypatch.setattr(
        server_module,
        "build_boto3_object_storage_client",
        lambda **_: fake_object_store_client,
    )

    with make_client(
        tmp_path,
        artifact_store_mode="minio",
        object_store_endpoint="http://minio:9000",
        object_store_bucket="artifacts",
        object_store_access_key="minioadmin",
        object_store_secret_key="minioadmin",
    ) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        payload = create_response.json()

        collect_task_snapshots(
            client,
            payload["taskId"],
            terminal_status="succeeded",
        )
        download_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts/model.glb",
            headers=task_auth_headers(client),
        )

    assert download_response.status_code == 200
    assert download_response.content.startswith(b"glTF")
    assert download_response.headers["etag"] == '"stream-etag"'
    assert fake_object_store_client.stream_opened is True
    assert fake_object_store_client.download_file_called is False


def test_metrics_track_successful_task(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        initial_metrics_payload = fetch_metrics_payload(client)
        succeeded_total_before = metric_sample_value(
            initial_metrics_payload,
            "task_total",
            {"status": "succeeded"},
        )
        succeeded_duration_count_before = metric_sample_value(
            initial_metrics_payload,
            "task_duration_seconds_count",
            {"status": "succeeded"},
        )
        preprocess_count_before = metric_sample_value(
            initial_metrics_payload,
            "stage_duration_seconds_count",
            {"stage": "preprocess"},
        )
        gpu_count_before = metric_sample_value(
            initial_metrics_payload,
            "stage_duration_seconds_count",
            {"stage": "gpu"},
        )
        export_count_before = metric_sample_value(
            initial_metrics_payload,
            "stage_duration_seconds_count",
            {"stage": "export"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        wait_for_status(
            client,
            create_response.json()["taskId"],
            "succeeded",
            timeout_seconds=5.0,
        )

        assert (
            wait_for_metric_sample(
                client,
                "task_total",
                labels={"status": "succeeded"},
                minimum_value=succeeded_total_before + 1,
            )
            >= succeeded_total_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "task_duration_seconds_count",
                labels={"status": "succeeded"},
                minimum_value=succeeded_duration_count_before + 1,
            )
            >= succeeded_duration_count_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "stage_duration_seconds_count",
                labels={"stage": "preprocess"},
                minimum_value=preprocess_count_before + 1,
            )
            >= preprocess_count_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "stage_duration_seconds_count",
                labels={"stage": "gpu"},
                minimum_value=gpu_count_before + 1,
            )
            >= gpu_count_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "stage_duration_seconds_count",
                labels={"stage": "export"},
                minimum_value=export_count_before + 1,
            )
            >= export_count_before + 1
        )


def test_metrics_track_failed_task(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        initial_metrics_payload = fetch_metrics_payload(client)
        failed_total_before = metric_sample_value(
            initial_metrics_payload,
            "task_total",
            {"status": "failed"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {
                    "resolution": 1024,
                    "mock_failure_stage": "preprocessing",
                },
            },
        )
        assert create_response.status_code == 201
        failed_payload = wait_for_status(client, create_response.json()["taskId"], "failed")

        assert failed_payload["currentStage"] == "preprocessing"
        assert (
            wait_for_metric_sample(
                client,
                "task_total",
                labels={"status": "failed"},
                minimum_value=failed_total_before + 1,
            )
            >= failed_total_before + 1
        )


def test_metrics_track_webhook(tmp_path: Path) -> None:
    webhook_calls: list[tuple[str, dict]] = []

    async def webhook_sender(callback_url: str, payload: dict) -> None:
        webhook_calls.append((callback_url, payload))

    with make_client(tmp_path, webhook_sender=webhook_sender) as client:
        initial_metrics_payload = fetch_metrics_payload(client)
        webhook_success_before = metric_sample_value(
            initial_metrics_payload,
            "webhook_total",
            {"result": "success"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "callback_url": "https://callback.test/metrics",
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        wait_for_status(client, create_response.json()["taskId"], "succeeded")

        wait_for_condition(lambda: len(webhook_calls) == 1, timeout_seconds=2.0)
        assert (
            wait_for_metric_sample(
                client,
                "webhook_total",
                labels={"result": "success"},
                minimum_value=webhook_success_before + 1,
            )
            >= webhook_success_before + 1
        )


def test_create_task_with_existing_idempotency_key_returns_http_200(tmp_path: Path) -> None:
    with make_client(tmp_path, queue_delay_ms=300) as client:
        first_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "idempotency_key": "same-task",
                "options": {"resolution": 1024},
            },
        )
        second_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "idempotency_key": "same-task",
                "options": {"resolution": 1024},
            },
        )

        wait_for_status(client, first_response.json()["taskId"], "succeeded")

    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert second_response.json()["taskId"] == first_response.json()["taskId"]


def test_webhook_failures_are_retried_and_recorded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "app.sqlite3"
    attempts: list[str] = []

    async def failing_webhook_sender(callback_url: str, payload: dict) -> None:
        attempts.append(callback_url)
        raise RuntimeError(f"webhook boom {len(attempts)}")

    async def no_op_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(async_engine_module.asyncio, "sleep", no_op_sleep)

    with make_client(
        tmp_path,
        webhook_sender=failing_webhook_sender,
        webhook_max_retries=2,
        database_path=database_path,
    ) as client:
        initial_metrics_payload = fetch_metrics_payload(client)
        webhook_failure_before = metric_sample_value(
            initial_metrics_payload,
            "webhook_total",
            {"result": "failure"},
        )
        webhook_success_before = metric_sample_value(
            initial_metrics_payload,
            "webhook_total",
            {"result": "success"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "callback_url": "https://callback.test/retry",
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        wait_for_status(client, task_id, "succeeded")
        wait_for_condition(lambda: len(attempts) == 3, timeout_seconds=2.0)

        assert (
            wait_for_metric_sample(
                client,
                "webhook_total",
                labels={"result": "failure"},
                minimum_value=webhook_failure_before + 3,
            )
            >= webhook_failure_before + 3
        )
        webhook_success_after = metric_sample_value(
            fetch_metrics_payload(client),
            "webhook_total",
            {"result": "success"},
        )

    assert attempts == [
        "https://callback.test/retry",
        "https://callback.test/retry",
        "https://callback.test/retry",
    ]
    assert webhook_success_after == webhook_success_before

    events = read_task_events(database_path, task_id)
    webhook_events = [event for event in events if event["event"].startswith("webhook_")]
    assert [event["event"] for event in webhook_events] == [
        "webhook_retry",
        "webhook_retry",
        "webhook_failed",
    ]
    assert webhook_events[-1]["metadata"]["attempts"] == 3
    assert webhook_events[-1]["metadata"]["error"] == "webhook boom 3"
    assert "webhook boom 3" in webhook_events[-1]["metadata"]["message"]


def test_create_task_returns_503_when_queue_is_full(tmp_path: Path) -> None:
    with make_client(
        tmp_path,
        queue_delay_ms=300,
        queue_max_size=1,
    ) as client:
        first_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        second_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        third_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )

        wait_for_status(client, first_response.json()["taskId"], "succeeded")
        wait_for_status(client, second_response.json()["taskId"], "succeeded")

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert third_response.status_code == 503
    assert third_response.json()["detail"]["code"] == "queue_full"


def test_single_gpu_default_configuration_exposes_slot_metric(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201

        wait_for_status(client, create_response.json()["taskId"], "succeeded")
        metrics_payload = fetch_metrics_payload(client)

    assert "gpu_slot_active" in metrics_payload
    assert 'gpu_slot_active{device="0"}' in metrics_payload


def test_gpu_queued_task_can_be_cancelled_and_repeat_cancel_is_rejected(tmp_path: Path) -> None:
    with make_client(
        tmp_path,
        queue_delay_ms=300,
        rate_limit_concurrent=1,
        rate_limit_per_hour=3,
    ) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        task_id = create_response.json()["taskId"]

        queued_payload = wait_for_status(client, task_id, "gpu_queued")
        assert queued_payload["status"] == "gpu_queued"

        concurrent_limit_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        cancel_response = client.post(f"/v1/tasks/{task_id}/cancel", headers=task_auth_headers(client))
        assert cancel_response.status_code == 200
        assert cancel_response.json()["status"] == "cancelled"

        second_cancel_response = client.post(
            f"/v1/tasks/{task_id}/cancel",
            headers=task_auth_headers(client),
        )
        final_task_response = client.get(f"/v1/tasks/{task_id}", headers=task_auth_headers(client))
        artifacts_response = client.get(
            f"/v1/tasks/{task_id}/artifacts",
            headers=task_auth_headers(client),
        )
        after_cancel_create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert after_cancel_create_response.status_code == 201
        wait_for_status(client, after_cancel_create_response.json()["taskId"], "succeeded")
        hourly_limit_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
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
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
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
            headers=task_auth_headers(client),
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
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
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
            headers=task_auth_headers(client),
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
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "callback_url": "https://callback.test/success",
                "options": {"resolution": 1024},
            },
        )
        failed_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
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
        wait_for_condition(lambda: len(webhook_calls) == 2, timeout_seconds=2.0)

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
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": "data:text/plain;base64,Zm9v",
                "options": {"resolution": 1024},
            },
        )
    assert create_response.status_code == 400
    assert "input_url must start with upload://" in create_response.json()["detail"]

    with make_real_mode_client(
        tmp_path,
        monkeypatch,
        allowed_callback_domains=("callback.test",),
    ) as real_client:
        uploaded_input_url = upload_input_url(real_client)
        file_url_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "input_url": "file:///tmp/input.png",
                "options": {"resolution": 1024},
            },
        )
        invalid_callback_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "input_url": uploaded_input_url,
                "callback_url": "ftp://callback.test/task",
                "options": {"resolution": 1024},
            },
        )
        disallowed_callback_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "input_url": uploaded_input_url,
                "callback_url": "https://evil.test/task",
                "options": {"resolution": 1024},
            },
        )
        allowed_callback_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "input_url": uploaded_input_url,
                "callback_url": "https://callback.test/task",
                "options": {"resolution": 1024},
            },
        )

    assert file_url_response.status_code == 400
    assert "input_url must start with upload://" in file_url_response.json()["detail"]
    assert invalid_callback_response.status_code == 422
    assert "callback_url must use http:// or https://" in invalid_callback_response.json()["detail"]
    assert disallowed_callback_response.status_code == 422
    assert "ALLOWED_CALLBACK_DOMAINS" in disallowed_callback_response.json()["detail"]
    assert allowed_callback_response.status_code == 201


def test_real_mode_model_load_failure_marks_task_failed_without_blocking_startup(
    tmp_path: Path,
) -> None:
    async def configure_default_model() -> None:
        store = ModelStore(tmp_path / "app.sqlite3")
        await store.initialize()
        await store.update_model(
            "trellis2",
            model_path=str(tmp_path / "missing-model"),
        )
        await store.close()

    asyncio.run(configure_default_model())

    config = ServingConfig(
        provider_mode="real",
        admin_token="admin-token",
        database_path=tmp_path / "app.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
        uploads_dir=tmp_path / "uploads",
    )
    app = create_test_app(config)

    with TestClient(app) as client:
        readiness_before = client.get("/readiness")
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "input_url": upload_input_url(client),
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        failed_payload = wait_for_status(client, create_response.json()["taskId"], "failed")
        readiness_after = client.get("/readiness")

    assert readiness_before.status_code == 503
    assert readiness_after.status_code == 503
    assert "failed to load" in failed_payload["error"]["message"]


def test_trellis2_provider_resolves_existing_local_model_path(tmp_path: Path) -> None:
    model_dir = tmp_path / "trellis2-model"
    model_dir.mkdir(parents=True)
    source_type, model_reference = Trellis2Provider._resolve_model_reference(
        str(model_dir)
    )
    assert source_type == "local"
    assert model_reference == str(model_dir.resolve())


def test_trellis2_provider_rejects_missing_non_local_model_path() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match="Use Admin to download first",
    ):
        Trellis2Provider._resolve_model_reference("microsoft/TRELLIS.2-4B")


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


@pytest.mark.anyio
async def test_trellis2_provider_run_batch_moves_mesh_tensors_to_cpu() -> None:
    class FakeTensor:
        def __init__(self, device_type: str) -> None:
            self.device = types.SimpleNamespace(type=device_type)

        @property
        def is_cuda(self) -> bool:
            return self.device.type == "cuda"

        def detach(self):
            return self

        def cpu(self):
            return FakeTensor("cpu")

    class FakeMesh:
        def __init__(self) -> None:
            self.vertices = FakeTensor("cuda")
            self.faces = FakeTensor("cuda")
            self.coords = FakeTensor("cuda")
            self.attrs = FakeTensor("cuda")
            self.layout = {"nested": FakeTensor("cuda")}

    class FakePipeline:
        def run(self, image, **kwargs):
            _ = image
            _ = kwargs
            return [FakeMesh()]

    provider = Trellis2Provider(
        pipeline=FakePipeline(),
        model_path="microsoft/TRELLIS.2-4B",
    )

    results = await provider.run_batch(images=[{"image": "stub"}], options={})

    assert len(results) == 1
    mesh = results[0].mesh
    assert mesh.vertices.device.type == "cpu"
    assert mesh.faces.device.type == "cpu"
    assert mesh.coords.device.type == "cpu"
    assert mesh.attrs.device.type == "cpu"
    assert mesh.layout["nested"].device.type == "cpu"


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


def test_build_provider_uses_trellis2_metadata_only_in_real_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeTrellis2Provider:
        @classmethod
        def metadata_only(cls, model_path: str):
            observed["metadata_only_model_path"] = model_path
            return {"provider": "trellis2", "mode": "metadata_only"}

        @classmethod
        def from_pretrained(cls, model_path: str):
            raise AssertionError(f"from_pretrained should not be called: {model_path}")

    monkeypatch.setattr(server_module, "Trellis2Provider", FakeTrellis2Provider)

    provider = server_module.build_provider(
        provider_name="trellis2",
        provider_mode="real",
        model_path="microsoft/TRELLIS.2-4B",
        mock_delay_ms=60,
    )

    assert provider == {"provider": "trellis2", "mode": "metadata_only"}
    assert observed["metadata_only_model_path"] == "microsoft/TRELLIS.2-4B"


def test_real_mode_preflight_requires_provider_mode_real(tmp_path: Path) -> None:
    config = ServingConfig(
        provider_mode="mock",
        database_path=tmp_path / "app.sqlite3",
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

    async def configure_default_model() -> None:
        store = ModelStore(tmp_path / "app.sqlite3")
        await store.initialize()
        await store.update_model(
            "trellis2",
            model_path=str(model_dir),
        )
        await store.close()

    asyncio.run(configure_default_model())

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
        artifact_store_mode="local",
        database_path=tmp_path / "app.sqlite3",
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


# ---------------------------------------------------------------------------
# HunYuan3D provider tests
# ---------------------------------------------------------------------------


def test_hunyuan3d_provider_resolves_existing_local_model_path(tmp_path: Path) -> None:
    model_dir = tmp_path / "hunyuan3d-model"
    model_dir.mkdir(parents=True)
    source_type, model_reference = Hunyuan3DProvider._resolve_model_reference(
        str(model_dir)
    )

    assert source_type == "local"
    assert model_reference == str(model_dir.resolve())


def test_hunyuan3d_provider_rejects_missing_non_local_model_path() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match="Use Admin to download first",
    ):
        Hunyuan3DProvider._resolve_model_reference("tencent/Hunyuan3D-2")


def test_hunyuan3d_provider_run_single_uses_correct_kwargs() -> None:
    observed: dict[str, object] = {}

    class FakeShapePipeline:
        def __call__(self, **kwargs):
            observed["shape_kwargs"] = kwargs
            return ["raw_mesh"]

    class FakeTexturePipeline:
        def __call__(self, mesh, image):
            observed["texture_mesh_input"] = mesh
            observed["texture_image_input"] = image
            return "textured_mesh"

    provider = Hunyuan3DProvider(
        shape_pipeline=FakeShapePipeline(),
        texture_pipeline=FakeTexturePipeline(),
        model_path="tencent/Hunyuan3D-2",
    )

    result = provider._run_single(
        image="image-object",
        options={
            "num_steps": 30,
            "guidance_scale": 6.0,
            "octree_resolution": 128,
            "texture_steps": 10,
        },
    )

    assert result == "textured_mesh"
    assert observed["shape_kwargs"] == {
        "image": "image-object",
        "num_inference_steps": 30,
        "guidance_scale": 6.0,
        "octree_resolution": 128,
    }
    assert observed["texture_mesh_input"] == "raw_mesh"
    assert observed["texture_image_input"] == "image-object"


def test_hunyuan3d_provider_run_single_skips_texture_when_none() -> None:
    class FakeShapePipeline:
        def __call__(self, **kwargs):
            return ["shape_mesh"]

    provider = Hunyuan3DProvider(
        shape_pipeline=FakeShapePipeline(),
        texture_pipeline=None,
        model_path="tencent/Hunyuan3D-2",
    )

    result = provider._run_single(image="img", options={})

    assert result == "shape_mesh"


def test_hunyuan3d_provider_export_glb_calls_mesh_export(tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    class FakeMesh:
        def export(self, path: str) -> None:
            observed["export_path"] = path

    provider = Hunyuan3DProvider(
        shape_pipeline=object(),
        texture_pipeline=None,
        model_path="tencent/Hunyuan3D-2",
    )

    output = tmp_path / "model.glb"
    provider.export_glb(GenerationResult(mesh=FakeMesh()), output, {})

    assert observed["export_path"] == str(output)


def test_hunyuan3d_mock_provider_emits_canonical_stages() -> None:
    mock = MockHunyuan3DProvider(stage_delay_ms=0)

    assert mock.stages == [
        {"name": "ss", "weight": 0.20},
        {"name": "shape", "weight": 0.45},
        {"name": "material", "weight": 0.35},
    ]


@pytest.mark.anyio
async def test_hunyuan3d_mock_provider_run_batch_returns_results() -> None:
    mock = MockHunyuan3DProvider(stage_delay_ms=0)
    stages_seen: list[str] = []

    async def progress_cb(progress):
        stages_seen.append(progress.stage_name)

    results = await mock.run_batch(
        images=["img1"],
        options={"resolution": 512},
        progress_cb=progress_cb,
    )

    assert len(results) == 1
    assert results[0].metadata["mock"] is True
    assert results[0].metadata["provider"] == "hunyuan3d"
    assert stages_seen == ["ss", "shape", "material"]


@pytest.mark.anyio
async def test_hunyuan3d_mock_provider_failure_injection() -> None:
    mock = MockHunyuan3DProvider(stage_delay_ms=0)

    with pytest.raises(ModelProviderExecutionError, match="gpu_shape"):
        await mock.run_batch(
            images=["img"],
            options={"mock_failure_stage": "gpu_shape"},
        )


def test_hunyuan3d_mock_provider_export_glb_writes_valid_file(tmp_path: Path) -> None:
    mock = MockHunyuan3DProvider()
    output = tmp_path / "mock.glb"
    mock.export_glb(GenerationResult(mesh=None), output, {})

    data = output.read_bytes()
    assert data[:4] == b"glTF"


def test_build_provider_supports_hunyuan3d_mock(tmp_path: Path) -> None:
    del tmp_path
    provider = server_module.build_provider(
        provider_name="hunyuan3d",
        provider_mode="mock",
        model_path="tencent/Hunyuan3D-2",
        mock_delay_ms=60,
    )
    assert isinstance(provider, MockHunyuan3DProvider)


def test_build_provider_uses_hunyuan3d_metadata_only_in_real_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeHunyuan3DProvider:
        @classmethod
        def metadata_only(cls, model_path: str):
            observed["metadata_only_model_path"] = model_path
            return {"provider": "hunyuan3d", "mode": "metadata_only"}

        @classmethod
        def from_pretrained(cls, model_path: str):
            raise AssertionError(f"from_pretrained should not be called: {model_path}")

    monkeypatch.setattr(server_module, "Hunyuan3DProvider", FakeHunyuan3DProvider)

    provider = server_module.build_provider(
        provider_name="hunyuan3d",
        provider_mode="real",
        model_path="tencent/Hunyuan3D-2",
        mock_delay_ms=60,
    )

    assert provider == {"provider": "hunyuan3d", "mode": "metadata_only"}
    assert observed["metadata_only_model_path"] == "tencent/Hunyuan3D-2"


# ---------------------------------------------------------------------------
# Step1X-3D provider tests
# ---------------------------------------------------------------------------


def _import_step1x3d_geometry_pipeline_module_with_test_stubs(
    monkeypatch: pytest.MonkeyPatch,
):
    module_name = (
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.pipelines.pipeline"
    )
    sys.modules.pop(module_name, None)

    def register(module_path: str, module: types.ModuleType) -> None:
        monkeypatch.setitem(sys.modules, module_path, module)

    def register_package(module_path: str, package_path: Path) -> None:
        package = types.ModuleType(module_path)
        package.__path__ = [str(package_path)]
        register(module_path, package)

    geometry_root = (
        WORKSPACE_ROOT / "gen3d" / "model" / "step1x3d" / "pipeline" / "step1x3d_geometry"
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry",
        geometry_root,
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models",
        geometry_root / "models",
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.pipelines",
        geometry_root / "models" / "pipelines",
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.autoencoders",
        geometry_root / "models" / "autoencoders",
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.conditional_encoders",
        geometry_root / "models" / "conditional_encoders",
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.transformers",
        geometry_root / "models" / "transformers",
    )

    class _NoGradContext:
        def __call__(self, fn=None):
            if fn is None:
                return self
            return fn

        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    class _FakeTensor:
        def __init__(
            self,
            *,
            dtype: str = "float16",
            shape: tuple[int, ...] = (1,),
            name: str = "tensor",
        ) -> None:
            self.dtype = dtype
            self.shape = shape
            self.name = name

        def to(self, *args, **kwargs):
            dtype = kwargs.get("dtype")
            if dtype is None and args and hasattr(args[0], "dtype"):
                dtype = getattr(args[0], "dtype")
            if dtype is None:
                return self
            return _FakeTensor(dtype=dtype, shape=self.shape, name=self.name)

        def expand(self, dim0: int):
            return _FakeTensor(dtype=self.dtype, shape=(dim0,), name=self.name)

        def chunk(self, chunks: int):
            return tuple(
                _FakeTensor(dtype=self.dtype, shape=self.shape, name=f"{self.name}_{i}")
                for i in range(chunks)
            )

        def __mul__(self, other):
            _ = other
            return _FakeTensor(dtype=self.dtype, shape=self.shape, name=self.name)

        def __add__(self, other):
            _ = other
            return _FakeTensor(dtype=self.dtype, shape=self.shape, name=self.name)

        def __sub__(self, other):
            _ = other
            return _FakeTensor(dtype=self.dtype, shape=self.shape, name=self.name)

    class _FakeTimestep:
        def expand(self, dim0: int):
            return _FakeTensor(dtype="int64", shape=(dim0,), name="timestep")

    fake_torch = types.ModuleType("torch")
    fake_torch.Tensor = _FakeTensor
    fake_torch.FloatTensor = _FakeTensor
    fake_torch.no_grad = lambda: _NoGradContext()
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake_torch.bfloat16 = "bfloat16"
    fake_torch.float16 = "float16"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)

    def _cat(tensors, dim=0):
        _ = dim
        head = tensors[0]
        first_dim = sum(
            (tensor.shape[0] if getattr(tensor, "shape", ()) else 1) for tensor in tensors
        )
        shape_tail = tuple(head.shape[1:]) if len(head.shape) > 1 else tuple()
        return _FakeTensor(dtype=head.dtype, shape=(first_dim, *shape_tail), name="cat")

    fake_torch.cat = _cat
    register("torch", fake_torch)

    fake_pil = types.ModuleType("PIL")
    fake_pil_image = types.ModuleType("PIL.Image")

    class _PILImage:
        pass

    fake_pil_image.Image = _PILImage
    fake_pil_image.open = lambda *args, **kwargs: _PILImage()
    fake_pil.Image = fake_pil_image
    register("PIL", fake_pil)
    register("PIL.Image", fake_pil_image)

    fake_trimesh = types.ModuleType("trimesh")
    fake_trimesh.Trimesh = object
    register("trimesh", fake_trimesh)
    register("rembg", types.ModuleType("rembg"))

    fake_hf_hub = types.ModuleType("huggingface_hub")
    fake_hf_hub.hf_hub_download = lambda *args, **kwargs: "stub-model"
    register("huggingface_hub", fake_hf_hub)

    fake_diffusers = types.ModuleType("diffusers")
    fake_diffusers.__path__ = []
    register("diffusers", fake_diffusers)

    fake_diffusers_schedulers = types.ModuleType("diffusers.schedulers")

    class _FlowMatchEulerDiscreteScheduler:
        pass

    fake_diffusers_schedulers.FlowMatchEulerDiscreteScheduler = (
        _FlowMatchEulerDiscreteScheduler
    )
    register("diffusers.schedulers", fake_diffusers_schedulers)

    fake_diffusers_utils = types.ModuleType("diffusers.utils")

    class _BaseOutput:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    fake_diffusers_utils.BaseOutput = _BaseOutput
    register("diffusers.utils", fake_diffusers_utils)

    fake_diffusers_torch_utils = types.ModuleType("diffusers.utils.torch_utils")
    fake_diffusers_torch_utils.randn_tensor = (
        lambda shape, generator=None, device=None, dtype=None: _FakeTensor(
            dtype=dtype or "float16",
            shape=shape,
            name="randn",
        )
    )
    register("diffusers.utils.torch_utils", fake_diffusers_torch_utils)

    fake_diffusers_pipeline_utils = types.ModuleType("diffusers.pipelines.pipeline_utils")

    class _DiffusionPipeline:
        def register_modules(self, **kwargs) -> None:
            for name, value in kwargs.items():
                setattr(self, name, value)

    fake_diffusers_pipeline_utils.DiffusionPipeline = _DiffusionPipeline
    register("diffusers.pipelines.pipeline_utils", fake_diffusers_pipeline_utils)

    fake_diffusers_loaders = types.ModuleType("diffusers.loaders")

    class _LoaderMixin:
        pass

    fake_diffusers_loaders.FluxIPAdapterMixin = _LoaderMixin
    fake_diffusers_loaders.FluxLoraLoaderMixin = _LoaderMixin
    fake_diffusers_loaders.FromSingleFileMixin = _LoaderMixin
    fake_diffusers_loaders.TextualInversionLoaderMixin = _LoaderMixin
    register("diffusers.loaders", fake_diffusers_loaders)

    fake_pipeline_utils = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.pipelines.pipeline_utils"
    )

    class _TransformerDiffusionMixin:
        pass

    fake_pipeline_utils.TransformerDiffusionMixin = _TransformerDiffusionMixin
    fake_pipeline_utils.preprocess_image = lambda image, **kwargs: image
    fake_pipeline_utils.retrieve_timesteps = (
        lambda scheduler, num_inference_steps, device, timesteps: (
            timesteps or [_FakeTimestep()],
            len(timesteps or [_FakeTimestep()]),
        )
    )
    fake_pipeline_utils.remove_floater = lambda mesh: mesh
    fake_pipeline_utils.remove_degenerate_face = lambda mesh: mesh
    fake_pipeline_utils.reduce_face = lambda mesh, max_facenum: mesh
    fake_pipeline_utils.smart_load_model = lambda model_path, subfolder=None: model_path
    register(fake_pipeline_utils.__name__, fake_pipeline_utils)

    fake_transformers = types.ModuleType("transformers")

    class _BitImageProcessor:
        pass

    fake_transformers.BitImageProcessor = _BitImageProcessor
    register("transformers", fake_transformers)

    fake_surface_extractors = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.autoencoders.surface_extractors"
    )
    fake_surface_extractors.MeshExtractResult = object
    register(fake_surface_extractors.__name__, fake_surface_extractors)

    fake_autoencoder = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.autoencoders.michelangelo_autoencoder"
    )
    fake_autoencoder.MichelangeloAutoencoder = object
    register(fake_autoencoder.__name__, fake_autoencoder)

    fake_dinov2 = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.conditional_encoders.dinov2_encoder"
    )
    fake_dinov2.Dinov2Encoder = object
    register(fake_dinov2.__name__, fake_dinov2)

    fake_t5 = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.conditional_encoders.t5_encoder"
    )
    fake_t5.T5Encoder = object
    register(fake_t5.__name__, fake_t5)

    fake_label = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.conditional_encoders.label_encoder"
    )
    fake_label.LabelEncoder = object
    register(fake_label.__name__, fake_label)

    fake_flux = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.transformers.flux_transformer_1d"
    )
    fake_flux.FluxDenoiser = object
    register(fake_flux.__name__, fake_flux)

    fake_config = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.utils.config"
    )
    fake_config.ExperimentConfig = object
    fake_config.load_config = lambda *args, **kwargs: None
    register(fake_config.__name__, fake_config)

    return importlib.import_module(module_name)


def _import_step1x3d_texture_pipeline_module_with_test_stubs(
    monkeypatch: pytest.MonkeyPatch,
):
    module_name = (
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.pipelines."
        "step1x_3d_texture_synthesis_pipeline"
    )
    sys.modules.pop(module_name, None)

    def register(module_path: str, module: types.ModuleType) -> None:
        monkeypatch.setitem(sys.modules, module_path, module)

    class _NoGradContext:
        def __call__(self, fn=None):
            if fn is None:
                return self
            return fn

        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_torch = types.ModuleType("torch")
    fake_torch.no_grad = lambda: _NoGradContext()
    fake_torch.float16 = "float16"
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: False)
    fake_torch_nn = types.ModuleType("torch.nn")

    class _TorchModule:
        pass

    fake_torch_nn.Module = _TorchModule
    fake_torch.nn = fake_torch_nn
    register("torch", fake_torch)
    register("torch.nn", fake_torch_nn)

    fake_diffusers = types.ModuleType("diffusers")

    class _DiffusersComponent:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            _ = args
            _ = kwargs
            return cls()

    fake_diffusers.AutoencoderKL = _DiffusersComponent
    fake_diffusers.DDPMScheduler = _DiffusersComponent
    fake_diffusers.LCMScheduler = _DiffusersComponent
    fake_diffusers.UNet2DConditionModel = _DiffusersComponent
    register("diffusers", fake_diffusers)

    fake_torchvision = types.ModuleType("torchvision")
    fake_transforms = types.ModuleType("torchvision.transforms")

    class _Compose:
        def __init__(self, ops):
            self.ops = ops

        def __call__(self, value):
            current = value
            for op in self.ops:
                if callable(op):
                    current = op(current)
            return current

    class _Resize:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __call__(self, value):
            return value

    class _ToTensor:
        def __call__(self, value):
            return value

    class _Normalize:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def __call__(self, value):
            return value

    class _ToPILImage:
        def __call__(self, value):
            _ = value
            return types.SimpleNamespace(resize=lambda size: ("mask", size))

    fake_transforms.Compose = _Compose
    fake_transforms.Resize = _Resize
    fake_transforms.ToTensor = _ToTensor
    fake_transforms.Normalize = _Normalize
    fake_transforms.ToPILImage = _ToPILImage
    fake_torchvision.transforms = fake_transforms
    register("torchvision", fake_torchvision)
    register("torchvision.transforms", fake_transforms)

    fake_tqdm = types.ModuleType("tqdm")
    fake_tqdm.tqdm = lambda iterable, *args, **kwargs: iterable
    register("tqdm", fake_tqdm)

    fake_transformers = types.ModuleType("transformers")

    class _AutoModelForImageSegmentation:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            _ = args
            _ = kwargs
            return cls()

        def to(self, *args, **kwargs):
            _ = args
            _ = kwargs
            return self

    fake_transformers.AutoModelForImageSegmentation = _AutoModelForImageSegmentation
    register("transformers", fake_transformers)

    fake_trimesh = types.ModuleType("trimesh")

    class _Scene:
        def to_geometry(self):
            return self

    fake_trimesh.Scene = _Scene
    register("trimesh", fake_trimesh)
    register("xatlas", types.ModuleType("xatlas"))

    fake_scipy = types.ModuleType("scipy")
    fake_scipy_sparse = types.ModuleType("scipy.sparse")
    fake_scipy_sparse_linalg = types.ModuleType("scipy.sparse.linalg")
    fake_scipy_sparse_linalg.spsolve = lambda *args, **kwargs: None
    fake_scipy.sparse = fake_scipy_sparse
    register("scipy", fake_scipy)
    register("scipy.sparse", fake_scipy_sparse)
    register("scipy.sparse.linalg", fake_scipy_sparse_linalg)

    fake_attn = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.models.attention_processor"
    )
    fake_attn.DecoupledMVRowColSelfAttnProcessor2_0 = object
    register(fake_attn.__name__, fake_attn)

    fake_ig2mv = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.pipelines.ig2mv_sdxl_pipeline"
    )

    class _StubIG2MVPipe:
        cond_encoder = types.SimpleNamespace(to=lambda *args, **kwargs: None)
        unet = types.SimpleNamespace(modules=lambda: [])
        scheduler = object()

        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            _ = args
            _ = kwargs
            return cls()

        def init_custom_adapter(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def load_custom_adapter(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def to(self, *args, **kwargs):
            _ = args
            _ = kwargs
            return self

    fake_ig2mv.IG2MVSDXLPipeline = _StubIG2MVPipe
    register(fake_ig2mv.__name__, fake_ig2mv)

    fake_scheduler = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.schedulers.scheduling_shift_snr"
    )

    class _ShiftSNRScheduler:
        @classmethod
        def from_scheduler(cls, *args, **kwargs):
            _ = args
            _ = kwargs
            return object()

    fake_scheduler.ShiftSNRScheduler = _ShiftSNRScheduler
    register(fake_scheduler.__name__, fake_scheduler)

    fake_utils = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.utils"
    )
    fake_utils.get_orthogonal_camera = lambda *args, **kwargs: None
    fake_utils.make_image_grid = lambda *args, **kwargs: None
    fake_utils.tensor_to_image = lambda *args, **kwargs: None
    register(fake_utils.__name__, fake_utils)

    fake_render = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.utils.render"
    )
    fake_render.NVDiffRastContextWrapper = object
    fake_render.load_mesh = lambda *args, **kwargs: (None, None)
    fake_render.render = lambda *args, **kwargs: None
    register(fake_render.__name__, fake_render)

    fake_diff_renderer = types.ModuleType("differentiable_renderer.mesh_render")

    class _MeshRender:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

    fake_diff_renderer.MeshRender = _MeshRender
    register(fake_diff_renderer.__name__, fake_diff_renderer)

    fake_pipeline_utils = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_geometry.models.pipelines.pipeline_utils"
    )
    fake_pipeline_utils.smart_load_model = (
        lambda model_path, subfolder=None: model_path
    )
    register(fake_pipeline_utils.__name__, fake_pipeline_utils)

    return importlib.import_module(module_name)


def _import_step1x3d_ig2mv_pipeline_module_with_test_stubs(
    monkeypatch: pytest.MonkeyPatch,
):
    module_name = (
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.pipelines."
        "ig2mv_sdxl_pipeline"
    )
    sys.modules.pop(module_name, None)

    def register(module_path: str, module: types.ModuleType) -> None:
        monkeypatch.setitem(sys.modules, module_path, module)

    def register_package(module_path: str, package_path: Path) -> None:
        package = types.ModuleType(module_path)
        package.__path__ = [str(package_path)]
        register(module_path, package)

    texture_root = (
        WORKSPACE_ROOT / "gen3d" / "model" / "step1x3d" / "pipeline" / "step1x3d_texture"
    )
    register_package("gen3d.model.step1x3d.pipeline.step1x3d_texture", texture_root)
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.pipelines",
        texture_root / "pipelines",
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.models",
        texture_root / "models",
    )
    register_package(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.texture_sync",
        texture_root / "texture_sync",
    )

    class _NoGradContext:
        def __call__(self, fn=None):
            if fn is None:
                return self
            return fn

        def __enter__(self):
            return None

        def __exit__(self, exc_type, exc, tb):
            return False

    fake_torch = types.ModuleType("torch")
    fake_torch.Tensor = object
    fake_torch.FloatTensor = object
    fake_torch.Generator = object
    fake_torch.no_grad = lambda: _NoGradContext()
    fake_torch.backends = types.SimpleNamespace(
        mps=types.SimpleNamespace(is_available=lambda: False)
    )
    fake_torch.float16 = "float16"
    fake_torch.float32 = "float32"
    register("torch", fake_torch)

    fake_torch_nn = types.ModuleType("torch.nn")
    fake_torch_nn.Module = object
    register("torch.nn", fake_torch_nn)

    fake_pil = types.ModuleType("PIL")
    fake_pil_image = types.ModuleType("PIL.Image")
    fake_pil_image.Image = object
    fake_pil.Image = fake_pil_image
    register("PIL", fake_pil)
    register("PIL.Image", fake_pil_image)

    fake_diffusers_image_processor = types.ModuleType("diffusers.image_processor")
    fake_diffusers_image_processor.PipelineImageInput = object

    class _VaeImageProcessor:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

    fake_diffusers_image_processor.VaeImageProcessor = _VaeImageProcessor
    register("diffusers.image_processor", fake_diffusers_image_processor)

    fake_diffusers_models = types.ModuleType("diffusers.models")
    fake_diffusers_models.AutoencoderKL = object
    fake_diffusers_models.ImageProjection = object
    fake_diffusers_models.T2IAdapter = object
    fake_diffusers_models.UNet2DConditionModel = object
    register("diffusers.models", fake_diffusers_models)

    fake_pipeline_output = types.ModuleType(
        "diffusers.pipelines.stable_diffusion_xl.pipeline_output"
    )
    fake_pipeline_output.StableDiffusionXLPipelineOutput = object
    register(
        "diffusers.pipelines.stable_diffusion_xl.pipeline_output",
        fake_pipeline_output,
    )

    fake_pipeline_sdxl = types.ModuleType(
        "diffusers.pipelines.stable_diffusion_xl.pipeline_stable_diffusion_xl"
    )

    class _StableDiffusionXLPipeline:
        def __init__(self, *args, **kwargs):
            _ = args
            _ = kwargs

    fake_pipeline_sdxl.StableDiffusionXLPipeline = _StableDiffusionXLPipeline
    fake_pipeline_sdxl.rescale_noise_cfg = lambda *args, **kwargs: None
    fake_pipeline_sdxl.retrieve_timesteps = (
        lambda scheduler, num_inference_steps, device, timesteps: (timesteps, 0)
    )
    register(
        "diffusers.pipelines.stable_diffusion_xl.pipeline_stable_diffusion_xl",
        fake_pipeline_sdxl,
    )

    fake_diffusers_schedulers = types.ModuleType("diffusers.schedulers")
    fake_diffusers_schedulers.KarrasDiffusionSchedulers = object
    register("diffusers.schedulers", fake_diffusers_schedulers)

    class _LoggingFacade:
        @staticmethod
        def get_logger(_name: str):
            class _Logger:
                def info(self, *args, **kwargs):
                    _ = args
                    _ = kwargs

                def warning(self, *args, **kwargs):
                    _ = args
                    _ = kwargs

                def exception(self, *args, **kwargs):
                    _ = args
                    _ = kwargs

            return _Logger()

    fake_diffusers_utils = types.ModuleType("diffusers.utils")
    fake_diffusers_utils.deprecate = lambda *args, **kwargs: None
    fake_diffusers_utils.logging = _LoggingFacade()
    fake_diffusers_utils.BaseOutput = object
    fake_diffusers_utils.numpy_to_pil = lambda *args, **kwargs: []
    fake_diffusers_utils.pt_to_pil = lambda *args, **kwargs: []
    fake_diffusers_utils.is_accelerate_available = lambda: False
    fake_diffusers_utils.is_accelerate_version = lambda *args, **kwargs: False
    fake_diffusers_utils.replace_example_docstring = (
        lambda *args, **kwargs: (lambda fn: fn)
    )
    register("diffusers.utils", fake_diffusers_utils)

    fake_diffusers_torch_utils = types.ModuleType("diffusers.utils.torch_utils")
    fake_diffusers_torch_utils.randn_tensor = lambda *args, **kwargs: object()
    register("diffusers.utils.torch_utils", fake_diffusers_torch_utils)

    fake_einops = types.ModuleType("einops")
    fake_einops.rearrange = lambda value, *args, **kwargs: value
    register("einops", fake_einops)

    fake_transformers = types.ModuleType("transformers")
    fake_transformers.CLIPImageProcessor = object
    fake_transformers.CLIPTextModel = object
    fake_transformers.CLIPTextModelWithProjection = object
    fake_transformers.CLIPTokenizer = object
    fake_transformers.CLIPVisionModelWithProjection = object
    register("transformers", fake_transformers)

    fake_loaders = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.loaders"
    )
    fake_loaders.CustomAdapterMixin = object
    register(fake_loaders.__name__, fake_loaders)

    fake_attention = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.models.attention_processor"
    )
    fake_attention.DecoupledMVRowSelfAttnProcessor2_0 = object
    fake_attention.set_unet_2d_condition_attn_processor = (
        lambda *args, **kwargs: None
    )
    register(fake_attention.__name__, fake_attention)

    fake_project = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.texture_sync.project"
    )
    fake_project.UVProjection = object
    register(fake_project.__name__, fake_project)

    fake_step_sync = types.ModuleType(
        "gen3d.model.step1x3d.pipeline.step1x3d_texture.texture_sync.step_sync"
    )
    fake_step_sync.step_tex_sync = lambda *args, **kwargs: None
    register(fake_step_sync.__name__, fake_step_sync)

    fake_trimesh = types.ModuleType("trimesh")
    fake_trimesh.Trimesh = object
    register("trimesh", fake_trimesh)

    fake_torchvision = types.ModuleType("torchvision")
    fake_torchvision_transforms = types.ModuleType("torchvision.transforms")
    fake_torchvision_transforms.Compose = object
    fake_torchvision_transforms.Resize = object
    fake_torchvision_transforms.GaussianBlur = object
    fake_torchvision_transforms.InterpolationMode = object
    fake_torchvision.transforms = fake_torchvision_transforms
    register("torchvision", fake_torchvision)
    register("torchvision.transforms", fake_torchvision_transforms)

    return importlib.import_module(module_name)


def test_step1x3d_texture_remove_bg_path_does_not_force_dtype(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texture_module = _import_step1x3d_texture_pipeline_module_with_test_stubs(
        monkeypatch
    )
    pipeline_cls = texture_module.Step1X3DTexturePipeline
    pipeline = pipeline_cls.__new__(pipeline_cls)

    class _Pred:
        def sigmoid(self):
            return self

        def cpu(self):
            class _PredBatch:
                def __getitem__(self, index):
                    _ = index
                    return types.SimpleNamespace(squeeze=lambda: "pred")

            return _PredBatch()

    observed_input_to: dict[str, object] = {}

    class _InputTensor:
        def unsqueeze(self, dim: int):
            observed_input_to["unsqueeze_dim"] = dim
            return self

        def to(self, *args, **kwargs):
            observed_input_to["args"] = args
            observed_input_to["kwargs"] = kwargs
            return self

    class _FakeNet:
        dtype = "float16"

        def __call__(self, input_images):
            observed_input_to["net_input"] = input_images
            return [_Pred()]

    class _FakeImage:
        size = (8, 8)

        def __init__(self) -> None:
            self.alpha = None

        def putalpha(self, value) -> None:
            self.alpha = value

    input_image = _FakeImage()
    returned_image = pipeline.remove_bg(
        input_image,
        _FakeNet(),
        transform=lambda image: _InputTensor(),
        device="cpu",
    )
    assert returned_image is input_image
    assert observed_input_to["args"] == ("cpu",)
    assert observed_input_to["kwargs"] == {}

    birefnet_to_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class _FakeBiRefNet:
        def to(self, *args, **kwargs):
            birefnet_to_calls.append((args, kwargs))
            return self

    class _FakeSegModelFactory:
        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            _ = args
            _ = kwargs
            return _FakeBiRefNet()

    monkeypatch.setattr(
        texture_module,
        "AutoModelForImageSegmentation",
        _FakeSegModelFactory,
    )

    class _StopRun(RuntimeError):
        pass

    pipeline.config = types.SimpleNamespace(
        device="cpu",
        dtype="float16",
        num_views=1,
        text="high quality",
        num_inference_steps=1,
        guidance_scale=1.0,
        seed=1,
        lora_scale=1.0,
        reference_conditioning_scale=1.0,
        negative_prompt="",
    )
    pipeline._birefnet = None
    pipeline._birefnet_transform = None
    pipeline.ig2mv_pipe = object()
    pipeline.run_ig2mv_pipeline = lambda *args, **kwargs: (_ for _ in ()).throw(
        _StopRun()
    )

    with pytest.raises(_StopRun):
        pipeline.__call__(image="stub-image", mesh=object(), remove_bg=True, seed=1)

    assert len(birefnet_to_calls) == 1
    _, birefnet_to_kwargs = birefnet_to_calls[0]
    assert birefnet_to_kwargs == {"device": "cpu"}
    assert "dtype" not in birefnet_to_kwargs


def test_step1x3d_geometry_casts_transformer_inputs_to_transformer_dtype(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    geometry_module = _import_step1x3d_geometry_pipeline_module_with_test_stubs(
        monkeypatch
    )
    pipeline_cls = geometry_module.Step1X3DGeometryPipeline
    pipeline = pipeline_cls.__new__(pipeline_cls)

    observed_dtypes: dict[str, str | None] = {}

    class _FakeTransformer:
        cfg = types.SimpleNamespace(
            use_label_condition=True,
            use_caption_condition=True,
            input_channels=4,
        )

        def parameters(self):
            yield types.SimpleNamespace(dtype="float32")

        def __call__(
            self,
            latent_model_input,
            timestep,
            visual_condition,
            label_condition,
            caption_condition,
            return_dict=False,
        ):
            _ = timestep
            _ = return_dict
            observed_dtypes["latent_model_input"] = latent_model_input.dtype
            observed_dtypes["visual_condition"] = (
                None if visual_condition is None else visual_condition.dtype
            )
            observed_dtypes["label_condition"] = (
                None if label_condition is None else label_condition.dtype
            )
            observed_dtypes["caption_condition"] = (
                None if caption_condition is None else caption_condition.dtype
            )
            return [geometry_module.torch.Tensor(dtype="float32", shape=(1, 2, 4))]

    class _FakeScheduler:
        order = 1

        def step(self, noise_pred, t, latents, return_dict=False):
            _ = noise_pred
            _ = t
            _ = return_dict
            return [latents]

    class _ProgressBar:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def update(self):
            return None

    pipeline._execution_device = "cpu"
    pipeline.transformer = _FakeTransformer()
    pipeline.scheduler = _FakeScheduler()
    pipeline.vae = types.SimpleNamespace(cfg=types.SimpleNamespace(num_latents=2))
    pipeline.progress_bar = lambda total: _ProgressBar()
    pipeline.encode_image = (
        lambda image, device, num_meshes_per_prompt: (
            geometry_module.torch.Tensor(dtype="float16", shape=(1, 2, 4)),
            geometry_module.torch.Tensor(dtype="float16", shape=(1, 2, 4)),
        )
    )
    pipeline.encode_label = (
        lambda label, device, num_meshes_per_prompt: (
            geometry_module.torch.Tensor(dtype="float16", shape=(1, 2, 4)),
            geometry_module.torch.Tensor(dtype="float16", shape=(1, 2, 4)),
        )
    )
    pipeline.encode_caption = (
        lambda caption, device, num_meshes_per_prompt: (
            geometry_module.torch.Tensor(dtype="float16", shape=(1, 2, 4)),
            geometry_module.torch.Tensor(dtype="float16", shape=(1, 2, 4)),
        )
    )
    pipeline.prepare_latents = (
        lambda *args, **kwargs: geometry_module.torch.Tensor(
            dtype="float16", shape=(1, 2, 4)
        )
    )

    pipeline.__call__(
        image=geometry_module.PIL.Image.Image(),
        label="demo-label",
        caption="demo-caption",
        num_inference_steps=1,
        guidance_scale=1.0,
        output_type="latent",
        use_zero_init=False,
    )

    assert observed_dtypes == {
        "latent_model_input": "float32",
        "visual_condition": "float32",
        "label_condition": "float32",
        "caption_condition": "float32",
    }


def test_step1x3d_texture_load_ig2mv_pipeline_does_not_cast_processor_dtype(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    texture_module = _import_step1x3d_texture_pipeline_module_with_test_stubs(
        monkeypatch
    )
    pipeline_cls = texture_module.Step1X3DTexturePipeline
    pipeline = pipeline_cls.__new__(pipeline_cls)

    pipe_to_calls: list[dict[str, object]] = []
    cond_encoder_to_calls: list[dict[str, object]] = []
    processor_to_calls: list[dict[str, object]] = []

    class _FakeProcessor(texture_module.torch.nn.Module):
        def to(self, *args, **kwargs):
            processor_to_calls.append({"args": args, "kwargs": kwargs})
            return self

    class _FakeUnetModule:
        def __init__(self) -> None:
            self.processor = _FakeProcessor()

    class _FakeIG2MVPipe:
        def __init__(self) -> None:
            self.scheduler = object()
            self.unet = types.SimpleNamespace(modules=lambda: [_FakeUnetModule()])
            self.cond_encoder = types.SimpleNamespace(to=self._cond_encoder_to)

        @classmethod
        def from_pretrained(cls, *args, **kwargs):
            _ = args
            _ = kwargs
            return cls()

        def _cond_encoder_to(self, *args, **kwargs):
            cond_encoder_to_calls.append({"args": args, "kwargs": kwargs})
            return self

        def init_custom_adapter(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def load_custom_adapter(self, *args, **kwargs):
            _ = args
            _ = kwargs

        def to(self, *args, **kwargs):
            pipe_to_calls.append({"args": args, "kwargs": kwargs})
            return self

    monkeypatch.setattr(texture_module, "IG2MVSDXLPipeline", _FakeIG2MVPipe)

    pipeline.prepare_ig2mv_pipeline(
        base_model="stub-base",
        vae_model=None,
        unet_model=None,
        lora_model=None,
        adapter_path="stub-adapter",
        scheduler="ddpm",
        num_views=6,
        device="cpu",
        dtype="float16",
    )

    assert pipe_to_calls == [{"args": (), "kwargs": {"device": "cpu", "dtype": "float16"}}]
    assert cond_encoder_to_calls == [
        {"args": (), "kwargs": {"device": "cpu", "dtype": "float16"}}
    ]
    assert processor_to_calls == []


def test_step1x3d_ig2mv_decode_casts_latents_to_vae_dtype(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ig2mv_module = _import_step1x3d_ig2mv_pipeline_module_with_test_stubs(monkeypatch)
    pipeline_cls = ig2mv_module.IG2MVSDXLPipeline
    pipeline = pipeline_cls.__new__(pipeline_cls)

    class _FakeTensor:
        def __init__(self, dtype: str) -> None:
            self.dtype = dtype

        def to(self, *args, **kwargs):
            dtype = kwargs.get("dtype")
            if dtype is None and args:
                dtype = args[0]
            return _FakeTensor(dtype or self.dtype)

    observed: dict[str, object] = {}

    class _FakePostQuantConv:
        def parameters(self):
            yield types.SimpleNamespace(dtype="float32")

    class _FakeVAE:
        def __init__(self) -> None:
            self.post_quant_conv = _FakePostQuantConv()

        def decode(self, latents, return_dict=False):
            observed["decode_input_dtype"] = latents.dtype
            observed["return_dict"] = return_dict
            return ["decoded-image"]

    pipeline.vae = _FakeVAE()

    decoded = pipeline._decode_latents_with_vae_dtype(_FakeTensor("float16"))

    assert decoded == "decoded-image"
    assert observed == {"decode_input_dtype": "float32", "return_dict": False}


def test_step1x3d_provider_resolves_existing_local_model_path(tmp_path: Path) -> None:
    model_dir = tmp_path / "step1x3d-model"
    model_dir.mkdir(parents=True)
    source_type, model_reference = Step1X3DProvider._resolve_model_reference(
        str(model_dir)
    )
    assert source_type == "local"
    assert model_reference == str(model_dir.resolve())


def test_step1x3d_provider_rejects_missing_non_local_model_path() -> None:
    with pytest.raises(
        ModelProviderConfigurationError,
        match="Use Admin to download first",
    ):
        Step1X3DProvider._resolve_model_reference("stepfun-ai/Step1X-3D")


def test_step1x3d_provider_patches_rembg_bria_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    rembg_module = types.ModuleType("rembg")
    rembg_bg_module = types.ModuleType("rembg.bg")

    def fake_new_session(*args, **kwargs):
        if "model_name" in kwargs:
            requested_model = kwargs["model_name"]
        elif args:
            requested_model = args[0]
        else:
            requested_model = "u2net"
        calls.append(str(requested_model))
        if requested_model == "bria-rmbg":
            return {"model_name": "bria-rmbg"}
        raise ValueError(f"No session class found for model '{requested_model}'")

    rembg_module.new_session = fake_new_session
    rembg_bg_module.new_session = fake_new_session
    monkeypatch.setitem(sys.modules, "rembg", rembg_module)
    monkeypatch.setitem(sys.modules, "rembg.bg", rembg_bg_module)

    step1x3d_provider_module._install_rembg_bria_alias_patch()

    session = rembg_module.new_session(model_name="bria", providers=["CUDAExecutionProvider"])
    assert session == {"model_name": "bria-rmbg"}
    assert calls == ["bria-rmbg"]


def test_step1x3d_provider_rembg_bria_alias_falls_back_to_default_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    rembg_module = types.ModuleType("rembg")
    rembg_bg_module = types.ModuleType("rembg.bg")

    def fake_new_session(*args, **kwargs):
        if "model_name" in kwargs:
            requested_model = kwargs["model_name"]
        elif args:
            requested_model = args[0]
        else:
            requested_model = "u2net"
        calls.append(str(requested_model))
        if requested_model in {"bria", "bria-rmbg"}:
            raise ValueError(f"No session class found for model '{requested_model}'")
        return {"model_name": str(requested_model)}

    rembg_module.new_session = fake_new_session
    rembg_bg_module.new_session = fake_new_session
    monkeypatch.setitem(sys.modules, "rembg", rembg_module)
    monkeypatch.setitem(sys.modules, "rembg.bg", rembg_bg_module)

    step1x3d_provider_module._install_rembg_bria_alias_patch()

    session = rembg_module.new_session(model_name="bria", providers=["CUDAExecutionProvider"])
    assert session == {"model_name": "u2net"}
    assert calls == ["bria-rmbg", "u2net"]


def test_step1x3d_provider_run_single_calls_both_pipelines() -> None:
    observed: dict[str, object] = {}

    class FakeGeometryPipeline:
        def __call__(self, image, **kwargs):
            observed["geo_kwargs"] = kwargs
            from types import SimpleNamespace
            return SimpleNamespace(mesh=["raw_mesh"])

    class FakeTextureConfig:
        num_inference_steps = 50

    class FakeTexturePipeline:
        config = FakeTextureConfig()

        def __call__(self, image, mesh):
            observed["tex_mesh_input"] = mesh
            observed["tex_steps"] = self.config.num_inference_steps
            return "textured_mesh"

    provider = Step1X3DProvider(
        geometry_pipeline=FakeGeometryPipeline(),
        texture_pipeline=FakeTexturePipeline(),
        model_path="stepfun-ai/Step1X-3D",
    )

    result = provider._run_single(
        image="image-object",
        options={"num_inference_steps": 30, "guidance_scale": 6.0, "texture_steps": 10},
    )

    assert result == "textured_mesh"
    assert observed["geo_kwargs"] == {
        "guidance_scale": 6.0,
        "num_inference_steps": 30,
    }
    assert observed["tex_mesh_input"] == "raw_mesh"
    assert observed["tex_steps"] == 10


def test_step1x3d_provider_run_single_skips_texture_when_none() -> None:
    class FakeGeometryPipeline:
        def __call__(self, image, **kwargs):
            from types import SimpleNamespace
            return SimpleNamespace(mesh=["geo_mesh"])

    provider = Step1X3DProvider(
        geometry_pipeline=FakeGeometryPipeline(),
        texture_pipeline=None,
        model_path="stepfun-ai/Step1X-3D",
    )
    result = provider._run_single(image="img", options={})
    assert result == "geo_mesh"


def test_step1x3d_provider_export_glb_calls_mesh_export(tmp_path: Path) -> None:
    observed: dict[str, object] = {}

    class FakeMesh:
        def export(self, path: str) -> None:
            observed["export_path"] = path

    provider = Step1X3DProvider(
        geometry_pipeline=object(),
        texture_pipeline=None,
        model_path="stepfun-ai/Step1X-3D",
    )
    output = tmp_path / "model.glb"
    provider.export_glb(GenerationResult(mesh=FakeMesh()), output, {})
    assert observed["export_path"] == str(output)


def test_step1x3d_mock_provider_emits_canonical_stages() -> None:
    mock = MockStep1X3DProvider(stage_delay_ms=0)
    assert mock.stages == [
        {"name": "ss", "weight": 0.20},
        {"name": "shape", "weight": 0.45},
        {"name": "material", "weight": 0.35},
    ]


@pytest.mark.anyio
async def test_step1x3d_mock_provider_run_batch() -> None:
    mock = MockStep1X3DProvider(stage_delay_ms=0)
    stages_seen: list[str] = []

    async def progress_cb(progress):
        stages_seen.append(progress.stage_name)

    results = await mock.run_batch(
        images=["img1"],
        options={"resolution": 512},
        progress_cb=progress_cb,
    )
    assert len(results) == 1
    assert results[0].metadata["provider"] == "step1x3d"
    assert stages_seen == ["ss", "shape", "material"]


@pytest.mark.anyio
async def test_step1x3d_mock_provider_failure_injection() -> None:
    mock = MockStep1X3DProvider(stage_delay_ms=0)
    with pytest.raises(ModelProviderExecutionError, match="gpu_shape"):
        await mock.run_batch(
            images=["img"],
            options={"mock_failure_stage": "gpu_shape"},
        )


def test_step1x3d_mock_provider_export_glb_valid(tmp_path: Path) -> None:
    mock = MockStep1X3DProvider()
    output = tmp_path / "mock.glb"
    mock.export_glb(GenerationResult(mesh=None), output, {})
    data = output.read_bytes()
    assert data[:4] == b"glTF"


def test_build_provider_supports_step1x3d_mock(tmp_path: Path) -> None:
    del tmp_path
    provider = server_module.build_provider(
        provider_name="step1x3d",
        provider_mode="mock",
        model_path="stepfun-ai/Step1X-3D",
        mock_delay_ms=60,
    )
    assert isinstance(provider, MockStep1X3DProvider)


def test_build_provider_uses_step1x3d_metadata_only_in_real_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeStep1X3DProvider:
        @classmethod
        def metadata_only(cls, model_path: str):
            observed["metadata_only_model_path"] = model_path
            return {"provider": "step1x3d", "mode": "metadata_only"}

        @classmethod
        def from_pretrained(cls, model_path: str):
            raise AssertionError(f"from_pretrained should not be called: {model_path}")

    monkeypatch.setattr(server_module, "Step1X3DProvider", FakeStep1X3DProvider)

    provider = server_module.build_provider(
        provider_name="step1x3d",
        provider_mode="real",
        model_path="stepfun-ai/Step1X-3D",
        mock_delay_ms=60,
    )

    assert provider == {"provider": "step1x3d", "mode": "metadata_only"}
    assert observed["metadata_only_model_path"] == "stepfun-ai/Step1X-3D"


@pytest.mark.anyio
async def test_step1x3d_metadata_only_provider_rejects_inference_calls(
    tmp_path: Path,
) -> None:
    model_dir = tmp_path / "step1x3d-model"
    model_dir.mkdir(parents=True)
    provider = Step1X3DProvider.metadata_only(str(model_dir))
    with pytest.raises(
        ModelProviderExecutionError,
        match="metadata-only provider cannot run inference",
    ):
        await provider.run_batch(images=["img"], options={})


def test_build_provider_rejects_unknown_provider(tmp_path: Path) -> None:
    del tmp_path
    with pytest.raises(ModelProviderConfigurationError, match="unsupported MODEL_PROVIDER"):
        server_module.build_provider(
            provider_name="unknown_model",
            provider_mode="mock",
            model_path="unused",
            mock_delay_ms=60,
        )


def test_minio_artifact_store_requires_complete_config(tmp_path: Path) -> None:
    config = ServingConfig(
        artifact_store_mode="minio",
        database_path=tmp_path / "app.sqlite3",
        artifacts_dir=tmp_path / "artifacts",
    )

    with pytest.raises(
        ArtifactStoreConfigurationError,
        match="OBJECT_STORE_ENDPOINT, OBJECT_STORE_BUCKET, OBJECT_STORE_ACCESS_KEY, OBJECT_STORE_SECRET_KEY",
    ):
        create_test_app(config)
