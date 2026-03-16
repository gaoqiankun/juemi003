from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from typing import Any

from datetime import datetime

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from gen3d.api.schemas import (
    AdminApiKeyCreateRequest,
    AdminApiKeyCreateResponse,
    AdminApiKeyListItem,
    AdminApiKeySetActiveRequest,
    CursorPaginationParams,
    HealthResponse,
    PrivilegedApiKeyCreateRequest,
    PrivilegedApiKeyCreateResponse,
    PrivilegedApiKeyListItem,
    TaskListResponse,
    TaskSummary,
    TaskArtifactsResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskResponse,
    UploadImageResponse,
    task_type_from_request,
)
from gen3d.config import ServingConfig
from gen3d.engine.async_engine import AsyncGen3DEngine
from gen3d.engine.model_registry import ModelRegistry, ModelRuntime
from gen3d.engine.pipeline import PipelineCoordinator, PipelineQueueFullError
from gen3d.engine.sequence import TERMINAL_STATUSES, TaskStatus
from gen3d.model.base import ModelProviderConfigurationError
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.observability.metrics import render_metrics
from gen3d.security import (
    RateLimitExceededError,
    TaskSubmissionValidationError,
    TokenRateLimiter,
)
from gen3d.stages.export.stage import ExportStage
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.stage import GPUStage
from gen3d.stages.gpu.worker import build_gpu_workers
from gen3d.stages.preprocess.stage import PreprocessStage
from gen3d.storage.artifact_store import (
    ArtifactStore,
    ArtifactStoreConfigurationError,
    build_boto3_object_storage_client,
)
from gen3d.storage.api_key_store import (
    ApiKeyStore,
    KEY_MANAGER_SCOPE,
    METRICS_SCOPE,
    TASK_VIEWER_SCOPE,
    USER_KEY_SCOPE,
)
from gen3d.storage.task_store import TaskStore

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
ALLOWED_UPLOAD_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass(slots=True)
class AppContainer:
    config: ServingConfig
    task_store: TaskStore
    api_key_store: ApiKeyStore
    artifact_store: ArtifactStore
    model_registry: ModelRegistry
    pipeline: PipelineCoordinator
    engine: AsyncGen3DEngine


def build_provider(config: ServingConfig):
    provider_name = config.model_provider.strip().lower()
    provider_mode = config.provider_mode.strip().lower()

    if provider_name != "trellis2":
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER: {config.model_provider}"
        )

    if provider_mode == "mock":
        return MockTrellis2Provider(stage_delay_ms=config.mock_gpu_stage_delay_ms)
    if provider_mode == "real":
        return Trellis2Provider.from_pretrained(config.model_path)

    raise ModelProviderConfigurationError(
        f"unsupported PROVIDER_MODE: {config.provider_mode}"
    )


def build_artifact_store(config: ServingConfig) -> ArtifactStore:
    store_mode = config.artifact_store_mode.strip().lower()
    if store_mode == "local":
        return ArtifactStore(config.artifacts_dir, mode="local")
    if store_mode != "minio":
        raise ArtifactStoreConfigurationError(
            f"unsupported ARTIFACT_STORE_MODE: {config.artifact_store_mode}"
        )

    required_fields = {
        "OBJECT_STORE_ENDPOINT": config.object_store_endpoint,
        "OBJECT_STORE_BUCKET": config.object_store_bucket,
        "OBJECT_STORE_ACCESS_KEY": config.object_store_access_key,
        "OBJECT_STORE_SECRET_KEY": config.object_store_secret_key,
    }
    missing = [name for name, value in required_fields.items() if not value]
    if missing:
        raise ArtifactStoreConfigurationError(
            "minio artifact store requires: " + ", ".join(missing)
        )

    object_store_client = build_boto3_object_storage_client(
        endpoint_url=str(config.object_store_endpoint),
        external_endpoint_url=config.object_store_external_endpoint,
        access_key=str(config.object_store_access_key),
        secret_key=str(config.object_store_secret_key),
        region=config.object_store_region,
    )
    return ArtifactStore(
        config.artifacts_dir,
        mode="minio",
        object_store_client=object_store_client,
        object_store_bucket=str(config.object_store_bucket),
        object_store_prefix=config.object_store_prefix,
        object_store_presign_ttl_seconds=config.object_store_presign_ttl_seconds,
    )


def build_model_runtime(config: ServingConfig, model_name: str) -> ModelRuntime:
    normalized_model_name = model_name.strip().lower()
    if normalized_model_name != "trellis":
        raise ModelProviderConfigurationError(f"unsupported model: {model_name}")

    provider = build_provider(config)
    workers = build_gpu_workers(
        provider=provider,
        provider_mode=config.provider_mode,
        provider_name=config.model_provider,
        model_path=config.model_path,
        device_ids=config.gpu_device_ids,
    )
    return ModelRuntime(
        model_name=normalized_model_name,
        provider=provider,
        workers=workers,
        scheduler=GPUSlotScheduler(workers),
    )


async def run_real_mode_preflight(config: ServingConfig) -> dict[str, Any]:
    provider_mode = config.provider_mode.strip().lower()
    if provider_mode != "real":
        raise ModelProviderConfigurationError(
            "--check-real-env requires PROVIDER_MODE=real"
        )

    artifact_store = build_artifact_store(config)
    await artifact_store.initialize()

    artifact_report: dict[str, Any] = {
        "mode": artifact_store.mode,
        "artifacts_dir": str(config.artifacts_dir),
    }
    if artifact_store.mode == "minio":
        artifact_report.update(
            {
                "endpoint": config.object_store_endpoint,
                "external_endpoint": config.object_store_external_endpoint,
                "bucket": config.object_store_bucket,
                "prefix": config.object_store_prefix,
                "presign_ttl_seconds": config.object_store_presign_ttl_seconds,
            }
        )

    provider_name = config.model_provider.strip().lower()
    if provider_name != "trellis2":
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER: {config.model_provider}"
        )

    provider_report = await asyncio.to_thread(
        Trellis2Provider.inspect_runtime,
        config.model_path,
        load_pipeline=True,
    )
    return {
        "provider_mode": provider_mode,
        "provider": provider_report,
        "artifact_store": artifact_report,
    }


def validate_runtime_security_config(config: ServingConfig) -> None:
    del config


def create_app(config: ServingConfig | None = None, webhook_sender=None) -> FastAPI:
    config = config or ServingConfig()
    validate_runtime_security_config(config)
    task_store = TaskStore(config.database_path)
    api_key_store = ApiKeyStore(config.database_path)
    artifact_store = build_artifact_store(config)
    model_registry = ModelRegistry(lambda model_name: build_model_runtime(config, model_name))
    rate_limiter = TokenRateLimiter(
        max_concurrent=config.rate_limit_concurrent,
        max_requests_per_hour=config.rate_limit_per_hour,
    )
    gpu_stage = GPUStage(
        delay_ms=config.queue_delay_ms,
        model_registry=model_registry,
        task_store=task_store,
    )
    pipeline = PipelineCoordinator(
        task_store=task_store,
        stages=[
            PreprocessStage(
                delay_ms=config.preprocess_delay_ms,
                download_timeout_seconds=config.preprocess_download_timeout_seconds,
                max_image_bytes=config.preprocess_max_image_bytes,
                allow_local_inputs=config.is_mock_provider,
                uploads_dir=config.uploads_dir,
                task_store=task_store,
            ),
            gpu_stage,
            ExportStage(
                model_registry=model_registry,
                artifact_store=artifact_store,
                task_store=task_store,
                delay_ms=config.mock_export_delay_ms,
            ),
        ],
        task_timeout_seconds=config.task_timeout_seconds,
        queue_max_size=config.queue_max_size,
        worker_count=len(config.gpu_device_ids),
    )
    engine = AsyncGen3DEngine(
        task_store=task_store,
        pipeline=pipeline,
        model_registry=model_registry,
        artifact_store=artifact_store,
        webhook_sender=webhook_sender,
        webhook_timeout_seconds=config.webhook_timeout_seconds,
        webhook_max_retries=config.webhook_max_retries,
        provider_mode=config.provider_mode,
        allowed_callback_domains=config.allowed_callback_domains,
        rate_limiter=rate_limiter,
        parallel_slots=len(config.gpu_device_ids),
        queue_max_size=config.queue_max_size,
        uploads_dir=config.uploads_dir,
    )
    container = AppContainer(
        config=config,
        task_store=task_store,
        api_key_store=api_key_store,
        artifact_store=artifact_store,
        model_registry=model_registry,
        pipeline=pipeline,
        engine=engine,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        config.uploads_dir.mkdir(parents=True, exist_ok=True)
        await container.task_store.initialize()
        await container.api_key_store.initialize()
        await artifact_store.initialize()
        await container.engine.start()
        yield
        await container.engine.stop()
        await container.api_key_store.close()
        await container.task_store.close()

    app = FastAPI(title=config.service_name, lifespan=lifespan)
    app.mount(
        "/static",
        StaticFiles(directory=str(STATIC_DIR)),
        name="static",
    )
    auth_scheme = HTTPBearer(auto_error=False)

    def get_container() -> AppContainer:
        return container

    def get_cursor_pagination_params(
        limit: int = Query(default=20, ge=1, le=50),
        before: datetime | None = Query(default=None),
    ) -> CursorPaginationParams:
        return CursorPaginationParams(limit=limit, before=before)

    async def require_bearer_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
        app_container: AppContainer = Depends(get_container),
    ) -> str:
        key = await app_container.api_key_store.validate_token(
            _extract_bearer_token(credentials),
            required_scope=USER_KEY_SCOPE,
        )
        if key is not None:
            return str(key["key_id"])
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    def _require_scoped_token(scope: str):
        async def dependency(
            credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
            app_container: AppContainer = Depends(get_container),
        ) -> dict[str, Any]:
            key = await app_container.api_key_store.validate_token(
                _extract_bearer_token(credentials),
                required_scope=scope,
            )
            if key is not None:
                return key
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        return dependency

    require_key_manager_token = _require_scoped_token(KEY_MANAGER_SCOPE)
    require_task_viewer_token = _require_scoped_token(TASK_VIEWER_SCOPE)
    require_metrics_token = _require_scoped_token(METRICS_SCOPE)

    def require_admin_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
        app_container: AppContainer = Depends(get_container),
    ) -> None:
        configured_token = app_container.config.admin_token
        if _is_valid_token(_extract_bearer_token(credentials), configured_token):
            return
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid admin token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(app_container: AppContainer = Depends(get_container)) -> HealthResponse:
        return HealthResponse(status="ok", service=app_container.config.service_name)

    @app.get("/readiness", response_model=HealthResponse)
    async def readiness(
        app_container: AppContainer = Depends(get_container),
    ) -> HealthResponse:
        if app_container.engine.ready:
            return HealthResponse(status="ready", service=app_container.config.service_name)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=HealthResponse(
                status="not_ready",
                service=app_container.config.service_name,
            ).model_dump(),
        )

    @app.get("/ready", response_model=HealthResponse, include_in_schema=False)
    async def ready(app_container: AppContainer = Depends(get_container)) -> HealthResponse:
        return await readiness(app_container)

    @app.get(
        "/metrics",
        response_class=PlainTextResponse,
        dependencies=[Depends(require_metrics_token)],
    )
    async def metrics(app_container: AppContainer = Depends(get_container)) -> str:
        return render_metrics(ready=app_container.engine.ready)

    @app.post(
        "/admin/privileged-keys",
        response_model=PrivilegedApiKeyCreateResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin_token)],
    )
    async def create_privileged_key(
        payload: PrivilegedApiKeyCreateRequest,
        app_container: AppContainer = Depends(get_container),
    ) -> PrivilegedApiKeyCreateResponse:
        try:
            api_key = await app_container.api_key_store.create_privileged_key(
                label=payload.label,
                scope=payload.scope,
                allowed_ips=payload.allowed_ips,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return PrivilegedApiKeyCreateResponse(**api_key)

    @app.get(
        "/admin/privileged-keys",
        response_model=list[PrivilegedApiKeyListItem],
        dependencies=[Depends(require_admin_token)],
    )
    async def list_privileged_keys(
        app_container: AppContainer = Depends(get_container),
    ) -> list[PrivilegedApiKeyListItem]:
        api_keys = await app_container.api_key_store.list_privileged_keys()
        return [PrivilegedApiKeyListItem(**api_key) for api_key in api_keys]

    @app.delete(
        "/admin/privileged-keys/{key_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin_token)],
    )
    async def delete_privileged_key(
        key_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> Response:
        revoked = await app_container.api_key_store.revoke_privileged_key(key_id)
        if not revoked:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="privileged token not found",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post(
        "/admin/keys",
        response_model=AdminApiKeyCreateResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_key_manager_token)],
    )
    async def create_admin_key(
        payload: AdminApiKeyCreateRequest,
        app_container: AppContainer = Depends(get_container),
    ) -> AdminApiKeyCreateResponse:
        try:
            api_key = await app_container.api_key_store.create_user_key(payload.label)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return AdminApiKeyCreateResponse(**api_key)

    @app.get(
        "/admin/keys",
        response_model=list[AdminApiKeyListItem],
        dependencies=[Depends(require_key_manager_token)],
    )
    async def list_admin_keys(
        app_container: AppContainer = Depends(get_container),
    ) -> list[AdminApiKeyListItem]:
        api_keys = await app_container.api_key_store.list_user_keys()
        return [AdminApiKeyListItem(**api_key) for api_key in api_keys]

    @app.patch(
        "/admin/keys/{key_id}",
        response_model=AdminApiKeyListItem,
        dependencies=[Depends(require_key_manager_token)],
    )
    async def set_admin_key_active(
        key_id: str,
        payload: AdminApiKeySetActiveRequest,
        app_container: AppContainer = Depends(get_container),
    ) -> AdminApiKeyListItem:
        updated = await app_container.api_key_store.set_active(
            key_id,
            payload.is_active,
        )
        if not updated:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="api key not found",
            )
        api_key = await app_container.api_key_store.get_user_key(key_id)
        if api_key is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="api key not found",
            )
        return AdminApiKeyListItem(**api_key)

    @app.post(
        "/v1/upload",
        response_model=UploadImageResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_image(
        request: Request,
        key_id: str = Depends(require_bearer_token),
        app_container: AppContainer = Depends(get_container),
    ) -> UploadImageResponse:
        del key_id
        _, content_type, payload = await _extract_uploaded_file(request)
        content_type = content_type.strip().lower()
        extension = ALLOWED_UPLOAD_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "unsupported file type; allowed content types: "
                    "image/jpeg, image/png, image/webp, image/gif"
                ),
            )

        if len(payload) > app_container.config.preprocess_max_image_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "uploaded file exceeds max size of "
                    f"{app_container.config.preprocess_max_image_bytes} bytes"
                ),
            )

        upload_id = uuid.uuid4().hex
        destination = app_container.config.uploads_dir / f"{upload_id}{extension}"
        await asyncio.to_thread(destination.write_bytes, payload)
        return UploadImageResponse(
            upload_id=upload_id,
            url=f"upload://{upload_id}",
        )

    @app.post(
        "/v1/tasks",
        response_model=TaskCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_task(
        payload: TaskCreateRequest,
        response: Response,
        key_id: str = Depends(require_bearer_token),
        app_container: AppContainer = Depends(get_container),
    ) -> TaskCreateResponse:
        if not payload.input_url.startswith("upload://"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="input_url must start with upload://",
            )
        try:
            sequence, created = await app_container.engine.submit_task(
                task_type=task_type_from_request(payload.type),
                image_url=payload.input_url,
                options=payload.options.model_dump(exclude_none=True),
                callback_url=payload.callback_url,
                idempotency_key=payload.idempotency_key,
                key_id=key_id,
                model=payload.model,
            )
        except TaskSubmissionValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        except RateLimitExceededError as exc:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=str(exc),
            ) from exc
        except PipelineQueueFullError as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "queue_full",
                    "message": str(exc),
                },
            ) from exc
        response.status_code = (
            status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )
        return TaskCreateResponse.from_sequence(sequence)

    @app.get(
        "/v1/tasks",
        response_model=TaskListResponse,
    )
    async def list_tasks(
        key_id: str = Depends(require_bearer_token),
        pagination: CursorPaginationParams = Depends(get_cursor_pagination_params),
        app_container: AppContainer = Depends(get_container),
    ) -> TaskListResponse:
        page = await app_container.engine.list_tasks(
            key_id=key_id,
            limit=pagination.limit,
            before=pagination.before,
        )
        return TaskListResponse(
            items=[TaskSummary.from_sequence(task) for task in page.items],
            has_more=page.has_more,
            next_cursor=page.next_cursor,
        )

    @app.get(
        "/admin/tasks",
        response_model=TaskListResponse,
        dependencies=[Depends(require_task_viewer_token)],
    )
    async def list_admin_tasks(
        key_id: str | None = Query(default=None),
        pagination: CursorPaginationParams = Depends(get_cursor_pagination_params),
        app_container: AppContainer = Depends(get_container),
    ) -> TaskListResponse:
        page = await app_container.engine.list_tasks(
            key_id=key_id,
            limit=pagination.limit,
            before=pagination.before,
        )
        return TaskListResponse(
            items=[TaskSummary.from_sequence(task) for task in page.items],
            has_more=page.has_more,
            next_cursor=page.next_cursor,
        )

    @app.delete(
        "/v1/tasks/{task_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    async def delete_task(
        task_id: str,
        key_id: str = Depends(require_bearer_token),
        app_container: AppContainer = Depends(get_container),
    ) -> Response:
        sequence = await app_container.engine.get_task(task_id)
        if sequence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )
        if sequence.key_id != key_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="forbidden",
            )
        if sequence.status not in TERMINAL_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="task is not terminal and cannot be deleted",
            )

        deleted = await app_container.engine.delete_task(task_id)
        if deleted is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get(
        "/v1/tasks/{task_id}",
        response_model=TaskResponse,
        dependencies=[Depends(require_bearer_token)],
    )
    async def get_task(
        task_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> TaskResponse:
        sequence = await app_container.engine.get_task(task_id)
        if sequence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )
        return TaskResponse.from_sequence(sequence)

    @app.get(
        "/v1/tasks/{task_id}/events",
        dependencies=[Depends(require_bearer_token)],
    )
    async def task_events(
        task_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> StreamingResponse:
        sequence = await app_container.engine.get_task(task_id)
        if sequence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )

        async def event_stream():
            async for event in app_container.engine.stream_events(task_id):
                yield (
                    f"event: {event['event']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @app.post(
        "/v1/tasks/{task_id}/cancel",
        response_model=TaskResponse,
        dependencies=[Depends(require_bearer_token)],
    )
    async def cancel_task(
        task_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> TaskResponse:
        result = await app_container.engine.cancel_task(task_id)
        if result.sequence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )
        if result.outcome == "already_terminal":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"task already in terminal status: {result.sequence.status.value}",
            )
        if result.outcome == "not_cancellable":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"task cannot be cancelled in status: {result.sequence.status.value}",
            )
        return TaskResponse.from_sequence(result.sequence)

    @app.get(
        "/v1/tasks/{task_id}/artifacts",
        response_model=TaskArtifactsResponse,
        dependencies=[Depends(require_bearer_token)],
    )
    async def get_artifacts(
        task_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> TaskArtifactsResponse:
        sequence = await app_container.engine.get_task(task_id)
        if sequence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )
        if sequence.status != TaskStatus.SUCCEEDED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="artifacts are only available for succeeded tasks",
            )
        artifacts = await app_container.engine.get_artifacts(task_id)
        return TaskArtifactsResponse(
            artifacts=artifacts or [],
        )

    @app.get(
        "/v1/tasks/{task_id}/artifacts/{filename}",
    )
    async def download_artifact(
        task_id: str,
        filename: str,
        app_container: AppContainer = Depends(get_container),
    ) -> FileResponse:
        sequence = await app_container.engine.get_task(task_id)
        if sequence is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="task not found",
            )
        if sequence.status != TaskStatus.SUCCEEDED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="artifacts are only available for succeeded tasks",
            )
        artifact_path = await app_container.artifact_store.get_local_artifact_path(
            task_id,
            filename,
        )
        if artifact_path is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="artifact not found",
            )
        return FileResponse(path=artifact_path, filename=artifact_path.name)

    @app.get("/", include_in_schema=False)
    async def root() -> Response:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return app


def _extract_bearer_token(
    credentials: HTTPAuthorizationCredentials | None,
) -> str | None:
    if credentials is None or credentials.scheme.lower() != "bearer":
        return None
    token = credentials.credentials.strip()
    return token or None


def _is_valid_token(provided_token: str | None, configured_token: str | None) -> bool:
    return (
        provided_token is not None
        and configured_token is not None
        and secrets.compare_digest(provided_token, configured_token)
    )


async def _extract_uploaded_file(request: Request) -> tuple[str, str, bytes]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content-type must be multipart/form-data",
        )

    body = await request.body()
    message = BytesParser(policy=default_email_policy).parsebytes(
        (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("utf-8")
        + body
    )
    if not message.is_multipart():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid multipart form payload",
        )

    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = part.get_filename() or "upload"
        part_content_type = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        return filename, part_content_type, payload

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="multipart form must include a file field",
    )
