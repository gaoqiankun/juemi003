from __future__ import annotations

from typing import TYPE_CHECKING

from cubie.core.gpu import get_gpu_device_info
from cubie.settings.store import (
    EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    MAX_LOADED_MODELS_KEY,
    MAX_TASKS_PER_SLOT_KEY,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


async def get_settings(app_container: AppContainer) -> dict:
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
            **get_gpu_device_info(device_id),
        }
        for device_id in app_container.all_device_ids
    ]
    return {
        "sections": sections,
        "gpuDevices": gpu_devices,
    }
