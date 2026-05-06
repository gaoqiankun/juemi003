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


_ALLOWED_UPDATE_KEYS = {
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
_RATE_LIMIT_UPDATE_KEYS = {"rateLimitConcurrent", "rateLimitPerHour"}
_MODEL_SCHEDULER_UPDATE_KEYS = {"maxLoadedModels", "maxTasksPerSlot"}


async def update_settings(
    payload: dict,
    app_container: AppContainer,
) -> dict:
    updates = {k: v for k, v in payload.items() if k in _ALLOWED_UPDATE_KEYS}
    if not updates:
        raise HTTPException(status_code=422, detail="no updatable settings provided")

    normalized_updates: dict[str, Any] = {}
    persisted_updates: dict[str, Any] = {}

    for (
        normalized_key,
        normalized_value,
        persisted_key,
        persisted_value,
    ) in _validated_update_results(updates, app_container):
        normalized_updates[normalized_key] = normalized_value
        persisted_updates[persisted_key] = persisted_value

    await app_container.settings_store.set_many(persisted_updates)
    await _apply_side_effects(normalized_updates, app_container)

    return {"ok": True, "updated": list(normalized_updates.keys())}


def _validate_default_provider(updates: dict) -> tuple[str, str, str] | None:
    if "defaultProvider" not in updates:
        return None
    default_provider = str(updates["defaultProvider"] or "").strip()
    if not default_provider:
        raise HTTPException(
            status_code=422,
            detail="defaultProvider must be a non-empty string",
        )
    return default_provider, "defaultProvider", default_provider


def _validate_queue_max_size(updates: dict) -> tuple[int, str, int] | None:
    if "queueMaxSize" not in updates:
        return None
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
    return queue_max_size, "queueMaxSize", queue_max_size


def _validate_max_loaded_models(updates: dict) -> tuple[int, str, int] | None:
    if "maxLoadedModels" not in updates:
        return None
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
    return max_loaded_models, MAX_LOADED_MODELS_KEY, max_loaded_models


def _validate_max_tasks_per_slot(updates: dict) -> tuple[int, str, int] | None:
    if "maxTasksPerSlot" not in updates:
        return None
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
    return max_tasks_per_slot, MAX_TASKS_PER_SLOT_KEY, max_tasks_per_slot


def _validate_external_vram_wait_timeout_seconds(
    updates: dict,
) -> tuple[float, str, float] | None:
    if "externalVramWaitTimeoutSeconds" not in updates:
        return None
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
    return (
        external_vram_wait_timeout_seconds,
        EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
        external_vram_wait_timeout_seconds,
    )


def _validate_internal_vram_wait_timeout_seconds(
    updates: dict,
) -> tuple[float, str, float] | None:
    if "internalVramWaitTimeoutSeconds" not in updates:
        return None
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
    return (
        internal_vram_wait_timeout_seconds,
        INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY,
        internal_vram_wait_timeout_seconds,
    )


def _validate_gpu_disabled_devices(
    updates: dict,
    all_device_ids: tuple[str, ...],
) -> tuple[list[str], str, list[str]] | None:
    if "gpuDisabledDevices" not in updates:
        return None
    try:
        parsed_disabled_devices = parse_gpu_disabled_devices_update(
            updates["gpuDisabledDevices"],
            all_device_ids=all_device_ids,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    ordered_devices = ordered_disabled_devices(
        parsed_disabled_devices,
        all_device_ids,
    )
    return ordered_devices, GPU_DISABLED_DEVICES_KEY, ordered_devices


def _validate_rate_limit_per_hour(updates: dict) -> tuple[int, str, int] | None:
    if "rateLimitPerHour" not in updates:
        return None
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
    return rate_limit_per_hour, "rateLimitPerHour", rate_limit_per_hour


def _validate_rate_limit_concurrent(updates: dict) -> tuple[int, str, int] | None:
    if "rateLimitConcurrent" not in updates:
        return None
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
    return rate_limit_concurrent, "rateLimitConcurrent", rate_limit_concurrent


def _validated_update_results(updates: dict, app_container: AppContainer):
    leading_validation_results = (
        ("defaultProvider", _validate_default_provider(updates)),
        ("queueMaxSize", _validate_queue_max_size(updates)),
        ("maxLoadedModels", _validate_max_loaded_models(updates)),
        ("maxTasksPerSlot", _validate_max_tasks_per_slot(updates)),
        (
            "externalVramWaitTimeoutSeconds",
            _validate_external_vram_wait_timeout_seconds(updates),
        ),
        (
            "internalVramWaitTimeoutSeconds",
            _validate_internal_vram_wait_timeout_seconds(updates),
        ),
    )
    for normalized_key, result in leading_validation_results:
        if result is not None:
            normalized_value, persisted_key, persisted_value = result
            yield normalized_key, normalized_value, persisted_key, persisted_value

    if "gpuDisabledDevices" in updates:
        result = _validate_gpu_disabled_devices(updates, app_container.all_device_ids)
        if result is not None:
            normalized_value, persisted_key, persisted_value = result
            yield (
                "gpuDisabledDevices",
                normalized_value,
                persisted_key,
                persisted_value,
            )

    trailing_validation_results = (
        ("rateLimitPerHour", _validate_rate_limit_per_hour(updates)),
        ("rateLimitConcurrent", _validate_rate_limit_concurrent(updates)),
    )
    for normalized_key, result in trailing_validation_results:
        if result is not None:
            normalized_value, persisted_key, persisted_value = result
            yield normalized_key, normalized_value, persisted_key, persisted_value


async def _apply_side_effects(
    normalized_updates: dict[str, Any],
    app_container: AppContainer,
) -> None:
    _apply_gpu_disabled_devices_update(normalized_updates, app_container)
    _apply_queue_max_size_update(normalized_updates, app_container)
    await _apply_rate_limit_updates(normalized_updates, app_container)
    await _apply_model_scheduler_limit_updates(normalized_updates, app_container)
    _apply_vram_wait_timeout_updates(normalized_updates, app_container)


def _apply_gpu_disabled_devices_update(
    normalized_updates: dict[str, Any],
    app_container: AppContainer,
) -> None:
    if "gpuDisabledDevices" not in normalized_updates:
        return
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


def _apply_queue_max_size_update(
    normalized_updates: dict[str, Any],
    app_container: AppContainer,
) -> None:
    if "queueMaxSize" in normalized_updates:
        app_container.engine.update_queue_capacity(normalized_updates["queueMaxSize"])


async def _apply_rate_limit_updates(
    normalized_updates: dict[str, Any],
    app_container: AppContainer,
) -> None:
    if not _RATE_LIMIT_UPDATE_KEYS.intersection(normalized_updates):
        return
    await app_container.rate_limiter.update_limits(
        max_concurrent=normalized_updates.get("rateLimitConcurrent"),
        max_requests_per_hour=normalized_updates.get("rateLimitPerHour"),
    )


async def _apply_model_scheduler_limit_updates(
    normalized_updates: dict[str, Any],
    app_container: AppContainer,
) -> None:
    if not _MODEL_SCHEDULER_UPDATE_KEYS.intersection(normalized_updates):
        return
    await app_container.model_scheduler.update_limits(
        max_loaded_models=normalized_updates.get("maxLoadedModels"),
        max_tasks_per_slot=normalized_updates.get("maxTasksPerSlot"),
    )


def _apply_vram_wait_timeout_updates(
    normalized_updates: dict[str, Any],
    app_container: AppContainer,
) -> None:
    if "externalVramWaitTimeoutSeconds" in normalized_updates:
        app_container.vram_allocator.set_external_vram_wait_timeout_seconds(
            normalized_updates["externalVramWaitTimeoutSeconds"]
        )
    if "internalVramWaitTimeoutSeconds" in normalized_updates:
        app_container.vram_allocator.set_internal_vram_wait_timeout_seconds(
            normalized_updates["internalVramWaitTimeoutSeconds"]
        )
