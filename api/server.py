from __future__ import annotations

import asyncio
import json
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
from gen3d.api.helpers import hf as _hf_helpers
from gen3d.api.helpers.artifacts import (
    _artifact_exists,
    _dispatch_preview_render,
    _extract_artifact_filename,
    _resolve_dev_local_model_path,
    build_artifact_store,
)
from gen3d.api.helpers.deps import _build_dep_response_rows, _prepare_dep_assignments
from gen3d.api.helpers.gpu_device import (
    _get_gpu_device_info,
    _normalize_persisted_disabled_devices,
    _ordered_disabled_devices,
    _parse_gpu_disabled_devices_update,
    _resolve_device_ids,
)
from gen3d.api.helpers.hf import (
    _current_hf_endpoint,
    _ensure_hf_client_available,
    _normalize_hf_endpoint,
    _resolve_hf_status,
    _set_hf_endpoint,
)
from gen3d.api.helpers.keys import (
    _build_user_key_label_map,
    _resolve_task_owner,
    _safe_record_usage,
)
from gen3d.api.helpers.preflight import (
    run_real_mode_preflight,  # noqa: F401
    validate_runtime_security_config,
)
from gen3d.api.helpers.runtime import (
    _resolve_model_definition_for_runtime,
    build_model_runtime,
)
from gen3d.api.helpers.tasks import _friendly_model_error_message, _map_task_status
from gen3d.api.helpers.vram import (
    _clamp_inference_estimate_mb,  # noqa: F401
    _detect_device_total_vram_mb,
    _normalize_vram_mb,
    _resolve_weight_vram_mb,
)
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
from gen3d.stages.gpu.stage import GPUStage
from gen3d.stages.preprocess.stage import PreprocessStage
from gen3d.storage.api_key_store import (
    KEY_MANAGER_SCOPE,
    METRICS_SCOPE,
    TASK_VIEWER_SCOPE,
    USER_KEY_SCOPE,
    ApiKeyStore,
)
from gen3d.storage.artifact_store import ArtifactStore
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
from starlette.background import BackgroundTask
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import Scope

HF_ENDPOINT_SETTING_KEY = "hfEndpoint"

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
_logger = structlog.get_logger(__name__)
_VRAM_ESTIMATE_FIELDS = frozenset({"weight_vram_mb", "inference_vram_mb"})
_VRAM_ESTIMATE_THRESHOLD_RATIO = 0.15
_VRAM_ESTIMATE_MIN_DELTA_MB = 1024
_VRAM_ESTIMATE_EMA_OLD_WEIGHT = 0.7
_VRAM_ESTIMATE_EMA_NEW_WEIGHT = 0.3


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


@dataclass(slots=True, frozen=True)
class VramEstimateDecision:
    model_id: str
    field_name: str
    measured_mb: int
    stored_mb: int | None
    new_mb: int
    should_update: bool


def _update_vram_estimate(
    model_id: str,
    field_name: str,
    measured_mb: int,
    *,
    stored_mb: int | None,
) -> VramEstimateDecision:
    normalized_model_id = str(model_id).strip().lower()
    normalized_field = str(field_name).strip()
    if normalized_field not in _VRAM_ESTIMATE_FIELDS:
        raise ValueError(f"unsupported VRAM estimate field: {field_name}")
    normalized_measured_mb = max(int(measured_mb), 0)
    normalized_stored_mb = (
        max(int(stored_mb), 0)
        if stored_mb is not None
        else None
    )
    if normalized_stored_mb is None:
        return VramEstimateDecision(
            model_id=normalized_model_id,
            field_name=normalized_field,
            measured_mb=normalized_measured_mb,
            stored_mb=None,
            new_mb=normalized_measured_mb,
            should_update=True,
        )
    if normalized_field == "weight_vram_mb":
        should_update = normalized_measured_mb != normalized_stored_mb
        return VramEstimateDecision(
            model_id=normalized_model_id,
            field_name=normalized_field,
            measured_mb=normalized_measured_mb,
            stored_mb=normalized_stored_mb,
            new_mb=normalized_measured_mb,
            should_update=should_update,
        )
    threshold_mb = max(
        normalized_stored_mb * _VRAM_ESTIMATE_THRESHOLD_RATIO,
        _VRAM_ESTIMATE_MIN_DELTA_MB,
    )
    should_update = abs(normalized_measured_mb - normalized_stored_mb) > threshold_mb
    new_mb = int(
        round(
            (_VRAM_ESTIMATE_EMA_OLD_WEIGHT * normalized_stored_mb)
            + (_VRAM_ESTIMATE_EMA_NEW_WEIGHT * normalized_measured_mb)
        )
    )
    return VramEstimateDecision(
        model_id=normalized_model_id,
        field_name=normalized_field,
        measured_mb=normalized_measured_mb,
        stored_mb=normalized_stored_mb,
        new_mb=new_mb,
        should_update=should_update,
    )


async def _persist_vram_estimate_measurement(
    model_store: ModelStore,
    *,
    model_id: str,
    field_name: str,
    measured_mb: int,
    device_id: str | None,
) -> VramEstimateDecision | None:
    normalized_model_id = str(model_id).strip().lower()
    model_definition = await model_store.get_model(normalized_model_id)
    if model_definition is None:
        _logger.warning(
            "vram_measure.model_not_found",
            model_name=normalized_model_id,
            device_id=device_id,
            field=field_name,
            measured_mb=measured_mb,
        )
        return None
    stored_mb = _normalize_vram_mb(model_definition.get(field_name))
    decision = _update_vram_estimate(
        normalized_model_id,
        field_name,
        measured_mb,
        stored_mb=stored_mb,
    )
    action = "update" if decision.should_update else "stable"
    if decision.should_update:
        await model_store.update_model(
            normalized_model_id,
            **{field_name: decision.new_mb},
        )
    measure_prefix = (
        "weight_measure"
        if field_name == "weight_vram_mb"
        else "inference_measure"
    )
    event_name = (
        f"{measure_prefix}.updated"
        if action == "update"
        else f"{measure_prefix}.stable"
    )
    _logger.info(
        event_name,
        model_name=normalized_model_id,
        device_id=device_id,
        field=field_name,
        measured_mb=decision.measured_mb,
        stored_mb=decision.stored_mb,
        new_mb=decision.new_mb,
        action=action,
    )
    return decision

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
    pending_vram_measurement_tasks: set[asyncio.Task[None]] = set()
    weight_measurements_by_device: dict[str, dict[str, int]] = {}

    def _track_vram_measurement_task(task: asyncio.Task[None]) -> None:
        pending_vram_measurement_tasks.add(task)

        def _finalize(done_task: asyncio.Task[None]) -> None:
            pending_vram_measurement_tasks.discard(done_task)
            if done_task.cancelled():
                return
            error = done_task.exception()
            if error is None:
                return
            _logger.warning(
                "vram_measure.update_task_failed",
                error=str(error),
            )

        task.add_done_callback(_finalize)

    async def _apply_vram_estimate_update(
        model_id: str,
        field_name: str,
        measured_mb: int,
        *,
        device_id: str | None,
    ) -> None:
        await _persist_vram_estimate_measurement(
            model_store,
            model_id=model_id,
            field_name=field_name,
            measured_mb=measured_mb,
            device_id=device_id,
        )

    def _schedule_vram_estimate_update(
        model_id: str,
        field_name: str,
        measured_mb: int,
        *,
        device_id: str | None,
    ) -> None:
        update_task = asyncio.create_task(
            _apply_vram_estimate_update(
                model_id,
                field_name,
                measured_mb,
                device_id=device_id,
            )
        )
        _track_vram_measurement_task(update_task)

    async def _on_weight_measured(
        model_name: str,
        device_id: str,
        measured_weight_mb: int,
    ) -> None:
        normalized_model_name = str(model_name).strip().lower()
        normalized_device_id = str(device_id).strip()
        normalized_measured_mb = max(int(measured_weight_mb), 0)
        device_samples = weight_measurements_by_device.setdefault(
            normalized_model_name,
            {},
        )
        device_samples[normalized_device_id] = normalized_measured_mb
        positive_samples = [sample for sample in device_samples.values() if sample > 0]
        if len(positive_samples) >= 2:
            min_sample = min(positive_samples)
            max_sample = max(positive_samples)
            variance_ratio = (
                (max_sample - min_sample) / max_sample
                if max_sample > 0
                else 0.0
            )
            if variance_ratio > 0.2:
                _logger.warning(
                    "weight_measure.device_variance",
                    model_name=normalized_model_name,
                    variance_ratio=variance_ratio,
                    measurements=dict(sorted(device_samples.items())),
                )
        await _apply_vram_estimate_update(
            normalized_model_name,
            "weight_vram_mb",
            normalized_measured_mb,
            device_id=normalized_device_id or None,
        )
        vram_allocator.reserve(
            model_name=normalized_model_name,
            weight_vram_mb=normalized_measured_mb,
            allowed_device_ids=all_device_ids,
        )

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

        _inference_mb_holder: list[int | None] = [
            _normalize_vram_mb(model_definition.get("inference_vram_mb"))
        ]

        try:
            def on_inference_measured(
                callback_model_name: str,
                callback_device_id: str,
                inference_peak_mb: int,
            ) -> None:
                _inference_mb_holder[0] = max(int(inference_peak_mb), 1)
                _schedule_vram_estimate_update(
                    callback_model_name,
                    "inference_vram_mb",
                    int(inference_peak_mb),
                    device_id=callback_device_id,
                )

            try:
                runtime = await build_model_runtime(
                    model_store,
                    config,
                    model_name,
                    device_ids=(assigned_device_id,),
                    disabled_devices=disabled_devices,
                    measurement_callback=on_inference_measured,
                )
            except TypeError as exc:
                message = str(exc)
                if (
                    "unexpected keyword argument 'device_ids'" not in message
                    and "unexpected keyword argument 'disabled_devices'" not in message
                    and "unexpected keyword argument 'measurement_callback'" not in message
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
            formula = _clamp_inference_estimate_mb(
                raw_value=raw_value,
                model=normalized_model_name,
                batch_size=normalized_batch_size,
                options=options,
            )
            measured = _inference_mb_holder[0]
            if measured is not None:
                return max(formula, measured)
            return formula

        runtime.scheduler.configure_inference_admission(
            allocator=vram_allocator,
            model_name=normalized_model_name,
            device_id=assigned_device_id,
            estimate_inference_vram_mb=estimate_inference_vram_mb,
        )
        runtime.assigned_device_id = assigned_device_id
        runtime.weight_vram_mb = weight_vram_mb
        return runtime

    model_registry = ModelRegistry(
        runtime_loader,
        weight_measurement_enabled=not config.is_mock_provider,
    )
    model_registry.add_model_unloaded_listener(vram_allocator.release)
    model_registry.add_weight_measured_listener(_on_weight_measured)
    model_scheduler = ModelScheduler(
        model_registry=model_registry,
        task_store=task_store,
        model_store=model_store,
        settings_store=settings_store,
        enabled=not config.is_mock_provider,
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
        if pending_vram_measurement_tasks:
            await asyncio.gather(
                *tuple(pending_vram_measurement_tasks),
                return_exceptions=True,
            )
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
        "/api/admin/models/{model_id}/unload",
        dependencies=[Depends(require_admin_token)],
    )
    async def unload_model(
        model_id: str,
        app_container: AppContainer = Depends(get_container),
    ) -> dict:
        model = await app_container.model_store.get_model(model_id)
        if model is None:
            raise HTTPException(status_code=404, detail="model not found")
        runtime_state = app_container.model_registry.get_state(model_id)
        if runtime_state == "not_loaded":
            raise HTTPException(status_code=400, detail="model is not loaded")
        await app_container.model_registry.unload(model_id)
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
            _hf_helpers._hf_login(token=token)
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
            _hf_helpers._hf_logout()
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
            if max_loaded_models < 1:
                raise HTTPException(
                    status_code=422,
                    detail="maxLoadedModels must be >= 1",
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
