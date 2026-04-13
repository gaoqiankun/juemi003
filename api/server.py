from __future__ import annotations

import asyncio
import json
import os
import secrets
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from email.parser import BytesParser
from email.policy import default as default_email_policy
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import structlog
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

try:
    from huggingface_hub import (
        constants as _hf_constants,
    )
    from huggingface_hub import (
        get_token as _hf_get_token,
    )
    from huggingface_hub import (
        hf_api as _hf_api_module,
    )
    from huggingface_hub import (
        login as _hf_login,
    )
    from huggingface_hub import (
        logout as _hf_logout,
    )
    from huggingface_hub import (
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
    TaskArtifactsResponse,
    TaskCreateRequest,
    TaskCreateResponse,
    TaskListResponse,
    TaskResponse,
    TaskSummary,
    UploadImageResponse,
    UserModelListResponse,
    UserModelSummary,
    task_type_from_request,
)
from gen3d.config import ServingConfig
from gen3d.engine.async_engine import AsyncGen3DEngine
from gen3d.engine.model_registry import ModelRegistry, ModelRuntime
from gen3d.engine.model_scheduler import ModelScheduler
from gen3d.engine.pipeline import PipelineCoordinator, PipelineQueueFullError
from gen3d.engine.sequence import TERMINAL_STATUSES, TaskStatus
from gen3d.engine.vram_allocator import (
    VRAMAllocator,
    VRAMAllocatorError,
    VRAMMetricsHook,
)
from gen3d.engine.weight_manager import WeightManager, get_provider_deps
from gen3d.model.base import ModelProviderConfigurationError
from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider, MockHunyuan3DProvider
from gen3d.model.step1x3d.provider import MockStep1X3DProvider, Step1X3DProvider
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider
from gen3d.observability.metrics import (
    increment_vram_acquire_inference,
    increment_vram_evict,
    initialize_vram_metrics,
    observe_vram_acquire_inference_wait,
    render_metrics,
)
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
from gen3d.storage.api_key_store import (
    KEY_MANAGER_SCOPE,
    METRICS_SCOPE,
    TASK_VIEWER_SCOPE,
    USER_KEY_SCOPE,
    ApiKeyStore,
)
from gen3d.storage.artifact_store import (
    ArtifactStore,
    ArtifactStoreConfigurationError,
    build_boto3_object_storage_client,
)
from gen3d.storage.dep_store import DepInstanceStore, ModelDepRequirementsStore
from gen3d.storage.model_store import ModelStore
from gen3d.storage.settings_store import (
    EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    GPU_DISABLED_DEVICES_KEY,
    INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    MAX_LOADED_MODELS_KEY,
    MAX_TASKS_PER_SLOT_KEY,
    SettingsStore,
)
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
        return True, None
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
    all_device_ids: tuple[str, ...]
    disabled_devices: set[str]
    task_store: TaskStore
    api_key_store: ApiKeyStore
    rate_limiter: TokenRateLimiter
    artifact_store: ArtifactStore
    preview_renderer_service: PreviewRendererServiceProtocol
    model_registry: ModelRegistry
    pipeline: PipelineCoordinator
    engine: AsyncGen3DEngine
    model_store: ModelStore
    dep_instance_store: DepInstanceStore
    model_dep_requirements_store: ModelDepRequirementsStore
    settings_store: SettingsStore
    vram_allocator: VRAMAllocator
    model_scheduler: ModelScheduler
    weight_manager: WeightManager
    model_download_tasks: dict[str, asyncio.Task[None]]


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


def build_provider(
    provider_name: str,
    provider_mode: str,
    model_path: str,
    mock_delay_ms: int = 60,
):
    provider_name = str(provider_name).strip().lower()
    provider_mode = str(provider_mode).strip().lower()
    model_path = str(model_path).strip()

    if provider_name == "trellis2":
        if provider_mode == "mock":
            return MockTrellis2Provider(stage_delay_ms=mock_delay_ms)
        if provider_mode == "real":
            return Trellis2Provider.metadata_only(model_path)
    elif provider_name == "hunyuan3d":
        if provider_mode == "mock":
            return MockHunyuan3DProvider(stage_delay_ms=mock_delay_ms)
        if provider_mode == "real":
            return Hunyuan3DProvider.metadata_only(model_path)
    elif provider_name == "step1x3d":
        if provider_mode == "mock":
            return MockStep1X3DProvider(stage_delay_ms=mock_delay_ms)
        if provider_mode == "real":
            return Step1X3DProvider.metadata_only(model_path)
    else:
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER: {provider_name}"
        )

    raise ModelProviderConfigurationError(
        f"unsupported PROVIDER_MODE: {provider_mode}"
    )


def _provider_dependency_descriptions(provider_type: str) -> dict[str, str]:
    return {dep.dep_id: dep.description for dep in get_provider_deps(provider_type)}


def _build_dep_response_rows(
    *,
    provider_type: str,
    dep_rows: list[dict],
) -> list[dict]:
    descriptions = _provider_dependency_descriptions(provider_type)
    payload_rows: list[dict] = []
    for dep in dep_rows:
        dep_type = str(dep.get("dep_type") or dep.get("dep_id") or "").strip()
        instance_id = str(dep.get("instance_id") or dep.get("id") or dep.get("dep_id") or "").strip()
        dep_id = dep_type or instance_id
        display_name = str(dep.get("display_name") or instance_id or dep_id).strip()
        payload_rows.append(
            {
                "dep_id": dep_id,
                "dep_type": dep_type or dep_id,
                "instance_id": instance_id or dep_id,
                "id": instance_id or dep_id,
                "display_name": display_name,
                "hf_repo_id": str(dep.get("hf_repo_id") or "").strip(),
                "weight_source": str(dep.get("weight_source") or "huggingface").strip().lower(),
                "dep_model_path": dep.get("dep_model_path"),
                "description": descriptions.get(dep_type, ""),
                "resolved_path": dep.get("resolved_path"),
                "download_status": str(dep.get("download_status") or "pending").strip().lower(),
                "download_progress": int(dep.get("download_progress") or 0),
                "download_speed_bps": int(dep.get("download_speed_bps") or 0),
                "download_error": dep.get("download_error"),
                "revision": None,
            }
        )
    return payload_rows


async def _resolve_dep_paths(
    model_id: str,
    dep_instance_store: DepInstanceStore,
    model_dep_store: ModelDepRequirementsStore,
) -> dict[str, str]:
    normalized_model_id = str(model_id or "").strip()
    if not normalized_model_id:
        return {}

    assignments = await model_dep_store.get_assignments_for_model(normalized_model_id)
    if not assignments:
        return {}

    dep_paths: dict[str, str] = {}
    for assignment in assignments:
        dep_type = str(assignment.get("dep_type") or "").strip()
        instance_id = str(assignment.get("dep_instance_id") or "").strip()
        if not dep_type or not instance_id:
            raise ModelProviderConfigurationError(
                f"invalid dependency assignment for model {normalized_model_id}"
            )

        dep_row = await dep_instance_store.get(instance_id)
        if dep_row is None:
            raise ModelProviderConfigurationError(
                f"dependency {dep_type} instance {instance_id} for model {normalized_model_id} is missing; "
                "please complete dependency download first"
            )

        status = str(dep_row.get("download_status") or "pending").strip().lower()
        resolved_path = str(dep_row.get("resolved_path") or "").strip()
        if status != "done" or not resolved_path:
            raise ModelProviderConfigurationError(
                f"dependency {dep_type} instance {instance_id} for model {normalized_model_id} is {status}; "
                "please complete dependency download first"
            )

        resolved_candidate = Path(resolved_path).expanduser()
        if not resolved_candidate.exists():
            raise ModelProviderConfigurationError(
                f"dependency {dep_type} instance {instance_id} for model {normalized_model_id} path does not exist: "
                f"{resolved_path}. please complete dependency download first"
            )
        dep_paths[dep_type] = str(resolved_candidate.resolve())
    return dep_paths


def _normalize_new_dep_config(dep_type: str, raw_new: Any) -> dict:
    if not isinstance(raw_new, dict):
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type}.new must be an object",
        )
    return {
        "instance_id": str(raw_new.get("instance_id", raw_new.get("instanceId")) or "").strip(),
        "display_name": str(raw_new.get("display_name", raw_new.get("displayName")) or "").strip(),
        "weight_source": str(raw_new.get("weight_source", raw_new.get("weightSource")) or "").strip().lower(),
        "dep_model_path": str(raw_new.get("dep_model_path", raw_new.get("depModelPath")) or "").strip(),
    }


def _normalize_single_dep_assignment(dep_type: str, raw_assignment: Any) -> dict:
    if not isinstance(raw_assignment, dict):
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type} must be an object",
        )
    normalized_assignment: dict[str, Any] = {}
    raw_instance_id = raw_assignment.get("instance_id", raw_assignment.get("instanceId"))
    if raw_instance_id is not None:
        instance_id = str(raw_instance_id).strip()
        if not instance_id:
            raise HTTPException(
                status_code=422,
                detail=f"depAssignments.{dep_type}.instance_id is required",
            )
        normalized_assignment["instance_id"] = instance_id
    if "new" in raw_assignment:
        normalized_assignment["new"] = _normalize_new_dep_config(dep_type, raw_assignment.get("new"))
    if "instance_id" in normalized_assignment and "new" in normalized_assignment:
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type} cannot set both instance_id and new",
        )
    return normalized_assignment


def _normalize_dep_assignments_payload(raw_assignments: Any) -> dict[str, dict]:
    if raw_assignments is None:
        return {}
    if not isinstance(raw_assignments, dict):
        raise HTTPException(status_code=422, detail="depAssignments must be an object")
    normalized_assignments: dict[str, dict] = {}
    for raw_dep_type, raw_assignment in raw_assignments.items():
        dep_type = str(raw_dep_type or "").strip()
        if not dep_type:
            raise HTTPException(status_code=422, detail="depAssignments contains an empty dep_type key")
        normalized_assignments[dep_type] = _normalize_single_dep_assignment(dep_type, raw_assignment)
    return normalized_assignments


def _is_hf_repo_id(value: str) -> bool:
    normalized = str(value or "").strip()
    parts = normalized.split("/")
    if len(parts) != 2:
        return False
    return all(part and part == part.strip() for part in parts)


def _default_dep_assignment(model_id: str, dep_type: str, hf_repo_id: str) -> dict:
    return {
        "new": {
            "instance_id": f"{dep_type}-{model_id}",
            "display_name": dep_type,
            "weight_source": "huggingface",
            "dep_model_path": hf_repo_id,
        }
    }


async def _validate_existing_dep_assignment(
    dep_type: str,
    instance_id: str,
    dep_instance_store: DepInstanceStore,
) -> dict:
    normalized_instance_id = str(instance_id or "").strip()
    if not normalized_instance_id:
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type}.instance_id is required",
        )
    existing = await dep_instance_store.get(normalized_instance_id)
    if existing is None:
        raise HTTPException(status_code=422, detail=f"dep instance not found: {normalized_instance_id}")
    existing_dep_type = str(existing.get("dep_type") or "").strip()
    if existing_dep_type and existing_dep_type != dep_type:
        raise HTTPException(
            status_code=422,
            detail=f"dep instance {normalized_instance_id} belongs to dep_type {existing_dep_type}, expected {dep_type}",
        )
    return {"instance_id": normalized_instance_id}


def _validate_new_dep_model_path(
    dep_type: str,
    hf_repo_id: str,
    weight_source: str,
    dep_model_path: str,
) -> str:
    if weight_source == "local":
        if not dep_model_path:
            raise HTTPException(
                status_code=422,
                detail=f"dep {dep_type} local source requires dep_model_path",
            )
        if not Path(dep_model_path).expanduser().exists():
            raise HTTPException(
                status_code=422,
                detail=f"dep {dep_type} local path does not exist: {dep_model_path}",
            )
        return dep_model_path
    if weight_source == "url":
        parsed_url = urlsplit(dep_model_path)
        if parsed_url.scheme not in {"http", "https"}:
            raise HTTPException(
                status_code=422,
                detail=f"dep {dep_type} url source requires an http(s) dep_model_path",
            )
        url_path = parsed_url.path.strip().lower()
        if not (url_path.endswith(".zip") or url_path.endswith(".tar.gz")):
            raise HTTPException(
                status_code=422,
                detail=f"dep {dep_type} url source only supports .zip and .tar.gz archives",
            )
        return dep_model_path
    repo_id = dep_model_path or hf_repo_id
    if not _is_hf_repo_id(repo_id):
        raise HTTPException(
            status_code=422,
            detail=f"dep {dep_type} huggingface source requires owner/repo format",
        )
    return repo_id


async def _validate_new_dep_assignment(
    dep_type: str,
    hf_repo_id: str,
    new_cfg: dict,
    dep_instance_store: DepInstanceStore,
) -> dict:
    instance_id = str(new_cfg.get("instance_id") or "").strip()
    if not instance_id:
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type}.new.instance_id is required",
        )
    if await dep_instance_store.get(instance_id) is not None:
        raise HTTPException(status_code=422, detail=f"dep instance already exists: {instance_id}")

    display_name = str(new_cfg.get("display_name") or dep_type).strip()
    if not display_name:
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type}.new.display_name is required",
        )

    weight_source = str(new_cfg.get("weight_source") or "huggingface").strip().lower()
    if weight_source not in {"huggingface", "local", "url"}:
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments.{dep_type}.new.weight_source must be one of: huggingface, local, url",
        )

    dep_model_path = _validate_new_dep_model_path(
        dep_type,
        hf_repo_id,
        weight_source,
        str(new_cfg.get("dep_model_path") or "").strip(),
    )

    duplicate = await dep_instance_store.find_duplicate_source(dep_type, weight_source, dep_model_path)
    if duplicate is not None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"dep {dep_type} already has an instance \"{duplicate['display_name']}\" "
                f"with the same source ({weight_source}: {dep_model_path}). "
                f"Use instance_id \"{duplicate['id']}\" instead."
            ),
        )

    return {
        "instance_id": instance_id,
        "display_name": display_name,
        "weight_source": weight_source,
        "dep_model_path": dep_model_path,
    }


async def _prepare_dep_assignments(
    model_id: str,
    provider_type: str,
    raw_dep_assignments: Any,
    dep_instance_store: DepInstanceStore,
) -> dict[str, dict]:
    dependencies = get_provider_deps(provider_type)
    if not dependencies:
        return {}

    assignments = _normalize_dep_assignments_payload(raw_dep_assignments)
    expected_dep_types = {dep.dep_id for dep in dependencies}
    unknown_dep_types = sorted(dep_type for dep_type in assignments if dep_type not in expected_dep_types)
    if unknown_dep_types:
        raise HTTPException(
            status_code=422,
            detail=f"depAssignments has unknown dep_type: {unknown_dep_types[0]}",
        )

    normalized_assignments: dict[str, dict] = {}
    for dep in dependencies:
        dep_type = dep.dep_id
        assignment = dict(assignments.get(dep_type) or _default_dep_assignment(model_id, dep_type, dep.hf_repo_id))
        if "instance_id" in assignment:
            normalized_assignments[dep_type] = await _validate_existing_dep_assignment(
                dep_type,
                str(assignment.get("instance_id") or ""),
                dep_instance_store,
            )
            continue

        new_cfg = assignment.get("new")
        if not isinstance(new_cfg, dict):
            raise HTTPException(
                status_code=422,
                detail=f"depAssignments.{dep_type} must set instance_id or new",
            )

        normalized_assignments[dep_type] = {
            "new": await _validate_new_dep_assignment(
                dep_type,
                dep.hf_repo_id,
                new_cfg,
                dep_instance_store,
            )
        }

    return normalized_assignments


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


def _resolve_device_ids(config: ServingConfig) -> tuple[str, ...]:
    configured_device_ids = tuple(
        str(device_id).strip()
        for device_id in config.gpu_device_ids
        if str(device_id).strip()
    )
    if configured_device_ids:
        return configured_device_ids

    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return ("0",)

    try:
        if not torch.cuda.is_available():
            return ("0",)
        detected_count = int(torch.cuda.device_count())
    except Exception:
        return ("0",)
    if detected_count <= 0:
        return ("0",)
    return tuple(str(index) for index in range(detected_count))


def _get_gpu_device_info(device_id: str) -> dict:
    try:
        import torch  # type: ignore[import-not-found]
        props = torch.cuda.get_device_properties(int(device_id))
        total_memory_gb = round(props.total_memory / (1024 ** 3), 1)
        return {"name": props.name, "totalMemoryGb": total_memory_gb}
    except Exception:
        return {"name": None, "totalMemoryGb": None}


_DEFAULT_DEVICE_TOTAL_VRAM_MB = 24 * 1024
_DEFAULT_WEIGHT_RATIO = 0.75


def _normalize_vram_mb(value: object) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _resolve_total_vram_mb(model_definition: dict[str, Any]) -> int | None:
    vram_gb = model_definition.get("vram_gb")
    if vram_gb is not None:
        try:
            parsed_gb = float(vram_gb)
        except (TypeError, ValueError):
            parsed_gb = 0.0
        if parsed_gb > 0:
            return int(round(parsed_gb * 1024.0))
    return _normalize_vram_mb(model_definition.get("min_vram_mb"))


def _resolve_weight_vram_mb(model_definition: dict[str, Any]) -> int:
    explicit_weight = _normalize_vram_mb(model_definition.get("weight_vram_mb"))
    if explicit_weight is not None:
        return explicit_weight
    total_vram_mb = _resolve_total_vram_mb(model_definition)
    if total_vram_mb is None:
        return 1
    return max(int(round(total_vram_mb * _DEFAULT_WEIGHT_RATIO)), 1)


def _detect_device_total_vram_mb(
    device_ids: tuple[str, ...],
) -> dict[str, int]:
    totals: dict[str, int] = {}
    for device_id in device_ids:
        info = _get_gpu_device_info(device_id)
        total_gb = info.get("totalMemoryGb")
        total_mb: int | None = None
        if total_gb is not None:
            try:
                parsed = float(total_gb)
            except (TypeError, ValueError):
                parsed = 0.0
            if parsed > 0:
                total_mb = int(round(parsed * 1024.0))
        totals[device_id] = total_mb or _DEFAULT_DEVICE_TOTAL_VRAM_MB
    return totals


def _summarize_inference_options(options: dict[str, Any]) -> list[str]:
    option_keys = sorted(str(key) for key in options.keys())
    if len(option_keys) <= 8:
        return option_keys
    return [*option_keys[:8], "..."]


def _clamp_inference_estimate_mb(
    *,
    raw_value: Any,
    model: str,
    batch_size: int,
    options: dict[str, Any],
) -> int:
    try:
        normalized = int(float(raw_value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        normalized = 0
    if normalized <= 0:
        _logger.warning(
            "estimate_inference_vram_mb_nonpositive",
            model=model,
            raw=raw_value,
            clamped=1,
            batch_size=batch_size,
            options=_summarize_inference_options(options),
        )
        return 1
    return normalized


async def _resolve_model_definition_for_runtime(
    model_store: ModelStore,
    normalized_model_name: str,
) -> dict[str, Any]:
    model_definition = await model_store.get_model(normalized_model_name)
    if model_definition is None and normalized_model_name == "trellis":
        # Backward compatibility: legacy tasks that still send "trellis"
        # resolve to the current default model in model_definitions.
        model_definition = await model_store.get_default_model()
    if model_definition is None:
        raise ModelProviderConfigurationError(
            f"model definition not found: {normalized_model_name}"
        )
    return model_definition


def _normalize_persisted_disabled_devices(
    raw_value: Any,
    all_device_ids: tuple[str, ...],
) -> set[str]:
    if not isinstance(raw_value, (list, tuple, set)):
        return set()
    valid_device_ids = set(all_device_ids)
    normalized: set[str] = set()
    for value in raw_value:
        device_id = str(value).strip()
        if device_id and device_id in valid_device_ids:
            normalized.add(device_id)
    return normalized


def _ordered_disabled_devices(
    disabled_devices: set[str],
    all_device_ids: tuple[str, ...],
) -> list[str]:
    return [device_id for device_id in all_device_ids if device_id in disabled_devices]


def _parse_gpu_disabled_devices_update(
    value: Any,
    *,
    all_device_ids: tuple[str, ...],
) -> set[str]:
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("gpuDisabledDevices must be an array of device IDs")
    valid_device_ids = set(all_device_ids)
    normalized: set[str] = set()
    for item in value:
        device_id = str(item).strip()
        if not device_id:
            raise ValueError("gpuDisabledDevices must not contain empty device IDs")
        if device_id not in valid_device_ids:
            raise ValueError(f"gpuDisabledDevices has unknown deviceId: {device_id}")
        normalized.add(device_id)
    return normalized


async def build_model_runtime(
    model_store: ModelStore,
    config: ServingConfig,
    model_name: str,
    device_ids: tuple[str, ...] | None = None,
    disabled_devices: set[str] | None = None,
) -> ModelRuntime:
    normalized_model_name = str(model_name).strip().lower()
    model_definition = await _resolve_model_definition_for_runtime(
        model_store,
        normalized_model_name,
    )

    provider_name = str(model_definition.get("provider_type") or "").strip().lower()
    if not provider_name:
        raise ModelProviderConfigurationError(
            f"model definition is missing provider_type: {normalized_model_name}"
        )

    download_status = str(model_definition.get("download_status") or "done").strip().lower()
    if download_status != "done" and not config.is_mock_provider:
        raise ModelProviderConfigurationError(
            f"model {normalized_model_name} weights are {download_status}; download must complete first"
        )

    model_path = str(model_definition.get("model_path") or "").strip()
    resolved_path = str(model_definition.get("resolved_path") or "").strip()
    if resolved_path:
        resolved_candidate = Path(resolved_path).expanduser()
        if not resolved_candidate.exists():
            raise ModelProviderConfigurationError(
                f"resolved model path does not exist: {resolved_path}. Download weights first."
            )
        provider_model_path = str(resolved_candidate.resolve())
    else:
        # Backward compatibility for legacy rows: resolved_path may be null.
        provider_model_path = model_path

    if not provider_model_path:
        raise ModelProviderConfigurationError(
            f"model definition is missing model_path: {normalized_model_name}"
        )

    model_id = str(model_definition.get("id") or normalized_model_name).strip()
    dep_instance_store = DepInstanceStore(config.database_path)
    model_dep_store = ModelDepRequirementsStore(config.database_path)
    await dep_instance_store.initialize()
    await model_dep_store.initialize()
    try:
        dep_paths = await _resolve_dep_paths(
            model_id=model_id,
            dep_instance_store=dep_instance_store,
            model_dep_store=model_dep_store,
        )
    finally:
        await dep_instance_store.close()
        await model_dep_store.close()

    provider = await asyncio.to_thread(
        build_provider,
        provider_name=provider_name,
        provider_mode=config.provider_mode,
        model_path=provider_model_path,
        mock_delay_ms=config.mock_gpu_stage_delay_ms,
    )
    resolved_device_ids = tuple(device_ids) if device_ids is not None else _resolve_device_ids(config)
    if not resolved_device_ids:
        resolved_device_ids = ("0",)
    resolved_device_id_set = set(resolved_device_ids)
    scheduler_disabled_devices = {
        device_id
        for device_id in (disabled_devices or set())
        if device_id in resolved_device_id_set
    }
    workers = build_gpu_workers(
        provider=provider,
        provider_mode=config.provider_mode,
        provider_name=provider_name,
        model_path=provider_model_path,
        device_ids=resolved_device_ids,
        dep_paths=dep_paths,
    )
    return ModelRuntime(
        model_name=normalized_model_name,
        provider=provider,
        workers=workers,
        scheduler=GPUSlotScheduler(
            workers,
            disabled_device_ids=scheduler_disabled_devices,
        ),
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

    model_store = ModelStore(config.database_path)
    await model_store.initialize()
    try:
        model_definition = await model_store.get_default_model()
        if model_definition is None:
            model_definitions = await model_store.list_models()
            if not model_definitions:
                raise ModelProviderConfigurationError(
                    "no model definitions found in model_definitions"
                )
            model_definition = model_definitions[0]
    finally:
        await model_store.close()

    provider_name = str(model_definition.get("provider_type") or "").strip().lower()
    model_id = str(model_definition.get("id") or "").strip()
    if provider_name != "trellis2":
        raise ModelProviderConfigurationError(
            f"unsupported MODEL_PROVIDER in model_definitions: {provider_name}"
        )
    model_path = str(model_definition.get("model_path") or "").strip()
    if not model_path:
        raise ModelProviderConfigurationError(
            "default model in model_definitions has empty model_path"
        )

    provider_report = await asyncio.to_thread(
        Trellis2Provider.inspect_runtime,
        model_path,
        load_pipeline=True,
    )
    return {
        "provider_mode": provider_mode,
        "model_id": model_id,
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
    all_device_ids = _resolve_device_ids(config)
    vram_allocator = VRAMAllocator(
        device_totals_mb=_detect_device_total_vram_mb(all_device_ids),
    )
    vram_allocator.set_metrics_hook(
        VRAMMetricsHook(
            on_acquire_outcome=increment_vram_acquire_inference,
            on_acquire_wait=observe_vram_acquire_inference_wait,
            on_evict=increment_vram_evict,
        )
    )
    if not config.is_mock_provider:
        from gen3d.engine.vram_probe import probe_device_free_mb

        vram_allocator.set_vram_probe(probe_device_free_mb)
    disabled_devices: set[str] = set()
    task_store = TaskStore(config.database_path)
    api_key_store = ApiKeyStore(config.database_path)
    model_store = ModelStore(config.database_path)
    dep_instance_store = DepInstanceStore(config.database_path)
    model_dep_requirements_store = ModelDepRequirementsStore(config.database_path)
    settings_store = SettingsStore(config.database_path)
    artifact_store = build_artifact_store(config)
    preview_renderer_service = preview_renderer_service or PreviewRendererService()

    async def runtime_loader(
        model_name: str,
        device_id: str | None = None,
        exclude_device_ids: Iterable[str] | None = None,
    ) -> ModelRuntime:
        normalized_model_name = str(model_name).strip().lower()
        model_definition = await _resolve_model_definition_for_runtime(
            model_store,
            normalized_model_name,
        )
        weight_vram_mb = _resolve_weight_vram_mb(model_definition)
        required_weight_vram_mb = 1 if config.is_mock_provider else weight_vram_mb
        excluded_device_ids = {
            str(candidate).strip()
            for candidate in (exclude_device_ids or ())
            if str(candidate).strip()
        }
        allocatable_device_ids = tuple(
            current_device_id
            for current_device_id in all_device_ids
            if (
                current_device_id not in disabled_devices
                and current_device_id not in excluded_device_ids
            )
        )
        if not allocatable_device_ids:
            raise ModelProviderConfigurationError("all GPU devices are disabled")
        try:
            assigned_device_id = vram_allocator.reserve(
                model_name=normalized_model_name,
                weight_vram_mb=required_weight_vram_mb,
                allowed_device_ids=allocatable_device_ids,
                preferred_device_id=(
                    device_id
                    if device_id is not None and device_id not in excluded_device_ids
                    else None
                ),
            )
        except VRAMAllocatorError as exc:
            raise ModelProviderConfigurationError(str(exc)) from exc

        try:
            try:
                runtime = await build_model_runtime(
                    model_store,
                    config,
                    model_name,
                    device_ids=(assigned_device_id,),
                    disabled_devices=disabled_devices,
                )
            except TypeError as exc:
                message = str(exc)
                if (
                    "unexpected keyword argument 'device_ids'" not in message
                    and "unexpected keyword argument 'disabled_devices'" not in message
                ):
                    raise
                runtime = await build_model_runtime(
                    model_store,
                    config,
                    model_name,
                )
        except Exception:
            vram_allocator.release(normalized_model_name)
            raise

        def estimate_inference_vram_mb(batch_size: int, options: dict[str, Any]) -> int:
            if config.is_mock_provider:
                return 1
            normalized_batch_size = max(int(batch_size), 1)
            raw_value = runtime.provider.estimate_inference_vram_mb(
                batch_size=normalized_batch_size,
                options=options,
            )
            return _clamp_inference_estimate_mb(
                raw_value=raw_value,
                model=normalized_model_name,
                batch_size=normalized_batch_size,
                options=options,
            )

        runtime.scheduler.configure_inference_admission(
            allocator=vram_allocator,
            model_name=normalized_model_name,
            device_id=assigned_device_id,
            estimate_inference_vram_mb=estimate_inference_vram_mb,
        )
        runtime.assigned_device_id = assigned_device_id
        runtime.weight_vram_mb = weight_vram_mb
        return runtime

    model_registry = ModelRegistry(runtime_loader)
    model_registry.add_model_unloaded_listener(vram_allocator.release)
    model_scheduler = ModelScheduler(
        model_registry=model_registry,
        task_store=task_store,
        model_store=model_store,
        settings_store=settings_store,
        enabled=not config.is_mock_provider,
        vram_detection_enabled=config.vram_detection_enabled,
        gpu_device_count=len(all_device_ids),
    )

    async def _evict_idle_on_device(device_id: str, requester_model_name: str) -> bool:
        snapshot = vram_allocator.snapshot().get(device_id)
        if snapshot is None:
            return False
        loaded_on_device = set(snapshot["allocations"].keys())
        active_model_names = vram_allocator.active_inference_model_names_on(device_id)
        candidates = [
            model_name
            for model_name in loaded_on_device
            if model_name != requester_model_name
            and model_name not in active_model_names
            and model_registry.get_state(model_name) == "ready"
        ]
        if not candidates:
            return False
        victim = min(candidates, key=model_scheduler.get_last_used_tick)
        try:
            await model_registry.unload(victim)
        except Exception:
            structlog.get_logger(__name__).warning(
                "vram_allocator.evict_failed",
                victim=victim,
                device_id=device_id,
                requester=requester_model_name,
            )
            return False
        return True

    vram_allocator.set_evict_callback(_evict_idle_on_device)
    weight_manager = WeightManager(
        model_store=model_store,
        cache_dir=config.model_cache_dir,
        dep_store=dep_instance_store,
        model_dep_requirements_store=model_dep_requirements_store,
    )
    model_registry.add_model_loaded_listener(model_scheduler.on_model_loaded)
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
        worker_count=len(all_device_ids),
    )
    engine = AsyncGen3DEngine(
        task_store=task_store,
        pipeline=pipeline,
        model_registry=model_registry,
        model_scheduler=model_scheduler,
        artifact_store=artifact_store,
        webhook_sender=webhook_sender,
        webhook_timeout_seconds=config.webhook_timeout_seconds,
        webhook_max_retries=config.webhook_max_retries,
        provider_mode=config.provider_mode,
        allowed_callback_domains=config.allowed_callback_domains,
        rate_limiter=rate_limiter,
        parallel_slots=len(all_device_ids),
        queue_max_size=config.queue_max_size,
        uploads_dir=config.uploads_dir,
    )
    container = AppContainer(
        config=config,
        all_device_ids=all_device_ids,
        disabled_devices=disabled_devices,
        task_store=task_store,
        api_key_store=api_key_store,
        rate_limiter=rate_limiter,
        artifact_store=artifact_store,
        preview_renderer_service=preview_renderer_service,
        model_registry=model_registry,
        pipeline=pipeline,
        engine=engine,
        model_store=model_store,
        dep_instance_store=dep_instance_store,
        model_dep_requirements_store=model_dep_requirements_store,
        settings_store=settings_store,
        vram_allocator=vram_allocator,
        model_scheduler=model_scheduler,
        weight_manager=weight_manager,
        model_download_tasks={},
    )
    proxy_client: httpx.AsyncClient | None = None

    async def _run_model_weight_download(
        model_id: str,
        provider_type: str,
        weight_source: str,
        model_path: str,
        dep_assignments: dict[str, dict] | None = None,
    ) -> None:
        try:
            await container.weight_manager.download(
                model_id=model_id,
                provider_type=provider_type,
                weight_source=weight_source,
                model_path=model_path,
                dep_assignments=dep_assignments,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _logger.warning(
                "model.weight_download_failed",
                model_id=model_id,
                provider_type=provider_type,
                weight_source=weight_source,
                error=str(exc),
            )
        finally:
            current_task = asyncio.current_task()
            if (
                current_task is not None
                and container.model_download_tasks.get(model_id) is current_task
            ):
                container.model_download_tasks.pop(model_id, None)

    async def _cancel_model_download_task(model_id: str) -> None:
        task = container.model_download_tasks.pop(model_id, None)
        if task is None:
            return
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal proxy_client
        app.state.container = container
        config.uploads_dir.mkdir(parents=True, exist_ok=True)
        await container.task_store.initialize()
        await container.api_key_store.initialize()
        await container.model_store.initialize()
        await container.dep_instance_store.initialize()
        await container.model_dep_requirements_store.initialize()
        await container.settings_store.initialize()
        initialize_vram_metrics(container.all_device_ids)
        persisted_external_wait_timeout = await container.settings_store.get(
            EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY
        )
        if persisted_external_wait_timeout is not None:
            try:
                container.vram_allocator.set_external_vram_wait_timeout_seconds(
                    float(persisted_external_wait_timeout)
                )
            except (TypeError, ValueError):
                pass
        persisted_internal_wait_timeout = await container.settings_store.get(
            INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY
        )
        if persisted_internal_wait_timeout is not None:
            try:
                container.vram_allocator.set_internal_vram_wait_timeout_seconds(
                    float(persisted_internal_wait_timeout)
                )
            except (TypeError, ValueError):
                pass
        persisted_disabled_devices = await container.settings_store.get(
            GPU_DISABLED_DEVICES_KEY
        )
        normalized_disabled_devices = _normalize_persisted_disabled_devices(
            persisted_disabled_devices,
            container.all_device_ids,
        )
        container.disabled_devices.clear()
        container.disabled_devices.update(normalized_disabled_devices)
        if persisted_disabled_devices is not None:
            normalized_disabled_list = _ordered_disabled_devices(
                normalized_disabled_devices,
                container.all_device_ids,
            )
            if persisted_disabled_devices != normalized_disabled_list:
                await container.settings_store.set(
                    GPU_DISABLED_DEVICES_KEY,
                    normalized_disabled_list,
                )
        await container.model_scheduler.initialize()
        default_models = await container.model_store.list_models(
            extra_statuses=frozenset({"pending"}) if container.config.is_mock_provider else frozenset(),
        )
        default_model_ids = tuple(
            str(model["id"]).strip().lower()
            for model in default_models
            if model.get("is_default") and str(model.get("id") or "").strip()
        )
        container.engine.set_startup_models(default_model_ids)
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
        download_task_ids = tuple(container.model_download_tasks.keys())
        for model_id in download_task_ids:
            await _cancel_model_download_task(model_id)
        await container.settings_store.close()
        await container.model_dep_requirements_store.close()
        await container.dep_instance_store.close()
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
        enabled_models = await app_container.model_store.get_enabled_models(
            extra_statuses=frozenset({"pending"}) if app_container.config.is_mock_provider else frozenset(),
        )
        runtime_states = app_container.model_registry.runtime_states()
        return UserModelListResponse(
            models=[
                UserModelSummary(
                    id=str(model["id"]),
                    display_name=str(model["display_name"]),
                    is_default=bool(model["is_default"]),
                    runtime_state=str(
                        runtime_states.get(str(model["id"]).strip().lower(), "not_loaded")
                    ),
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
        requested_model = str(payload.model or "").strip().lower()
        if requested_model:
            normalized_model = requested_model
        else:
            default_model = await app_container.model_store.get_default_model()
            if default_model is None:
                all_models = await app_container.model_store.list_models()
                default_model = all_models[0] if all_models else None
            normalized_model = str(default_model.get("id") if default_model else "").strip().lower()
            if not normalized_model:
                raise HTTPException(
                    status_code=422,
                    detail="no default model configured",
                )
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
        if created:
            asyncio.create_task(
                app_container.model_scheduler.on_task_queued(normalized_model)
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
        "/api/admin/gpu/state",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_admin_gpu_state(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        snapshot_by_device = app_container.vram_allocator.snapshot()
        runtime_states = app_container.model_registry.runtime_states()
        holders: list[dict[str, object]] = []
        devices: list[dict[str, object]] = []
        cluster_total_vram_mb = 0
        cluster_reserved_vram_mb = 0
        cluster_used_weight_vram_mb = 0
        cluster_used_inference_vram_mb = 0
        cluster_free_vram_mb = 0
        cluster_effective_free_vram_mb = 0

        for device_id in app_container.all_device_ids:
            snapshot = snapshot_by_device.get(device_id, {})
            total_vram_mb = int(snapshot.get("total_vram_mb", 0))
            reserved_vram_mb = int(snapshot.get("reserved_vram_mb", 0))
            used_weight_vram_mb = int(snapshot.get("used_weight_vram_mb", 0))
            used_inference_vram_mb = int(snapshot.get("used_inference_vram_mb", 0))
            free_vram_mb = int(snapshot.get("free_vram_mb", 0))
            effective_free_vram_mb = int(snapshot.get("effective_free_vram_mb", 0))
            allocations = {
                str(model_name).strip().lower(): int(vram_mb)
                for model_name, vram_mb in dict(snapshot.get("allocations", {})).items()
                if str(model_name).strip()
            }
            inference_allocations = {
                str(allocation_id).strip(): int(vram_mb)
                for allocation_id, vram_mb in dict(
                    snapshot.get("inference_allocations", {})
                ).items()
                if str(allocation_id).strip()
            }
            inference_allocation_models = {
                str(allocation_id).strip(): str(model_name).strip().lower()
                for allocation_id, model_name in dict(
                    snapshot.get("inference_allocation_models", {})
                ).items()
                if str(allocation_id).strip()
            }
            external_occupation_mb = max(free_vram_mb - effective_free_vram_mb, 0)

            cluster_total_vram_mb += total_vram_mb
            cluster_reserved_vram_mb += reserved_vram_mb
            cluster_used_weight_vram_mb += used_weight_vram_mb
            cluster_used_inference_vram_mb += used_inference_vram_mb
            cluster_free_vram_mb += free_vram_mb
            cluster_effective_free_vram_mb += effective_free_vram_mb

            for model_name, vram_mb in allocations.items():
                holders.append(
                    {
                        "kind": "weight",
                        "modelName": model_name,
                        "deviceId": device_id,
                        "vramMb": vram_mb,
                        "runtimeState": str(
                            runtime_states.get(model_name, "not_loaded")
                        ),
                    }
                )
            for allocation_id, vram_mb in inference_allocations.items():
                holders.append(
                    {
                        "kind": "inference",
                        "allocationId": allocation_id,
                        "modelName": inference_allocation_models.get(allocation_id, ""),
                        "deviceId": device_id,
                        "vramMb": vram_mb,
                    }
                )

            weight_models = [
                {"name": model_name, "vramMb": vram_mb}
                for model_name, vram_mb in allocations.items()
            ]
            weight_models.sort(
                key=lambda model_item: int(model_item["vramMb"]),
                reverse=True,
            )
            device_info = _get_gpu_device_info(device_id)
            devices.append(
                {
                    "deviceId": device_id,
                    "name": str(device_info.get("name") or f"GPU {device_id}"),
                    "totalVramMb": total_vram_mb,
                    "reservedVramMb": reserved_vram_mb,
                    "usedWeightVramMb": used_weight_vram_mb,
                    "usedInferenceVramMb": used_inference_vram_mb,
                    "freeVramMb": free_vram_mb,
                    "effectiveFreeVramMb": effective_free_vram_mb,
                    "externalOccupationMb": external_occupation_mb,
                    "weightModels": weight_models,
                    "inferenceCount": len(inference_allocations),
                    "enabled": device_id not in app_container.disabled_devices,
                }
            )

        holders.sort(key=lambda holder: int(holder.get("vramMb", 0)), reverse=True)
        return {
            "cluster": {
                "deviceCount": len(app_container.all_device_ids),
                "totalVramMb": cluster_total_vram_mb,
                "reservedVramMb": cluster_reserved_vram_mb,
                "usedWeightVramMb": cluster_used_weight_vram_mb,
                "usedInferenceVramMb": cluster_used_inference_vram_mb,
                "freeVramMb": cluster_free_vram_mb,
                "effectiveFreeVramMb": cluster_effective_free_vram_mb,
            },
            "holders": holders,
            "devices": devices,
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
        include_pending: bool = Query(default=False),
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        models = await app_container.model_store.list_models(
            include_pending=include_pending,
            extra_statuses=frozenset({"pending"}) if (not include_pending and app_container.config.is_mock_provider) else frozenset(),
        )
        runtime_states = app_container.model_registry.runtime_states()
        max_tasks_per_slot = app_container.model_scheduler.max_tasks_per_slot
        for model in models:
            model_id = str(model["id"]).strip().lower()
            state = str(runtime_states.get(model_id, "not_loaded"))
            model["runtimeState"] = state
            model["runtime_state"] = state
            model["tasks_processed"] = app_container.model_scheduler.get_tasks_processed(model_id)
            model["maxTasksPerSlot"] = max_tasks_per_slot
            model["max_tasks_per_slot"] = max_tasks_per_slot
            if state == "error":
                error = None
                try:
                    error = app_container.model_registry.get_error(model["id"])
                except Exception:
                    error = None
                model["error_message"] = _friendly_model_error_message(error)
            else:
                model["error_message"] = None
            if include_pending:
                dep_rows = await app_container.dep_instance_store.get_all_for_model(model_id)
                model["deps"] = _build_dep_response_rows(
                    provider_type=str(model.get("provider_type") or ""),
                    dep_rows=dep_rows,
                )

        enabled = sum(1 for m in models if m.get("is_enabled"))
        return {
            "models": models,
            "summary": {
                "total": len(models),
                "enabled": enabled,
                "disabled": len(models) - enabled,
            },
        }

    @app.get(
        "/api/admin/deps",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_deps(
        app_container: AppContainer = Depends(get_container),
    ) -> list[dict]:
        dep_rows = await app_container.dep_instance_store.list_all()
        return _build_dep_response_rows(
            provider_type="",
            dep_rows=dep_rows,
        )

    @app.get(
        "/api/admin/providers/{provider_type}/deps",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_provider_deps(
        provider_type: str,
        app_container: AppContainer = Depends(get_container),
    ) -> list[dict]:
        dependencies = get_provider_deps(provider_type)
        result: list[dict] = []
        for dep in dependencies:
            instances = await app_container.dep_instance_store.list_by_dep_type(dep.dep_id)
            result.append(
                {
                    "dep_type": dep.dep_id,
                    "hf_repo_id": dep.hf_repo_id,
                    "description": dep.description,
                    "instances": instances,
                }
            )
        return result

    @app.get(
        "/api/admin/models/{model_id}/deps",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_model_deps(
        model_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> list[dict]:
        model = await app_container.model_store.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        dep_rows = await app_container.dep_instance_store.get_all_for_model(model_id)
        return _build_dep_response_rows(
            provider_type=str(model.get("provider_type") or ""),
            dep_rows=dep_rows,
        )

    @app.post(
        "/api/admin/models/{model_id}/load",
        dependencies=[Depends(require_admin_token)],
    )
    async def load_model(
        model_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        model = await app_container.model_store.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        await app_container.model_scheduler.request_load(model_id)
        runtime_state = app_container.model_registry.get_state(model_id)
        return {
            "id": str(model["id"]),
            "runtime_state": runtime_state,
            "runtimeState": runtime_state,
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
        model_id = str(payload.get("id") or "").strip()
        provider_type = str(
            payload.get(
                "provider_type",
                payload.get("providerType", payload.get("providerName")),
            )
            or ""
        ).strip()
        display_name = str(payload.get("displayName") or "").strip()
        model_path = str(payload.get("modelPath") or "").strip()
        weight_source = str(
            payload.get("weightSource", payload.get("weight_source")) or ""
        ).strip().lower()
        raw_dep_assignments = payload.get("depAssignments", payload.get("dep_assignments"))
        if not model_id:
            raise HTTPException(status_code=422, detail="id is required")
        if not provider_type:
            raise HTTPException(status_code=422, detail="providerType is required")
        if not display_name:
            raise HTTPException(status_code=422, detail="displayName is required")
        if not model_path:
            raise HTTPException(status_code=422, detail="modelPath is required")
        if weight_source not in {"huggingface", "url", "local"}:
            raise HTTPException(
                status_code=422,
                detail="weightSource must be one of: huggingface, url, local",
            )
        if weight_source == "url":
            parsed_url = urlsplit(model_path)
            if parsed_url.scheme not in {"http", "https"}:
                raise HTTPException(
                    status_code=422,
                    detail="url weightSource requires an http(s) modelPath",
                )
            normalized_url_path = parsed_url.path.strip().lower()
            if not (
                normalized_url_path.endswith(".zip")
                or normalized_url_path.endswith(".tar.gz")
            ):
                raise HTTPException(
                    status_code=422,
                    detail="url source only supports .zip and .tar.gz archives",
                )
        if weight_source == "local":
            local_candidate = Path(model_path).expanduser()
            if not local_candidate.exists():
                raise HTTPException(
                    status_code=422,
                    detail=f"local model path does not exist: {model_path}",
                )
        dep_assignments = await _prepare_dep_assignments(
            model_id=model_id,
            provider_type=provider_type,
            raw_dep_assignments=raw_dep_assignments,
            dep_instance_store=app_container.dep_instance_store,
        )

        try:
            model = await app_container.model_store.create_model(
                id=model_id,
                provider_type=provider_type,
                display_name=display_name,
                model_path=model_path,
                weight_source=weight_source,
                download_status="downloading",
                download_progress=0,
                download_speed_bps=0,
                resolved_path=None,
                min_vram_mb=payload.get("minVramMb", 24000),
                vram_gb=payload.get("vramGb"),
                weight_vram_mb=payload.get("weightVramMb"),
                inference_vram_mb=payload.get("inferenceVramMb"),
                config=payload.get("config"),
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if weight_source == "local":
            try:
                await app_container.weight_manager.download(
                    model_id=model_id,
                    provider_type=provider_type,
                    weight_source=weight_source,
                    model_path=model_path,
                    dep_assignments=dep_assignments,
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except Exception as exc:
                raise HTTPException(
                    status_code=500,
                    detail=f"failed to resolve local model path: {exc}",
                ) from exc
            refreshed_model = await app_container.model_store.get_model(model_id)
            if refreshed_model is not None:
                model = refreshed_model
            return model

        existing_task = app_container.model_download_tasks.get(model_id)
        if existing_task is not None and not existing_task.done():
            await _cancel_model_download_task(model_id)
        app_container.model_download_tasks[model_id] = asyncio.create_task(
            _run_model_weight_download(
                model_id=model_id,
                provider_type=provider_type,
                weight_source=weight_source,
                model_path=model_path,
                dep_assignments=dep_assignments,
            ),
            name=f"model-download-{model_id}",
        )
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
            "vramGb": "vram_gb",
            "weightVramMb": "weight_vram_mb",
            "inferenceVramMb": "inference_vram_mb",
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
        model = await app_container.model_store.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        if str(model.get("download_status") or "").strip().lower() == "done":
            ready_count = await app_container.model_store.count_ready_models()
            if ready_count <= 1:
                raise HTTPException(
                    status_code=400, detail="cannot delete the last ready model"
                )
        if str(model.get("download_status") or "").strip().lower() == "downloading":
            await _cancel_model_download_task(model_id)
        if app_container.model_registry.get_state(model_id) != "not_loaded":
            await app_container.model_registry.unload(model_id)
        deleted = await app_container.model_store.delete_model(model_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="model not found")
        return {"ok": True}

    @app.get(
        "/api/admin/storage/stats",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_storage_stats(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        return await app_container.weight_manager.get_storage_stats()

    @app.get(
        "/api/admin/storage/orphans",
        dependencies=[Depends(require_admin_token)],
    )
    async def list_storage_orphans(
        app_container: AppContainer = Depends(get_container),
    ) -> list:
        return await app_container.weight_manager.list_orphans()

    @app.get(
        "/api/admin/storage/breakdown",
        dependencies=[Depends(require_admin_token)],
    )
    async def get_storage_breakdown(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        return await app_container.weight_manager.get_storage_breakdown()

    @app.delete(
        "/api/admin/storage/orphans",
        dependencies=[Depends(require_admin_token)],
    )
    async def clean_storage_orphans(
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        return await app_container.weight_manager.clean_orphans()

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
        model_definitions = await app_container.model_store.list_models(
            extra_statuses=frozenset({"pending"}) if app_container.config.is_mock_provider else frozenset(),
        )
        provider_options = [
            {
                "value": str(model["id"]),
                "label": str(model["display_name"]),
            }
            for model in model_definitions
            if str(model.get("id") or "").strip()
        ]
        default_model = next(
            (model for model in model_definitions if model.get("is_default")),
            None,
        )
        fallback_provider = (
            str(default_model.get("id") or "").strip()
            if default_model is not None
            else ""
        )
        if not provider_options:
            if fallback_provider:
                provider_options = [
                    {
                        "value": fallback_provider,
                        "label": fallback_provider,
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
                        "value": db_settings.get("defaultProvider", fallback_provider),
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
                        "key": "maxLoadedModels",
                        "labelKey": "settings.fields.maxLoadedModels.label",
                        "descriptionKey": "settings.fields.maxLoadedModels.description",
                        "type": "number",
                        "value": int(
                            db_settings.get(
                                MAX_LOADED_MODELS_KEY,
                                app_container.model_scheduler.max_loaded_models,
                            )
                        ),
                        "suffix": f"<= {app_container.model_scheduler.max_possible_loaded}",
                    },
                    {
                        "key": "maxTasksPerSlot",
                        "labelKey": "settings.fields.maxTasksPerSlot.label",
                        "descriptionKey": "settings.fields.maxTasksPerSlot.description",
                        "type": "number",
                        "value": int(
                            db_settings.get(
                                MAX_TASKS_PER_SLOT_KEY,
                                app_container.model_scheduler.max_tasks_per_slot,
                            )
                        ),
                        "suffixKey": "settings.suffix.tasks",
                    },
                    {
                        "key": "externalVramWaitTimeoutSeconds",
                        "labelKey": "settings.fields.externalVramWaitTimeoutSeconds.label",
                        "descriptionKey": (
                            "settings.fields.externalVramWaitTimeoutSeconds.description"
                        ),
                        "type": "number",
                        "value": float(
                            db_settings.get(
                                EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
                                app_container.vram_allocator.external_vram_wait_timeout_seconds,
                            )
                        ),
                        "suffixKey": "settings.suffix.seconds",
                    },
                    {
                        "key": "internalVramWaitTimeoutSeconds",
                        "labelKey": "settings.fields.internalVramWaitTimeoutSeconds.label",
                        "descriptionKey": (
                            "settings.fields.internalVramWaitTimeoutSeconds.description"
                        ),
                        "type": "number",
                        "value": float(
                            db_settings.get(
                                INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
                                app_container.vram_allocator.internal_vram_wait_timeout_seconds,
                            )
                        ),
                        "suffixKey": "settings.suffix.seconds",
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
        gpu_devices = [
            {
                "deviceId": device_id,
                "enabled": device_id not in app_container.disabled_devices,
                **_get_gpu_device_info(device_id),
            }
            for device_id in app_container.all_device_ids
        ]
        return {
            "sections": sections,
            "gpuDevices": gpu_devices,
        }

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
            "maxLoadedModels",
            "maxTasksPerSlot",
            "externalVramWaitTimeoutSeconds",
            "internalVramWaitTimeoutSeconds",
            "gpuDisabledDevices",
        }
        updates = {k: v for k, v in payload.items() if k in allowed_keys}
        if not updates:
            raise HTTPException(
                status_code=422, detail="no updatable settings provided"
            )

        normalized_updates: dict[str, Any] = {}
        persisted_updates: dict[str, Any] = {}

        if "defaultProvider" in updates:
            default_provider = str(updates["defaultProvider"] or "").strip()
            if not default_provider:
                raise HTTPException(
                    status_code=422,
                    detail="defaultProvider must be a non-empty string",
                )
            normalized_updates["defaultProvider"] = default_provider
            persisted_updates["defaultProvider"] = default_provider

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
            persisted_updates["queueMaxSize"] = queue_max_size

        if "maxLoadedModels" in updates:
            try:
                max_loaded_models = int(updates["maxLoadedModels"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="maxLoadedModels must be an integer",
                ) from exc
            max_possible_loaded = app_container.model_scheduler.max_possible_loaded
            if max_loaded_models < 1 or max_loaded_models > max_possible_loaded:
                raise HTTPException(
                    status_code=422,
                    detail=f"maxLoadedModels must be between 1 and {max_possible_loaded}",
                )
            normalized_updates["maxLoadedModels"] = max_loaded_models
            persisted_updates[MAX_LOADED_MODELS_KEY] = max_loaded_models

        if "maxTasksPerSlot" in updates:
            try:
                max_tasks_per_slot = int(updates["maxTasksPerSlot"])
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="maxTasksPerSlot must be an integer",
                ) from exc
            if max_tasks_per_slot < 1:
                raise HTTPException(
                    status_code=422,
                    detail="maxTasksPerSlot must be >= 1",
                )
            normalized_updates["maxTasksPerSlot"] = max_tasks_per_slot
            persisted_updates[MAX_TASKS_PER_SLOT_KEY] = max_tasks_per_slot

        if "externalVramWaitTimeoutSeconds" in updates:
            try:
                external_vram_wait_timeout_seconds = float(
                    updates["externalVramWaitTimeoutSeconds"]
                )
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="externalVramWaitTimeoutSeconds must be a number",
                ) from exc
            if external_vram_wait_timeout_seconds <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="externalVramWaitTimeoutSeconds must be > 0",
                )
            normalized_updates["externalVramWaitTimeoutSeconds"] = (
                external_vram_wait_timeout_seconds
            )
            persisted_updates[EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY] = (
                external_vram_wait_timeout_seconds
            )

        if "internalVramWaitTimeoutSeconds" in updates:
            try:
                internal_vram_wait_timeout_seconds = float(
                    updates["internalVramWaitTimeoutSeconds"]
                )
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail="internalVramWaitTimeoutSeconds must be a number",
                ) from exc
            if internal_vram_wait_timeout_seconds <= 0:
                raise HTTPException(
                    status_code=422,
                    detail="internalVramWaitTimeoutSeconds must be > 0",
                )
            normalized_updates["internalVramWaitTimeoutSeconds"] = (
                internal_vram_wait_timeout_seconds
            )
            persisted_updates[INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY] = (
                internal_vram_wait_timeout_seconds
            )

        if "gpuDisabledDevices" in updates:
            try:
                parsed_disabled_devices = _parse_gpu_disabled_devices_update(
                    updates["gpuDisabledDevices"],
                    all_device_ids=app_container.all_device_ids,
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=str(exc),
                ) from exc
            ordered_disabled_devices = _ordered_disabled_devices(
                parsed_disabled_devices,
                app_container.all_device_ids,
            )
            normalized_updates["gpuDisabledDevices"] = ordered_disabled_devices
            persisted_updates[GPU_DISABLED_DEVICES_KEY] = ordered_disabled_devices

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
            persisted_updates["rateLimitPerHour"] = rate_limit_per_hour

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
            persisted_updates["rateLimitConcurrent"] = rate_limit_concurrent

        await app_container.settings_store.set_many(persisted_updates)

        if "gpuDisabledDevices" in normalized_updates:
            next_disabled_devices = set(normalized_updates["gpuDisabledDevices"])
            current_disabled_devices = set(app_container.disabled_devices)
            to_disable = next_disabled_devices - current_disabled_devices
            to_enable = current_disabled_devices - next_disabled_devices

            app_container.disabled_devices.clear()
            app_container.disabled_devices.update(next_disabled_devices)

            active_schedulers = tuple(app_container.model_registry.iter_schedulers())
            for scheduler in active_schedulers:
                for device_id in to_disable:
                    scheduler.disable(device_id)
                for device_id in to_enable:
                    scheduler.enable(device_id)

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

        if "maxLoadedModels" in normalized_updates or "maxTasksPerSlot" in normalized_updates:
            await app_container.model_scheduler.update_limits(
                max_loaded_models=normalized_updates.get("maxLoadedModels"),
                max_tasks_per_slot=normalized_updates.get("maxTasksPerSlot"),
            )

        if "externalVramWaitTimeoutSeconds" in normalized_updates:
            app_container.vram_allocator.set_external_vram_wait_timeout_seconds(
                normalized_updates["externalVramWaitTimeoutSeconds"]
            )
        if "internalVramWaitTimeoutSeconds" in normalized_updates:
            app_container.vram_allocator.set_internal_vram_wait_timeout_seconds(
                normalized_updates["internalVramWaitTimeoutSeconds"]
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
