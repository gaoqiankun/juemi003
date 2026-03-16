from __future__ import annotations

import asyncio
import io
import importlib
import json
import sqlite3
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path
from typing import Awaitable, Callable

import pytest
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.api import server as server_module
from gen3d.api.server import create_app, run_real_mode_preflight
from gen3d.config import ServingConfig, ServingConfigurationError
from gen3d.engine import async_engine as async_engine_module
from gen3d.engine.sequence import RequestSequence, TaskStatus, TaskType, utcnow
from gen3d.model.base import GenerationResult, ModelProviderConfigurationError
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.storage.artifact_store import (
    ArtifactStoreConfigurationError,
    ArtifactStoreOperationError,
)
from gen3d.storage.task_store import TaskStore

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
    admin_token: str | None = "admin-token",
    rate_limit_concurrent: int = 5,
    rate_limit_per_hour: int = 100,
    webhook_max_retries: int = 3,
    task_timeout_seconds: int = 3600,
    database_path: Path | None = None,
    artifacts_dir: Path | None = None,
    uploads_dir: Path | None = None,
    gpu_device_ids: tuple[str, ...] = ("0",),
    queue_max_size: int = 20,
    preprocess_max_image_bytes: int = 10 * 1024 * 1024,
) -> TestClient:
    database_path = database_path or (tmp_path / "gen3d.sqlite3")
    artifacts_dir = artifacts_dir or (tmp_path / "artifacts")
    uploads_dir = uploads_dir or (tmp_path / "uploads")
    config = ServingConfig(
        api_token=api_token,
        admin_token=admin_token,
        database_path=database_path,
        artifacts_dir=artifacts_dir,
        uploads_dir=uploads_dir,
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
    return TestClient(create_app(config, webhook_sender=webhook_sender))


def make_real_mode_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    allowed_callback_domains: tuple[str, ...] = (),
    admin_token: str | None = "admin-token",
    uploads_dir: Path | None = None,
) -> TestClient:
    monkeypatch.setattr(
        server_module,
        "build_provider",
        lambda config: MockTrellis2Provider(stage_delay_ms=0),
    )
    config = ServingConfig(
        provider_mode="real",
        api_token="test-token",
        admin_token=admin_token,
        database_path=tmp_path / "gen3d-real.sqlite3",
        artifacts_dir=tmp_path / "artifacts-real",
        uploads_dir=uploads_dir or (tmp_path / "uploads-real"),
        preprocess_delay_ms=0,
        queue_delay_ms=20,
        mock_gpu_stage_delay_ms=0,
        mock_export_delay_ms=0,
        allowed_callback_domains=allowed_callback_domains,
    )
    return TestClient(create_app(config))


def auth_headers(token: str = "test-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def admin_headers(token: str = "admin-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


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
        "/admin/keys",
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


def collect_task_snapshots(
    client: TestClient,
    task_id: str,
    *,
    terminal_status: str,
    token: str | None = None,
    timeout_seconds: float = 4.0,
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
    timeout_seconds: float = 3.0,
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


def fetch_metrics_payload(client: TestClient, *, token: str = "test-token") -> str:
    response = client.get("/metrics", headers=auth_headers(token))
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


def test_admin_key_routes_return_401_when_admin_token_is_unset(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token=None) as client:
        response = client.get("/admin/keys", headers=admin_headers())

    assert response.status_code == 401
    assert response.json()["detail"] == "invalid admin token"


def test_admin_key_crud_flow_returns_token_once_and_list_hides_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        create_response = client.post(
            "/admin/keys",
            headers=admin_headers(),
            json={"label": "QA Team"},
        )
        assert create_response.status_code == 201
        created_payload = create_response.json()
        key_id = created_payload["keyId"]

        list_response = client.get("/admin/keys", headers=admin_headers())
        patch_response = client.patch(
            f"/admin/keys/{key_id}",
            headers=admin_headers(),
            json={"is_active": False},
        )
        missing_response = client.patch(
            "/admin/keys/missing-key",
            headers=admin_headers(),
            json={"is_active": False},
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


def test_managed_api_key_auth_supports_valid_invalid_and_api_tokens_are_rejected(
    tmp_path: Path,
) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Tester A")

        managed_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        invalid_response = client.post(
            "/v1/tasks",
            headers=auth_headers("invalid-key"),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        api_token_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers("test-token"),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        api_token_list_response = client.get(
            "/v1/tasks",
            headers=auth_headers("test-token"),
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
    assert api_token_create_response.status_code == 401
    assert api_token_create_response.json()["detail"] == "invalid bearer token"
    assert api_token_list_response.status_code == 401
    assert api_token_list_response.json()["detail"] == "invalid bearer token"


def test_inactive_managed_api_key_is_rejected(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        managed_key = create_managed_api_key(client, label="Tester B")
        deactivate_response = client.patch(
            f"/admin/keys/{managed_key['keyId']}",
            headers=admin_headers(),
            json={"is_active": False},
        )
        create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key["token"]),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        time.sleep(0.01)
        key_b_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_b["token"]),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        time.sleep(0.01)
        key_b_create_response = client.post(
            "/v1/tasks",
            headers=auth_headers(managed_key_b["token"]),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )

        all_response = client.get(
            "/admin/tasks",
            headers=admin_headers(),
        )
        key_a_response = client.get(
            f"/admin/tasks?key_id={managed_key_a['keyId']}",
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


def test_admin_tasks_requires_valid_admin_token(tmp_path: Path) -> None:
    with make_client(tmp_path, admin_token="admin-token") as client:
        missing_token_response = client.get("/admin/tasks")
        invalid_token_response = client.get(
            "/admin/tasks",
            headers=admin_headers("wrong-token"),
        )
    with make_client(tmp_path / "no-admin", admin_token=None) as no_admin_client:
        missing_admin_config_response = no_admin_client.get(
            "/admin/tasks",
            headers=admin_headers(),
        )

    assert missing_token_response.status_code == 401
    assert missing_token_response.json()["detail"] == "invalid admin token"
    assert invalid_token_response.status_code == 401
    assert invalid_token_response.json()["detail"] == "invalid admin token"
    assert missing_admin_config_response.status_code == 401
    assert missing_admin_config_response.json()["detail"] == "invalid admin token"


def test_task_list_returns_requested_page_and_cursor_metadata(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "gen3d.sqlite3"
    base_time = utcnow()
    seed_tasks(
        database_path,
        [
            RequestSequence(
                task_id=f"task-{index:02d}",
                task_type=TaskType.IMAGE_TO_3D,
                input_url=SAMPLE_IMAGE_DATA_URL,
                options={"resolution": 1024},
                status=TaskStatus.SUBMITTED,
                progress=0,
                current_stage=TaskStatus.SUBMITTED.value,
                created_at=base_time - timedelta(seconds=54 - index),
                queued_at=base_time - timedelta(seconds=54 - index),
                updated_at=base_time - timedelta(seconds=54 - index),
            )
            for index in range(55)
        ],
    )

    with make_client(tmp_path, database_path=database_path) as client:
        response = client.get("/admin/tasks?limit=50", headers=admin_headers())

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
        response = client.get("/admin/tasks", headers=admin_headers())

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


def test_delete_task_soft_deletes_own_terminal_task_and_removes_artifacts(
    tmp_path: Path,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
    database_path = tmp_path / "gen3d.sqlite3"
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
    database_path = tmp_path / "gen3d.sqlite3"
    base_time = utcnow()
    seed_tasks(
        database_path,
        [
            RequestSequence(
                task_id=f"seed-{index}",
                task_type=TaskType.IMAGE_TO_3D,
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
        first_page_response = client.get("/admin/tasks?limit=2", headers=admin_headers())
        assert first_page_response.status_code == 200
        first_page_items = task_page_items(first_page_response)

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201

        second_page_response = client.get(
            "/admin/tasks",
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
                "image_url": png_payload["url"],
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        wait_for_status(client, create_response.json()["taskId"], "succeeded")

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


def test_sse_stream_replays_full_task_lifecycle(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
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
            headers=task_auth_headers(client),
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
            headers=task_auth_headers(client),
        )
        download_response = client.get(
            f"/v1/tasks/{payload['taskId']}/artifacts/model.glb",
            headers=task_auth_headers(client),
        )
        metrics_response = client.get("/metrics", headers=auth_headers())

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
    assert metrics_response.status_code == 200
    metrics_payload = metrics_response.text
    assert "gen3d_queue_depth" in metrics_payload
    assert "gen3d_task_duration_seconds" in metrics_payload
    assert "gen3d_stage_duration_seconds" in metrics_payload
    assert "gen3d_task_total" in metrics_payload
    assert "gen3d_webhook_total" in metrics_payload
    assert 'gen3d_task_total{status="succeeded"}' in metrics_payload
    assert 'gen3d_task_duration_seconds_count{status="succeeded"}' in metrics_payload


def test_metrics_track_successful_task(tmp_path: Path) -> None:
    with make_client(tmp_path) as client:
        initial_metrics_payload = fetch_metrics_payload(client)
        succeeded_total_before = metric_sample_value(
            initial_metrics_payload,
            "gen3d_task_total",
            {"status": "succeeded"},
        )
        succeeded_duration_count_before = metric_sample_value(
            initial_metrics_payload,
            "gen3d_task_duration_seconds_count",
            {"status": "succeeded"},
        )
        preprocess_count_before = metric_sample_value(
            initial_metrics_payload,
            "gen3d_stage_duration_seconds_count",
            {"stage": "preprocess"},
        )
        gpu_count_before = metric_sample_value(
            initial_metrics_payload,
            "gen3d_stage_duration_seconds_count",
            {"stage": "gpu"},
        )
        export_count_before = metric_sample_value(
            initial_metrics_payload,
            "gen3d_stage_duration_seconds_count",
            {"stage": "export"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201
        wait_for_status(client, create_response.json()["taskId"], "succeeded")

        assert (
            wait_for_metric_sample(
                client,
                "gen3d_task_total",
                labels={"status": "succeeded"},
                minimum_value=succeeded_total_before + 1,
            )
            >= succeeded_total_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "gen3d_task_duration_seconds_count",
                labels={"status": "succeeded"},
                minimum_value=succeeded_duration_count_before + 1,
            )
            >= succeeded_duration_count_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "gen3d_stage_duration_seconds_count",
                labels={"stage": "preprocess"},
                minimum_value=preprocess_count_before + 1,
            )
            >= preprocess_count_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "gen3d_stage_duration_seconds_count",
                labels={"stage": "gpu"},
                minimum_value=gpu_count_before + 1,
            )
            >= gpu_count_before + 1
        )
        assert (
            wait_for_metric_sample(
                client,
                "gen3d_stage_duration_seconds_count",
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
            "gen3d_task_total",
            {"status": "failed"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "gen3d_task_total",
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
            "gen3d_webhook_total",
            {"result": "success"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "gen3d_webhook_total",
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "idempotency_key": "same-task",
                "options": {"resolution": 1024},
            },
        )
        second_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
    database_path = tmp_path / "gen3d.sqlite3"
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
            "gen3d_webhook_total",
            {"result": "failure"},
        )
        webhook_success_before = metric_sample_value(
            initial_metrics_payload,
            "gen3d_webhook_total",
            {"result": "success"},
        )

        create_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "gen3d_webhook_total",
                labels={"result": "failure"},
                minimum_value=webhook_failure_before + 3,
            )
            >= webhook_failure_before + 3
        )
        webhook_success_after = metric_sample_value(
            fetch_metrics_payload(client),
            "gen3d_webhook_total",
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        second_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        third_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "options": {"resolution": 1024},
            },
        )
        assert create_response.status_code == 201

        wait_for_status(client, create_response.json()["taskId"], "succeeded")
        metrics_payload = fetch_metrics_payload(client)

    assert "gen3d_gpu_slot_active" in metrics_payload
    assert 'gen3d_gpu_slot_active{device="0"}' in metrics_payload


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
            headers=task_auth_headers(client),
            json={
                "type": "image_to_3d",
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
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
            headers=task_auth_headers(client),
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
                "image_url": SAMPLE_IMAGE_DATA_URL,
                "callback_url": "https://callback.test/success",
                "options": {"resolution": 1024},
            },
        )
        failed_response = client.post(
            "/v1/tasks",
            headers=task_auth_headers(client),
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
            headers=task_auth_headers(client),
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
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "image_url": "file:///tmp/input.png",
                "options": {"resolution": 1024},
            },
        )
        invalid_callback_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "image_url": "http://127.0.0.1:9/input.png",
                "callback_url": "ftp://callback.test/task",
                "options": {"resolution": 1024},
            },
        )
        disallowed_callback_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
            json={
                "type": "image_to_3d",
                "image_url": "http://127.0.0.1:9/input.png",
                "callback_url": "https://evil.test/task",
                "options": {"resolution": 1024},
            },
        )
        allowed_callback_response = real_client.post(
            "/v1/tasks",
            headers=task_auth_headers(real_client),
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
