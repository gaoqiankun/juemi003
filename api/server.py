from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles

from gen3d.api.schemas import (
    HealthResponse,
    TaskArtifactsResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskResponse,
    task_type_from_request,
)
from gen3d.config import ServingConfig, ServingConfigurationError
from gen3d.engine.async_engine import AsyncGen3DEngine
from gen3d.engine.pipeline import PipelineCoordinator, PipelineQueueFullError
from gen3d.engine.sequence import TaskStatus
from gen3d.model.base import ModelProviderConfigurationError
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.observability.metrics import render_metrics
from gen3d.security import (
    RateLimitExceededError,
    TaskSubmissionValidationError,
    TokenRateLimiter,
    is_loopback_host,
)
from gen3d.stages.export.stage import ExportStage
from gen3d.stages.gpu.stage import GPUStage
from gen3d.stages.gpu.worker import build_gpu_workers
from gen3d.stages.preprocess.stage import PreprocessStage
from gen3d.storage.artifact_store import (
    ArtifactStore,
    ArtifactStoreConfigurationError,
    build_boto3_object_storage_client,
)
from gen3d.storage.task_store import TaskStore

STATIC_DIR = Path(__file__).resolve().parents[1] / "static"


@dataclass(slots=True)
class AppContainer:
    config: ServingConfig
    task_store: TaskStore
    artifact_store: ArtifactStore
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
    if config.is_mock_provider:
        return
    if not config.api_token:
        raise ServingConfigurationError(
            "API_TOKEN is required when PROVIDER_MODE != mock"
        )


def create_app(config: ServingConfig | None = None, webhook_sender=None) -> FastAPI:
    config = config or ServingConfig()
    validate_runtime_security_config(config)
    task_store = TaskStore(config.database_path)
    artifact_store = build_artifact_store(config)
    provider = build_provider(config)
    rate_limiter = TokenRateLimiter(
        max_concurrent=config.rate_limit_concurrent,
        max_requests_per_hour=config.rate_limit_per_hour,
    )
    gpu_workers = build_gpu_workers(
        provider=provider,
        provider_mode=config.provider_mode,
        provider_name=config.model_provider,
        model_path=config.model_path,
        device_ids=config.gpu_device_ids,
    )
    gpu_stage = GPUStage(
        delay_ms=config.queue_delay_ms,
        workers=gpu_workers,
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
            ),
            gpu_stage,
            ExportStage(
                provider=provider,
                artifact_store=artifact_store,
                delay_ms=config.mock_export_delay_ms,
            ),
        ],
        task_timeout_seconds=config.task_timeout_seconds,
        queue_max_size=config.queue_max_size,
        worker_count=gpu_stage.slot_count,
    )
    engine = AsyncGen3DEngine(
        task_store=task_store,
        pipeline=pipeline,
        artifact_store=artifact_store,
        webhook_sender=webhook_sender,
        webhook_timeout_seconds=config.webhook_timeout_seconds,
        webhook_max_retries=config.webhook_max_retries,
        provider_mode=config.provider_mode,
        allowed_callback_domains=config.allowed_callback_domains,
        rate_limiter=rate_limiter,
    )
    container = AppContainer(
        config=config,
        task_store=task_store,
        artifact_store=artifact_store,
        pipeline=pipeline,
        engine=engine,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.container = container
        await container.task_store.initialize()
        await artifact_store.initialize()
        await container.engine.start()
        yield
        await container.engine.stop()
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

    def require_bearer_token(
        credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
        app_container: AppContainer = Depends(get_container),
    ) -> str | None:
        configured_token = app_container.config.api_token
        if configured_token is None and app_container.config.is_mock_provider:
            return None
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or credentials.credentials != configured_token
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return credentials.credentials

    def has_valid_bearer_token(
        credentials: HTTPAuthorizationCredentials | None,
        configured_token: str | None,
    ) -> bool:
        return (
            configured_token is not None
            and credentials is not None
            and credentials.scheme.lower() == "bearer"
            and credentials.credentials == configured_token
        )

    def require_metrics_access(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(auth_scheme),
        app_container: AppContainer = Depends(get_container),
    ) -> None:
        configured_token = app_container.config.api_token
        if configured_token is None and app_container.config.is_mock_provider:
            return
        if has_valid_bearer_token(credentials, configured_token):
            return
        if is_loopback_host(request.client.host if request.client else None):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="bearer token required for metrics",
            )
        if configured_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return

    @app.get("/health", response_model=HealthResponse)
    async def health(app_container: AppContainer = Depends(get_container)) -> HealthResponse:
        return HealthResponse(status="ok", service=app_container.config.service_name)

    @app.get("/ready", response_model=HealthResponse)
    async def ready(app_container: AppContainer = Depends(get_container)) -> HealthResponse:
        readiness = "ready" if app_container.engine.ready else "ok"
        return HealthResponse(status=readiness, service=app_container.config.service_name)

    @app.get(
        "/metrics",
        response_class=PlainTextResponse,
        dependencies=[Depends(require_metrics_access)],
    )
    async def metrics(app_container: AppContainer = Depends(get_container)) -> str:
        return render_metrics(ready=app_container.engine.ready)

    @app.post(
        "/v1/tasks",
        response_model=TaskCreateResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def create_task(
        payload: TaskCreateRequest,
        response: Response,
        api_token: str | None = Depends(require_bearer_token),
        app_container: AppContainer = Depends(get_container),
    ) -> TaskCreateResponse:
        try:
            sequence, created = await app_container.engine.submit_task(
                task_type=task_type_from_request(payload.type),
                image_url=payload.image_url,
                options=payload.options.model_dump(exclude_none=True),
                callback_url=payload.callback_url,
                idempotency_key=payload.idempotency_key,
                api_token=api_token,
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
