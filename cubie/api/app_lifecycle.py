from __future__ import annotations

from typing import Any

from cubie.api.routers.admin.models.downloads import cancel_model_download_task
from cubie.core.gpu import (
    normalize_persisted_disabled_devices,
    ordered_disabled_devices,
)
from cubie.core.hf import normalize_hf_endpoint, set_hf_endpoint
from cubie.core.observability.metrics import initialize_vram_metrics
from cubie.settings.store import (
    EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    GPU_DISABLED_DEVICES_KEY,
    INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
)

HF_ENDPOINT_SETTING_KEY = "hfEndpoint"


async def initialize_app_container(container: Any) -> None:
    container.config.uploads_dir.mkdir(parents=True, exist_ok=True)
    await container.task_store.initialize()
    await container.api_key_store.initialize()
    await container.model_store.initialize()
    await container.dep_instance_store.initialize()
    await container.model_dep_requirements_store.initialize()
    await container.settings_store.initialize()
    initialize_vram_metrics(container.all_device_ids)
    await apply_persisted_vram_settings(container)
    await container.model_scheduler.initialize()
    await initialize_startup_models(container)
    configured_hf_endpoint = await container.settings_store.get(HF_ENDPOINT_SETTING_KEY)
    set_hf_endpoint(normalize_hf_endpoint(configured_hf_endpoint, strict=False))
    await container.artifact_store.initialize()
    await container.preview_renderer_service.start()


async def apply_persisted_vram_settings(container: Any) -> None:
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
    normalized_disabled_devices = normalize_persisted_disabled_devices(
        persisted_disabled_devices,
        container.all_device_ids,
    )
    container.disabled_devices.clear()
    container.disabled_devices.update(normalized_disabled_devices)
    if persisted_disabled_devices is None:
        return
    normalized_disabled_list = ordered_disabled_devices(
        normalized_disabled_devices,
        container.all_device_ids,
    )
    if persisted_disabled_devices != normalized_disabled_list:
        await container.settings_store.set(
            GPU_DISABLED_DEVICES_KEY,
            normalized_disabled_list,
        )


async def initialize_startup_models(container: Any) -> None:
    default_models = await container.model_store.list_models(
        extra_statuses=(
            frozenset({"pending"})
            if container.config.is_mock_provider
            else frozenset()
        ),
    )
    default_model_ids = tuple(
        str(model["id"]).strip().lower()
        for model in default_models
        if model.get("is_default") and str(model.get("id") or "").strip()
    )
    container.engine.set_startup_models(default_model_ids)


async def close_app_container(container: Any) -> None:
    download_task_ids = tuple(container.model_download_tasks.keys())
    for model_id in download_task_ids:
        await cancel_model_download_task(container, model_id)
    await container.settings_store.close()
    await container.model_dep_requirements_store.close()
    await container.dep_instance_store.close()
    await container.model_store.close()
    await container.api_key_store.close()
    await container.task_store.close()
