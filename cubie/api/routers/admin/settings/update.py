from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

from cubie.core.gpu import ordered_disabled_devices, parse_gpu_disabled_devices_update
from cubie.settings.store import (
    EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    GPU_DISABLED_DEVICES_KEY,
    INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
    MAX_LOADED_MODELS_KEY,
    MAX_TASKS_PER_SLOT_KEY,
)

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


async def update_settings(
    payload: dict,
    app_container: AppContainer,
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
            parsed_disabled_devices = parse_gpu_disabled_devices_update(
                updates["gpuDisabledDevices"],
                all_device_ids=app_container.all_device_ids,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=str(exc),
            ) from exc
        ordered_devices = ordered_disabled_devices(
            parsed_disabled_devices,
            app_container.all_device_ids,
        )
        normalized_updates["gpuDisabledDevices"] = ordered_devices
        persisted_updates[GPU_DISABLED_DEVICES_KEY] = ordered_devices

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
