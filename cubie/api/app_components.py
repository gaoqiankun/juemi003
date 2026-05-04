from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from cubie.api.helpers.artifacts import build_artifact_store
from cubie.auth.api_key_store import ApiKeyStore
from cubie.core.config import ServingConfig
from cubie.core.gpu import resolve_device_ids
from cubie.core.observability.metrics import (
    increment_vram_acquire_inference,
    increment_vram_evict,
    observe_vram_acquire_inference_wait,
)
from cubie.core.security import TokenRateLimiter
from cubie.model.base import ModelProviderConfigurationError
from cubie.model.dep_store import DepInstanceStore, ModelDepRequirementsStore
from cubie.model.registry import ModelRegistry
from cubie.model.scheduler import ModelScheduler
from cubie.model.store import ModelStore
from cubie.model.weight import WeightManager
from cubie.settings.store import SettingsStore
from cubie.stage.export.preview_renderer_service import (
    PreviewRendererService,
    PreviewRendererServiceProtocol,
)
from cubie.stage.export.stage import ExportStage
from cubie.stage.gpu.stage import GPUStage
from cubie.stage.preprocess.stage import PreprocessStage
from cubie.task.engine import AsyncGen3DEngine
from cubie.task.pipeline import PipelineCoordinator
from cubie.task.store import TaskStore
from cubie.vram.allocator import VRAMAllocator, VRAMMetricsHook
from cubie.vram.helpers import detect_device_total_vram_mb


def build_app_components(
    *,
    config: ServingConfig,
    webhook_sender: Any,
    preview_renderer_service: PreviewRendererServiceProtocol | None,
    runtime_builder: Callable[..., Any],
) -> dict[str, Any]:
    all_device_ids = resolve_device_ids(config)
    vram_allocator = VRAMAllocator(
        device_totals_mb=detect_device_total_vram_mb(all_device_ids),
    )
    vram_allocator.set_metrics_hook(
        VRAMMetricsHook(
            on_acquire_outcome=increment_vram_acquire_inference,
            on_acquire_wait=observe_vram_acquire_inference_wait,
            on_evict=increment_vram_evict,
        )
    )
    if not config.is_mock_provider:
        from cubie.vram.probe import probe_device_free_mb

        vram_allocator.set_vram_probe(probe_device_free_mb)

    disabled_devices: set[str] = set()
    task_store = TaskStore(config.database_path)
    api_key_store = ApiKeyStore(config.database_path)
    model_store = ModelStore(config.database_path)
    dep_instance_store = DepInstanceStore(config.database_path)
    model_dep_requirements_store = ModelDepRequirementsStore(config.database_path)
    settings_store = SettingsStore(config.database_path)
    artifact_store = build_artifact_store(config)
    preview_renderer = preview_renderer_service or PreviewRendererService()

    async def build_runtime_for_device(
        model_name: str,
        *,
        device_id: str,
        measurement_callback=None,
    ):
        normalized_model_name = str(model_name).strip().lower()
        normalized_device_id = str(device_id).strip()
        if not normalized_device_id:
            raise ModelProviderConfigurationError(
                "device_id is required for model runtime creation: "
                f"{normalized_model_name}"
            )
        if normalized_device_id not in set(all_device_ids):
            raise ModelProviderConfigurationError(
                f"unknown GPU device: {normalized_device_id}"
            )
        if normalized_device_id in disabled_devices:
            raise ModelProviderConfigurationError(
                f"GPU device is disabled: {normalized_device_id}"
            )
        try:
            runtime = await runtime_builder(
                model_store,
                config,
                normalized_model_name,
                device_ids=(normalized_device_id,),
                disabled_devices=disabled_devices,
                measurement_callback=measurement_callback,
            )
        except TypeError as exc:
            message = str(exc)
            if (
                "unexpected keyword argument 'device_ids'" not in message
                and "unexpected keyword argument 'disabled_devices'" not in message
                and "unexpected keyword argument 'measurement_callback'" not in message
            ):
                raise
            runtime = await runtime_builder(model_store, config, normalized_model_name)
        runtime.assigned_device_id = normalized_device_id
        return runtime

    def create_model_worker(
        model_name: str,
        *,
        device_id: str | None = None,
        exclude_device_ids: Iterable[str] | None = None,
    ):
        _ = device_id
        _ = exclude_device_ids
        from cubie.model.worker import ModelWorker

        return ModelWorker(
            model_id=model_name,
            allocator=vram_allocator,
            gpu_worker_factory=build_runtime_for_device,
            db_store=model_store,
        )

    model_registry = ModelRegistry(create_model_worker)
    model_scheduler = ModelScheduler(
        model_registry=model_registry,
        task_store=task_store,
        model_store=model_store,
        settings_store=settings_store,
        enabled=not config.is_mock_provider,
        gpu_device_count=len(all_device_ids),
    )
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
                preview_renderer_service=preview_renderer,
                task_store=task_store,
                delay_ms=config.mock_export_delay_ms,
            ),
        ],
        inference_allocator=vram_allocator,
        model_registry=model_registry,
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
    return {
        "config": config,
        "all_device_ids": all_device_ids,
        "disabled_devices": disabled_devices,
        "task_store": task_store,
        "api_key_store": api_key_store,
        "rate_limiter": rate_limiter,
        "artifact_store": artifact_store,
        "preview_renderer_service": preview_renderer,
        "model_registry": model_registry,
        "pipeline": pipeline,
        "engine": engine,
        "model_store": model_store,
        "dep_instance_store": dep_instance_store,
        "model_dep_requirements_store": model_dep_requirements_store,
        "settings_store": settings_store,
        "vram_allocator": vram_allocator,
        "model_scheduler": model_scheduler,
        "weight_manager": weight_manager,
        "model_download_tasks": {},
    }
