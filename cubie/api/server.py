from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
import structlog
from fastapi import FastAPI, HTTPException, Request, status

from cubie.api.app_components import build_app_components
from cubie.api.app_lifecycle import close_app_container, initialize_app_container
from cubie.api.dev_proxy import (
    forward_dev_proxy_request,
    rewrite_legacy_api_path,
    should_proxy_dev_request,
)
from cubie.api.preflight import run_real_mode_preflight  # noqa: F401
from cubie.api.routers import include_api_routers
from cubie.artifact.store import ArtifactStore
from cubie.core.config import ServingConfig
from cubie.model.runtime import build_model_runtime
from cubie.model.store import ModelStore
from cubie.stage.export.preview_renderer_service import (
    PreviewRendererServiceProtocol,
)
from cubie.vram.helpers import (
    clamp_inference_estimate_mb,  # noqa: F401 — re-exported for tests
    normalize_vram_mb,
)

if TYPE_CHECKING:
    from cubie.auth.api_key_store import ApiKeyStore
    from cubie.core.security import TokenRateLimiter
    from cubie.model.dep_store import DepInstanceStore, ModelDepRequirementsStore
    from cubie.model.registry import ModelRegistry
    from cubie.model.scheduler import ModelScheduler
    from cubie.model.weight import WeightManager
    from cubie.settings.store import SettingsStore
    from cubie.task.engine import AsyncGen3DEngine
    from cubie.task.pipeline import PipelineCoordinator
    from cubie.task.store import TaskStore
    from cubie.vram.allocator import VRAMAllocator

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


def update_vram_estimate(
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


async def persist_vram_estimate_measurement(
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
    stored_mb = normalize_vram_mb(model_definition.get(field_name))
    decision = update_vram_estimate(
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


def create_app(
    config: ServingConfig | None = None,
    webhook_sender=None,
    preview_renderer_service: PreviewRendererServiceProtocol | None = None,
) -> FastAPI:
    config = config or ServingConfig()
    container = AppContainer(
        **build_app_components(
            config=config,
            webhook_sender=webhook_sender,
            preview_renderer_service=preview_renderer_service,
            runtime_builder=build_model_runtime,
        )
    )
    proxy_client: httpx.AsyncClient | None = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal proxy_client
        app.state.container = container
        await initialize_app_container(container)
        if config.dev_proxy_target is not None:
            proxy_client = httpx.AsyncClient(
                follow_redirects=False,
                timeout=httpx.Timeout(connect=10.0, read=None, write=30.0, pool=30.0),
            )
        await container.engine.start()
        yield
        await container.engine.stop()
        await container.preview_renderer_service.stop()
        if proxy_client is not None:
            await proxy_client.aclose()
        await close_app_container(container)

    app = FastAPI(title=config.service_name, lifespan=lifespan)

    @app.middleware("http")
    async def maybe_proxy_dev_requests(request: Request, call_next):
        rewrite_legacy_api_path(request.scope)
        if not should_proxy_dev_request(request, config):
            return await call_next(request)
        if proxy_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="dev proxy client is not ready",
            )
        return await forward_dev_proxy_request(
            request=request,
            proxy_client=proxy_client,
            proxy_target=config.dev_proxy_target,
        )

    include_api_routers(app, container)

    return app
