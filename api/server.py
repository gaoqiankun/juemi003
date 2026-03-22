from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

from datetime import datetime

import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

try:
    from huggingface_hub import (
        constants as _hf_constants,
        hf_api as _hf_api_module,
        get_token as _hf_get_token,
        login as _hf_login,
        logout as _hf_logout,
        whoami as _hf_whoami,
    )
except Exception:
    _hf_constants = None
    _hf_api_module = None
    _hf_get_token = None
    _hf_login = None
    _hf_logout = None
    _hf_whoami = None

from gen3d.api.schemas import (
    AdminApiKeyCreateRequest,
    AdminApiKeyCreateResponse,
    AdminApiKeyListItem,
    AdminApiKeySetActiveRequest,
    AdminHfEndpointResponse,
    AdminHfEndpointUpdateRequest,
    AdminHfLoginRequest,
    AdminHfStatusResponse,
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
    UserModelListResponse,
    UserModelSummary,
    task_type_from_request,
)
from gen3d.config import ServingConfig
from gen3d.engine.async_engine import AsyncGen3DEngine
from gen3d.engine.model_registry import ModelRegistry, ModelRuntime
from gen3d.engine.pipeline import PipelineCoordinator, PipelineQueueFullError
from gen3d.engine.sequence import TERMINAL_STATUSES, TaskStatus
from gen3d.model.base import ModelProviderConfigurationError
from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider, MockHunyuan3DProvider
from gen3d.model.step1x3d.provider import MockStep1X3DProvider, Step1X3DProvider
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.observability.metrics import render_metrics
from gen3d.security import (
    RateLimitExceededError,
    TaskSubmissionValidationError,
    TokenRateLimiter,
)
from gen3d.stages.export.preview_renderer_service import (
    PreviewRendererService,
    PreviewRendererServiceProtocol,
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
from gen3d.storage.model_store import ModelStore
from gen3d.storage.settings_store import SettingsStore
from gen3d.storage.task_store import TaskStore

_TASK_STATUS_MAP: dict[str, str] = {
    "queued": "queued",
    "preprocessing": "queued",
    "gpu_queued": "queued",
    "gpu_ss": "live",
    "gpu_shape": "live",
    "gpu_material": "live",
    "exporting": "live",
    "uploading": "live",
    "succeeded": "completed",
    "failed": "failed",
    "cancelled": "failed",
}

HF_ENDPOINT_ENV_KEY = "HF_ENDPOINT"
HF_DEFAULT_ENDPOINT = "https://huggingface.co"
HF_ENDPOINT_SETTING_KEY = "hfEndpoint"


def _ensure_hf_client_available() -> None:
    if not all(callable(item) for item in (_hf_get_token, _hf_login, _hf_logout, _hf_whoami)):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="huggingface_hub is not available",
        )


def _normalize_hf_endpoint(raw_value: Any, *, strict: bool) -> str:
    endpoint = str(raw_value or "").strip()
    if not endpoint:
        return HF_DEFAULT_ENDPOINT
    parsed = urlsplit(endpoint)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        if strict:
            raise ValueError("endpoint must be a valid http(s) URL")
        return HF_DEFAULT_ENDPOINT
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, normalized_path, "", ""))


def _set_hf_endpoint(endpoint: str) -> str:
    normalized_endpoint = _normalize_hf_endpoint(endpoint, strict=False)
    os.environ[HF_ENDPOINT_ENV_KEY] = normalized_endpoint
    if _hf_constants is not None:
        try:
            _hf_constants.ENDPOINT = normalized_endpoint
        except Exception:
            pass
    if _hf_api_module is not None:
        try:
            _hf_api_module.ENDPOINT = normalized_endpoint
            api_client = getattr(_hf_api_module, "api", None)
            if api_client is not None:
                api_client.endpoint = normalized_endpoint
        except Exception:
            pass
    return normalized_endpoint


def _current_hf_endpoint() -> str:
    return _normalize_hf_endpoint(os.environ.get(HF_ENDPOINT_ENV_KEY, HF_DEFAULT_ENDPOINT), strict=False)


def _resolve_hf_status() -> tuple[bool, str | None]:
    _ensure_hf_client_available()
    token = _hf_get_token()
    if not token:
        return False, None
    try:
        profile = _hf_whoami(token=token)
    except Exception:
        return False, None
    profile_dict = profile if isinstance(profile, dict) else {}
    username = str(profile_dict.get("name") or "").strip()
    return True, username or None


def _map_task_status(backend_status: str) -> str:
    return _TASK_STATUS_MAP.get(backend_status, "queued")


def _short_key_id(key_id: str | None) -> str:
    normalized = str(key_id or "").strip()
    if not normalized:
        return "-"
    if len(normalized) <= 8:
        return normalized
    return f"{normalized[:8]}…"


def _resolve_task_owner(
    key_id: str | None,
    key_label_map: dict[str, str],
) -> tuple[str, str]:
    normalized_key_id = str(key_id or "").strip()
    if not normalized_key_id:
        return "-", ""
    label = key_label_map.get(normalized_key_id, "").strip()
    if label:
        return label, label
    return _short_key_id(normalized_key_id), ""


async def _build_user_key_label_map(
    api_key_store: ApiKeyStore,
) -> dict[str, str]:
    try:
        api_keys = await api_key_store.list_user_keys()
    except Exception:
        return {}
    label_map: dict[str, str] = {}
    for api_key in api_keys:
        key_id = str(api_key.get("key_id") or "").strip()
        label = str(api_key.get("label") or "").strip()
        if key_id and label:
            label_map[key_id] = label
    return label_map


def _friendly_model_error_message(error: Exception | None) -> str:
    raw_message = str(error or "").strip()
    lowered = raw_message.lower()
    if (
        "401" in lowered
        or "403" in lowered
        or "unauthorized" in lowered
        or "forbidden" in lowered
    ):
        return "模型需要授权访问，请配置 HuggingFace Token"
    if "timeout" in lowered or "connectionerror" in lowered or "connection error" in lowered:
        return "模型下载超时，请检查网络连接"
    if "no space left" in lowered or "disk" in lowered:
        return "磁盘空间不足"
    if "cuda out of memory" in lowered or " oom" in lowered or lowered == "oom":
        return "GPU 显存不足"
    if "path does not exist" in lowered:
        return "模型路径不存在，请检查配置"
    return raw_message or "模型加载失败"


async def _safe_record_usage(api_key_store: ApiKeyStore, key_id: str) -> None:
    try:
        await api_key_store.record_usage(key_id)
    except Exception:
        pass


WEB_DIST_DIR = Path(__file__).resolve().parents[1] / "web" / "dist"
SPA_INDEX_PATH = WEB_DIST_DIR / "index.html"
ALLOWED_UPLOAD_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
PROXY_REQUEST_HEADER_EXCLUSIONS = HOP_BY_HOP_HEADERS | {"host", "content-length"}
ARTIFACT_STREAM_CHUNK_SIZE = 1024 * 1024
_preview_rendering: set[str] = set()
_preview_render_tasks: set[asyncio.Task[None]] = set()
_logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class AppContainer:
    config: ServingConfig
    task_store: TaskStore
    api_key_store: ApiKeyStore
    rate_limiter: TokenRateLimiter
    artifact_store: ArtifactStore
    preview_renderer_service: PreviewRendererServiceProtocol
    model_registry: ModelRegistry
    pipeline: PipelineCoordinator
    engine: AsyncGen3DEngine
    model_store: ModelStore
    settings_store: SettingsStore


class SPAStaticFiles(StaticFiles):
    def __init__(self, *args, spa_index_path: Path, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._spa_index_path = spa_index_path

    async def get_response(self, path: str, scope: Scope) -> Response:
        fallback = None
        normalized_path = path.strip("/.")
        request_path = f"/{normalized_path}" if normalized_path else "/"
        if (
            scope.get("method") in {"GET", "HEAD"}
            and self._spa_index_path.is_file()
            and _should_serve_static_spa_route(request_path)
        ):
            fallback = FileResponse(self._spa_index_path)
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND or fallback is None:
                raise
            return fallback
        if response.status_code == status.HTTP_404_NOT_FOUND and fallback is not None:
            return fallback
        return response


def _extract_artifact_filename(path: str) -> str | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) != 5:
        return None
    if parts[0] != "v1" or parts[1] != "tasks" or parts[3] != "artifacts":
        return None
    return parts[4]


def _resolve_dev_local_model_path(config: ServingConfig, filename: str | None) -> Path | None:
    if config.dev_proxy_target is None or filename is None:
        return None
    if Path(filename).name.lower() != "model.glb":
        return None
    if config.dev_local_model_path is None:
        return None
    candidate = config.dev_local_model_path.expanduser()
    if not candidate.is_absolute():
        candidate = (Path(__file__).resolve().parents[1] / candidate).resolve()
    if not candidate.is_file():
        return None
    return candidate


def build_provider(config: ServingConfig):
    provider_name = config.model_provider.strip().lower()
    provider_mode = config.provider_mode.strip().lower()

    if provider_name == "trellis2":
        if provider_mode == "mock":
            return MockTrellis2Provider(stage_delay_ms=config.mock_gpu_stage_delay_ms)
        if provider_mode == "real":
            return Trellis2Provider.from_pretrained(config.model_path)
    elif provider_name == "hunyuan3d":
        if provider_mode == "mock":
            return MockHunyuan3DProvider(stage_delay_ms=config.mock_gpu_stage_delay_ms)
        if provider_mode == "real":
            return Hunyuan3DProvider.from_pretrained(config.model_path)
    elif provider_name == "step1x3d":
        if provider_mode == "mock":
            return MockStep1X3DProvider(stage_delay_ms=config.mock_gpu_stage_delay_ms)
        if provider_mode == "real":
            return Step1X3DProvider.from_pretrained(config.model_path)
    else:
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER: {config.model_provider}"
        )

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
    normalized_model_name = str(model_name).strip().lower() or "trellis"

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


def _artifact_file_name_from_url(value: Any) -> str | None:
    if not value:
        return None
    return Path(urlsplit(str(value)).path).name or None


def _artifact_matches_file_name(
    artifact: dict[str, Any],
    file_name: str,
) -> bool:
    return _artifact_file_name_from_url(artifact.get("url")) == file_name


async def _artifact_exists(
    artifact_store: ArtifactStore,
    *,
    task_id: str,
    file_name: str,
) -> bool:
    if artifact_store.mode == "local":
        return await artifact_store.get_local_artifact_path(task_id, file_name) is not None

    artifacts = await artifact_store.list_artifacts(task_id)
    return any(
        _artifact_matches_file_name(artifact, file_name)
        for artifact in artifacts
    )


def _merge_preview_artifacts(
    existing_artifacts: list[dict[str, Any]],
    preview_artifact: dict[str, Any],
) -> list[dict[str, Any]]:
    artifacts_without_preview = [
        artifact
        for artifact in existing_artifacts
        if not _artifact_matches_file_name(artifact, "preview.png")
    ]
    primary_artifacts = [
        artifact
        for artifact in artifacts_without_preview
        if artifact.get("type") == "glb" or _artifact_matches_file_name(artifact, "model.glb")
    ]
    primary_artifact_ids = {id(artifact) for artifact in primary_artifacts}
    remaining_artifacts = [
        artifact
        for artifact in artifacts_without_preview
        if id(artifact) not in primary_artifact_ids
    ]
    return ExportStage._merge_artifacts(
        primary_artifacts=primary_artifacts,
        supplemental_artifacts=[preview_artifact],
        existing_artifacts=remaining_artifacts,
    )


async def _render_preview_artifact_on_demand(
    task_id: str,
    artifact_store: ArtifactStore,
    preview_renderer_service: PreviewRendererServiceProtocol,
) -> None:
    model_path: Path | None = None
    preview_staging_path: Path | None = None
    model_is_temporary = False
    try:
        if await _artifact_exists(
            artifact_store,
            task_id=task_id,
            file_name="preview.png",
        ):
            return

        existing_artifacts = await artifact_store.list_artifacts(task_id)
        model_download = await artifact_store.prepare_download(task_id, "model.glb")
        if model_download is None:
            return

        model_path, _, model_is_temporary = model_download
        preview_staging_path = await asyncio.to_thread(
            ExportStage._create_preview_temp_path,
            model_path,
        )
        preview_png = await preview_renderer_service.render_preview_png(
            model_path=model_path,
        )
        await asyncio.to_thread(preview_staging_path.write_bytes, preview_png)
        preview_artifact = await artifact_store.publish_artifact(
            task_id=task_id,
            artifact_type="preview",
            file_name="preview.png",
            staging_path=preview_staging_path,
            content_type="image/png",
        )
        await artifact_store.replace_artifacts(
            task_id,
            _merge_preview_artifacts(existing_artifacts, preview_artifact),
        )
    except Exception as exc:
        _logger.warning(
            "artifact.preview_render_failed",
            task_id=task_id,
            error=str(exc),
        )
    finally:
        if preview_staging_path is not None and preview_staging_path.exists():
            await asyncio.to_thread(_cleanup_temporary_artifact, preview_staging_path)
        if model_path is not None and model_is_temporary:
            await asyncio.to_thread(_cleanup_temporary_artifact, model_path)
        _preview_rendering.discard(task_id)


def _dispatch_preview_render(
    task_id: str,
    artifact_store: ArtifactStore,
    preview_renderer_service: PreviewRendererServiceProtocol,
) -> None:
    if task_id in _preview_rendering:
        return

    _preview_rendering.add(task_id)
    try:
        task = asyncio.create_task(
            _render_preview_artifact_on_demand(
                task_id,
                artifact_store,
                preview_renderer_service,
            ),
        )
    except Exception as exc:
        _preview_rendering.discard(task_id)
        _logger.warning(
            "artifact.preview_render_schedule_failed",
            task_id=task_id,
            error=str(exc),
        )
        return

    _preview_render_tasks.add(task)
    task.add_done_callback(_preview_render_tasks.discard)


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


def create_app(
    config: ServingConfig | None = None,
    webhook_sender=None,
    preview_renderer_service: PreviewRendererServiceProtocol | None = None,
) -> FastAPI:
    config = config or ServingConfig()
    validate_runtime_security_config(config)
    task_store = TaskStore(config.database_path)
    api_key_store = ApiKeyStore(config.database_path)
    model_store = ModelStore(config.database_path)
    settings_store = SettingsStore(config.database_path)
    artifact_store = build_artifact_store(config)
    preview_renderer_service = preview_renderer_service or PreviewRendererService()
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
                artifact_store=artifact_store,
                task_store=task_store,
            ),
            gpu_stage,
            ExportStage(
                model_registry=model_registry,
                artifact_store=artifact_store,
                preview_renderer_service=preview_renderer_service,
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
        startup_models=("trellis",),
    )
    container = AppContainer(
        config=config,
        task_store=task_store,
        api_key_store=api_key_store,
        rate_limiter=rate_limiter,
        artifact_store=artifact_store,
        preview_renderer_service=preview_renderer_service,
        model_registry=model_registry,
        pipeline=pipeline,
        engine=engine,
        model_store=model_store,
        settings_store=settings_store,
    )
    proxy_client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal proxy_client
        app.state.container = container
        config.uploads_dir.mkdir(parents=True, exist_ok=True)
        await container.task_store.initialize()
        await container.api_key_store.initialize()
        await container.model_store.initialize()
        await container.settings_store.initialize()
        configured_hf_endpoint = await container.settings_store.get(HF_ENDPOINT_SETTING_KEY)
        _set_hf_endpoint(
            _normalize_hf_endpoint(configured_hf_endpoint, strict=False)
        )
        await artifact_store.initialize()
        await preview_renderer_service.start()
        if config.dev_proxy_target is not None:
            proxy_client = httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0),
            )
        await container.engine.start()
        yield
        await container.engine.stop()
        await preview_renderer_service.stop()
        if proxy_client is not None:
            await proxy_client.aclose()
        await container.settings_store.close()
        await container.model_store.close()
        await container.api_key_store.close()
        await container.task_store.close()

    app = FastAPI(title=config.service_name, lifespan=lifespan)
    auth_scheme = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def maybe_proxy_dev_requests(request: Request, call_next):
        _rewrite_legacy_api_path(request.scope)
        if not _should_proxy_dev_request(request, config):
            return await call_next(request)
        if proxy_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="dev proxy client is not ready",
            )
        return await _forward_dev_proxy_request(
            request=request,
            proxy_client=proxy_client,
            proxy_target=config.dev_proxy_target,
        )

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
        "/api/admin/privileged-keys",
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
        "/api/admin/privileged-keys",
        response_model=list[PrivilegedApiKeyListItem],
        dependencies=[Depends(require_admin_token)],
    )
    async def list_privileged_keys(
        app_container: AppContainer = Depends(get_container),
    ) -> list[PrivilegedApiKeyListItem]:
        api_keys = await app_container.api_key_store.list_privileged_keys()
        return [PrivilegedApiKeyListItem(**api_key) for api_key in api_keys]

    @app.delete(
        "/api/admin/privileged-keys/{key_id}",
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
        "/api/admin/keys",
        response_model=AdminApiKeyCreateResponse,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin_token)],
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
        "/api/admin/keys",
        response_model=list[AdminApiKeyListItem],
        dependencies=[Depends(require_admin_token)],
    )
    async def list_admin_keys(
        app_container: AppContainer = Depends(get_container),
    ) -> list[AdminApiKeyListItem]:
        api_keys = await app_container.api_key_store.list_user_keys()
        return [AdminApiKeyListItem(**api_key) for api_key in api_keys]

    @app.patch(
        "/api/admin/keys/{key_id}",
        response_model=AdminApiKeyListItem,
        dependencies=[Depends(require_admin_token)],
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

    @app.delete(
        "/api/admin/keys/{key_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Depends(require_admin_token)],
    )
    async def delete_admin_key(
        key_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> Response:
        deleted = await app_container.api_key_store.revoke_user_key(key_id)
        if not deleted:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="api key not found",
            )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

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

    @app.get(
        "/v1/models",
        response_model=UserModelListResponse,
    )
    async def list_enabled_models(
        key_id: str = Depends(require_bearer_token),
        app_container: AppContainer = Depends(get_container),
    ) -> UserModelListResponse:
        del key_id
        enabled_models = await app_container.model_store.get_enabled_models()
        return UserModelListResponse(
            models=[
                UserModelSummary(
                    id=str(model["id"]),
                    display_name=str(model["display_name"]),
                    is_default=bool(model["is_default"]),
                )
                for model in enabled_models
            ]
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
        normalized_model = str(payload.model).strip().lower() or "trellis"
        model_definition = await app_container.model_store.get_model(normalized_model)
        if model_definition is not None and not bool(model_definition.get("is_enabled")):
            raise HTTPException(
                status_code=422,
                detail="该模型已被管理员禁用",
            )
        try:
            sequence, created = await app_container.engine.submit_task(
                task_type=task_type_from_request(payload.type),
                image_url=payload.input_url,
                options=payload.options.model_dump(exclude_none=True),
                callback_url=payload.callback_url,
                idempotency_key=payload.idempotency_key,
                key_id=key_id,
                model=normalized_model,
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
        asyncio.create_task(_safe_record_usage(app_container.api_key_store, key_id))
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
        "/api/admin/tasks",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_admin_tasks(
        key_id: str | None = Query(default=None),
        pagination: CursorPaginationParams = Depends(get_cursor_pagination_params),
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        page = await app_container.engine.list_tasks(
            key_id=key_id,
            limit=pagination.limit,
            before=pagination.before,
        )
        response = TaskListResponse(
            items=[TaskSummary.from_sequence(task) for task in page.items],
            has_more=page.has_more,
            next_cursor=page.next_cursor,
        ).model_dump(by_alias=True, mode="json")
        key_label_map = await _build_user_key_label_map(app_container.api_key_store)
        items = response.get("items", [])
        for index, sequence in enumerate(page.items):
            if index >= len(items):
                break
            owner, key_label = _resolve_task_owner(sequence.key_id, key_label_map)
            items[index]["keyId"] = str(sequence.key_id or "")
            items[index]["keyLabel"] = key_label
            items[index]["owner"] = owner
        return response

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
    ) -> Response:
        local_model_path = _resolve_dev_local_model_path(app_container.config, filename)
        if local_model_path is not None:
            return FileResponse(
                path=local_model_path,
                filename=Path(filename).name,
                media_type="model/gltf-binary",
            )

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
        streaming_download = await app_container.artifact_store.open_streaming_download(
            task_id,
            filename,
        )
        if streaming_download is not None:
            headers = _build_artifact_download_headers(
                file_name=streaming_download.file_name,
                content_length=streaming_download.content_length,
                etag=streaming_download.etag,
            )

            async def stream_artifact():
                try:
                    while True:
                        chunk = await asyncio.to_thread(
                            streaming_download.body.read,
                            ARTIFACT_STREAM_CHUNK_SIZE,
                        )
                        if not chunk:
                            break
                        yield chunk
                finally:
                    await asyncio.to_thread(streaming_download.body.close)

            return StreamingResponse(
                stream_artifact(),
                media_type=streaming_download.content_type,
                headers=headers,
            )

        artifact_download = await app_container.artifact_store.prepare_download(
            task_id,
            filename,
        )
        if artifact_download is None:
            if Path(filename).name.lower() == "preview.png" and await _artifact_exists(
                app_container.artifact_store,
                task_id=task_id,
                file_name="model.glb",
            ):
                _dispatch_preview_render(
                    task_id,
                    app_container.artifact_store,
                    app_container.preview_renderer_service,
                )
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="artifact not found",
            )
        artifact_path, content_type, is_temporary = artifact_download
        background = BackgroundTask(_cleanup_temporary_artifact, artifact_path) if is_temporary else None
        return FileResponse(
            path=artifact_path,
            filename=Path(filename).name,
            media_type=content_type,
            background=background,
        )

    # ------------------------------------------------------------------
    # Admin panel endpoints
    # ------------------------------------------------------------------

    @app.get(
        "/api/admin/dashboard",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_dashboard(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        task_counts = await app_container.task_store.count_tasks_by_status()
        recent = await app_container.task_store.get_recent_tasks(limit=10)
        throughput = await app_container.task_store.get_throughput_stats(hours=1)
        active = await app_container.task_store.get_active_task_count()
        key_label_map = await _build_user_key_label_map(app_container.api_key_store)

        stats = [
            {"key": "activeTasks", "value": active, "change": ""},
            {
                "key": "queued",
                "value": task_counts.get("queued", 0) + task_counts.get("gpu_queued", 0),
                "change": "",
            },
            {"key": "completed", "value": task_counts.get("succeeded", 0), "change": ""},
            {"key": "failed", "value": task_counts.get("failed", 0), "change": ""},
        ]

        gpu = {
            "model": "N/A",
            "utilization": 0,
            "vramUsedGb": 0,
            "vramTotalGb": 0,
            "temperatureC": 0,
            "powerW": 0,
            "fanPercent": 0,
            "cudaVersion": "",
            "driverVersion": "",
            "activeJobs": active,
            "avgLatencySeconds": throughput.get("avg_duration_seconds") or 0,
        }

        recent_tasks = []
        for task in recent:
            task_key_id = str(task.get("key_id") or "")
            owner, key_label = _resolve_task_owner(task_key_id, key_label_map)
            recent_tasks.append(
                {
                    "id": task["id"],
                    "subjectKey": "",
                    "model": task.get("model", ""),
                    "status": _map_task_status(task["status"]),
                    "durationSeconds": 0,
                    "createdAt": task.get("created_at", ""),
                    "owner": owner,
                    "keyId": task_key_id,
                    "keyLabel": key_label,
                }
            )

        return {
            "stats": stats,
            "gpu": gpu,
            "recentTasks": recent_tasks,
            "nodes": [],
            "workers": [],
        }

    @app.get(
        "/api/admin/tasks/stats",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_tasks_stats(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        counts = await app_container.task_store.count_tasks_by_status()
        throughput = await app_container.task_store.get_throughput_stats(hours=1)
        active = await app_container.task_store.get_active_task_count()

        overview = [
            {
                "key": "throughput",
                "value": throughput.get("completed_count", 0),
                "unit": "/h",
                "change": "",
            },
            {
                "key": "latency",
                "value": throughput.get("avg_duration_seconds") or 0,
                "unit": "s",
                "change": "",
            },
            {"key": "active", "value": active, "change": ""},
        ]
        return {"overview": overview, "countByStatus": counts}

    @app.get(
        "/api/admin/models",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_models(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        models = await app_container.model_store.list_models()
        for model in models:
            try:
                state = (
                    app_container.model_registry.get_state(model["id"])
                    if hasattr(app_container.model_registry, "get_state")
                    else "unknown"
                )
            except Exception:
                state = "unknown"
            model["runtimeState"] = state
            if state == "error":
                error = None
                try:
                    error = app_container.model_registry.get_error(model["id"])
                except Exception:
                    error = None
                model["error_message"] = _friendly_model_error_message(error)
            else:
                model["error_message"] = None

        enabled = sum(1 for m in models if m.get("is_enabled"))
        return {
            "models": models,
            "summary": {
                "total": len(models),
                "enabled": enabled,
                "disabled": len(models) - enabled,
            },
        }

    @app.post(
        "/api/admin/models",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_admin_token)],
    )
    async def create_model(
        payload: dict,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        try:
            model = await app_container.model_store.create_model(
                id=payload["id"],
                provider_type=payload["providerType"],
                display_name=payload["displayName"],
                model_path=payload["modelPath"],
                min_vram_mb=payload.get("minVramMb", 24000),
                config=payload.get("config"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return model

    @app.get(
        "/api/admin/models/{model_id}",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_model(
        model_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        model = await app_container.model_store.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        return model

    @app.patch(
        "/api/admin/models/{model_id}",
        dependencies=[Depends(require_admin_token)],
    )
    async def update_model(
        model_id: str,
        payload: dict,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        field_map = {
            "isEnabled": "is_enabled",
            "isDefault": "is_default",
            "displayName": "display_name",
            "modelPath": "model_path",
            "minVramMb": "min_vram_mb",
            "config": "config",
        }
        updates = {}
        for camel, snake in field_map.items():
            if camel in payload:
                updates[snake] = payload[camel]
        try:
            model = await app_container.model_store.update_model(model_id, **updates)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        return model

    @app.delete(
        "/api/admin/models/{model_id}",
        dependencies=[Depends(require_admin_token)],
    )
    async def delete_model(
        model_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        deleted = await app_container.model_store.delete_model(model_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="model not found")
        return {"ok": True}

    @app.get(
        "/api/admin/keys/stats",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_keys_stats(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        stats = await app_container.api_key_store.get_usage_stats()
        return stats

    @app.get(
        "/api/admin/hf-status",
        response_model=AdminHfStatusResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def get_hf_status() -> AdminHfStatusResponse:
        logged_in, username = _resolve_hf_status()
        return AdminHfStatusResponse(
            logged_in=logged_in,
            username=username,
            endpoint=_current_hf_endpoint(),
        )

    @app.patch(
        "/api/admin/hf-endpoint",
        response_model=AdminHfEndpointResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def update_hf_endpoint(
        payload: AdminHfEndpointUpdateRequest,
        app_container: AppContainer = Depends(get_container),
    ) -> AdminHfEndpointResponse:
        try:
            normalized_endpoint = _normalize_hf_endpoint(payload.endpoint, strict=True)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        _set_hf_endpoint(normalized_endpoint)
        await app_container.settings_store.set(HF_ENDPOINT_SETTING_KEY, normalized_endpoint)
        return AdminHfEndpointResponse(endpoint=normalized_endpoint)

    @app.post(
        "/api/admin/hf-login",
        response_model=AdminHfStatusResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def login_hf(payload: AdminHfLoginRequest) -> AdminHfStatusResponse:
        _ensure_hf_client_available()
        token = str(payload.token or "").strip()
        if not token:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="token must be a non-empty string",
            )
        # Keep login calls pinned to the current mirror endpoint.
        _set_hf_endpoint(_current_hf_endpoint())
        try:
            _hf_login(token=token)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        logged_in, username = _resolve_hf_status()
        return AdminHfStatusResponse(
            logged_in=logged_in,
            username=username,
            endpoint=_current_hf_endpoint(),
        )

    @app.post(
        "/api/admin/hf-logout",
        response_model=AdminHfStatusResponse,
        dependencies=[Depends(require_admin_token)],
    )
    async def logout_hf() -> AdminHfStatusResponse:
        _ensure_hf_client_available()
        try:
            _hf_logout()
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=str(exc),
            ) from exc
        return AdminHfStatusResponse(
            logged_in=False,
            username=None,
            endpoint=_current_hf_endpoint(),
        )

    @app.get(
        "/api/admin/settings",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_settings(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        db_settings = await app_container.settings_store.get_all()
        cfg = app_container.config
        model_definitions = await app_container.model_store.list_models()
        provider_options = [
            {
                "value": str(model["id"]),
                "label": str(model["display_name"]),
            }
            for model in model_definitions
            if str(model.get("id") or "").strip()
        ]
        if not provider_options:
            provider_options = [
                {
                    "value": str(cfg.model_provider),
                    "label": str(cfg.model_provider),
                }
            ]

        sections = [
            {
                "key": "generation",
                "titleKey": "settings.sections.generation.title",
                "descriptionKey": "settings.sections.generation.description",
                "fields": [
                    {
                        "key": "defaultProvider",
                        "labelKey": "settings.fields.defaultProvider.label",
                        "descriptionKey": "settings.fields.defaultProvider.description",
                        "type": "select",
                        "value": db_settings.get("defaultProvider", cfg.model_provider),
                        "options": provider_options,
                    },
                    {
                        "key": "queueMaxSize",
                        "labelKey": "settings.fields.queueMaxSize.label",
                        "descriptionKey": "settings.fields.queueMaxSize.description",
                        "type": "number",
                        "value": db_settings.get("queueMaxSize", cfg.queue_max_size),
                    },
                    {
                        "key": "rateLimitPerHour",
                        "labelKey": "settings.fields.rateLimitPerHour.label",
                        "descriptionKey": "settings.fields.rateLimitPerHour.description",
                        "type": "number",
                        "value": db_settings.get(
                            "rateLimitPerHour", cfg.rate_limit_per_hour
                        ),
                        "suffixKey": "settings.suffix.perHour",
                    },
                    {
                        "key": "rateLimitConcurrent",
                        "labelKey": "settings.fields.rateLimitConcurrent.label",
                        "descriptionKey": "settings.fields.rateLimitConcurrent.description",
                        "type": "number",
                        "value": db_settings.get(
                            "rateLimitConcurrent", cfg.rate_limit_concurrent
                        ),
                        "suffixKey": "settings.suffix.count",
                    },
                ],
            },
        ]
        return {"sections": sections}

    @app.patch(
        "/api/admin/settings",
        dependencies=[Depends(require_admin_token)],
    )
    async def update_settings(
        payload: dict,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        allowed_keys = {
            "rateLimitPerHour",
            "rateLimitConcurrent",
            "queueMaxSize",
            "defaultProvider",
        }
        updates = {k: v for k, v in payload.items() if k in allowed_keys}
        if not updates:
            raise HTTPException(
                status_code=422, detail="no updatable settings provided"
            )

        normalized_updates: dict[str, Any] = {}

        if "defaultProvider" in updates:
            default_provider = str(updates["defaultProvider"] or "").strip()
            if not default_provider:
                raise HTTPException(
                    status_code=422,
                    detail="defaultProvider must be a non-empty string",
                )
            normalized_updates["defaultProvider"] = default_provider

        if "queueMaxSize" in updates:
            try:
                queue_max_size = int(updates["queueMaxSize"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="queueMaxSize must be an integer",
                ) from exc
            if queue_max_size < 0:
                raise HTTPException(
                    status_code=422,
                    detail="queueMaxSize must be >= 0",
                )
            normalized_updates["queueMaxSize"] = queue_max_size

        if "rateLimitPerHour" in updates:
            try:
                rate_limit_per_hour = int(updates["rateLimitPerHour"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="rateLimitPerHour must be an integer",
                ) from exc
            if rate_limit_per_hour < 1:
                raise HTTPException(
                    status_code=422,
                    detail="rateLimitPerHour must be >= 1",
                )
            normalized_updates["rateLimitPerHour"] = rate_limit_per_hour

        if "rateLimitConcurrent" in updates:
            try:
                rate_limit_concurrent = int(updates["rateLimitConcurrent"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="rateLimitConcurrent must be an integer",
                ) from exc
            if rate_limit_concurrent < 1:
                raise HTTPException(
                    status_code=422,
                    detail="rateLimitConcurrent must be >= 1",
                )
            normalized_updates["rateLimitConcurrent"] = rate_limit_concurrent

        await app_container.settings_store.set_many(normalized_updates)

        if "queueMaxSize" in normalized_updates:
            app_container.engine.update_queue_capacity(normalized_updates["queueMaxSize"])

        if (
            "rateLimitConcurrent" in normalized_updates
            or "rateLimitPerHour" in normalized_updates
        ):
            await app_container.rate_limiter.update_limits(
                max_concurrent=normalized_updates.get("rateLimitConcurrent"),
                max_requests_per_hour=normalized_updates.get("rateLimitPerHour"),
            )

        return {"ok": True, "updated": list(normalized_updates.keys())}

    @app.get("/", include_in_schema=False)
    async def spa_root() -> Response:
        if SPA_INDEX_PATH.is_file():
            return FileResponse(SPA_INDEX_PATH)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/static", include_in_schema=False)
    async def static_root_redirect() -> Response:
        return RedirectResponse(url="/", status_code=status.HTTP_308_PERMANENT_REDIRECT)

    @app.get("/static/{spa_path:path}", include_in_schema=False)
    async def static_compat_redirect(spa_path: str) -> Response:
        target = f"/{spa_path.lstrip('/')}" if spa_path else "/"
        return RedirectResponse(url=target, status_code=status.HTTP_308_PERMANENT_REDIRECT)

    app.mount(
        "/",
        SPAStaticFiles(
            directory=str(WEB_DIST_DIR),
            check_dir=False,
            spa_index_path=SPA_INDEX_PATH,
        ),
        name="spa",
    )

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


def _should_proxy_dev_request(request: Request, config: ServingConfig) -> bool:
    if config.dev_proxy_target is None:
        return False
    path = request.url.path
    if path.startswith("/static") or path.startswith("/assets/") or path == "/favicon.svg":
        return False
    if _resolve_dev_local_model_path(config, _extract_artifact_filename(path)) is not None:
        return False
    return (
        path.startswith("/v1/")
        or path.startswith("/api/")
        or path in {"/health", "/readiness", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}
    )


def _cleanup_temporary_artifact(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _build_artifact_download_headers(
    *,
    file_name: str,
    content_length: int | None = None,
    etag: str | None = None,
) -> dict[str, str]:
    safe_name = Path(file_name).name or "artifact"
    headers = {
        "Content-Disposition": f"attachment; filename*=utf-8''{quote(safe_name)}",
    }
    if content_length is not None and content_length >= 0:
        headers["Content-Length"] = str(content_length)
    if etag:
        headers["ETag"] = str(etag)
    return headers


def _should_serve_static_spa_route(path: str) -> bool:
    normalized = path.strip() or "/"
    if normalized in {"/", ""}:
        return True
    if normalized.startswith("/api/") or normalized.startswith("/v1/"):
        return False
    if normalized in {"/health", "/readiness", "/ready", "/metrics", "/docs", "/redoc", "/openapi.json"}:
        return False
    if normalized.startswith("/assets/"):
        return False
    return "." not in normalized.rsplit("/", 1)[-1]


def _rewrite_legacy_api_path(scope: Scope) -> None:
    path = scope.get("path", "")
    if not isinstance(path, str):
        return
    if path == "/api/v1" or path.startswith("/api/v1/"):
        rewritten_path = path[4:]
        scope["path"] = rewritten_path
        scope["raw_path"] = rewritten_path.encode("utf-8")


async def _forward_dev_proxy_request(
    *,
    request: Request,
    proxy_client: httpx.AsyncClient,
    proxy_target: str | None,
) -> Response:
    if proxy_target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not found")

    upstream_request = proxy_client.build_request(
        method=request.method,
        url=_build_dev_proxy_url(proxy_target, request),
        headers=_build_proxy_request_headers(request),
        content=await request.body(),
    )
    try:
        upstream_response = await proxy_client.send(upstream_request, stream=True)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"dev proxy request failed: {exc}",
        ) from exc

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=_build_proxy_response_headers(upstream_response),
        background=BackgroundTask(upstream_response.aclose),
    )


def _build_dev_proxy_url(proxy_target: str, request: Request) -> str:
    target = urlsplit(proxy_target)
    target_path = target.path.rstrip("/")
    if not target_path.startswith("/") and target_path:
        target_path = f"/{target_path}"
    combined_path = f"{target_path}{request.url.path}" if target_path else request.url.path
    if not combined_path.startswith("/"):
        combined_path = f"/{combined_path}"
    return urlunsplit(
        (
            target.scheme,
            target.netloc,
            combined_path,
            request.url.query,
            "",
        )
    )


def _build_proxy_request_headers(request: Request) -> list[tuple[str, str]]:
    headers: list[tuple[str, str]] = []
    for name, value in request.headers.raw:
        decoded_name = name.decode("latin-1")
        if decoded_name.lower() in PROXY_REQUEST_HEADER_EXCLUSIONS:
            continue
        headers.append((decoded_name, value.decode("latin-1")))
    return headers


def _build_proxy_response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        name: value
        for name, value in response.headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS
    }


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
