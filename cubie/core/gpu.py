from __future__ import annotations

from typing import Any

from cubie.core.config import ServingConfig


def resolve_device_ids(config: ServingConfig) -> tuple[str, ...]:
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

def get_gpu_device_info(device_id: str) -> dict:
    try:
        import torch  # type: ignore[import-not-found]
        props = torch.cuda.get_device_properties(int(device_id))
        total_memory_gb = round(props.total_memory / (1024 ** 3), 1)
        return {"name": props.name, "totalMemoryGb": total_memory_gb}
    except Exception:
        return {"name": None, "totalMemoryGb": None}

def normalize_persisted_disabled_devices(
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

def ordered_disabled_devices(
    disabled_devices: set[str],
    all_device_ids: tuple[str, ...],
) -> list[str]:
    return [device_id for device_id in all_device_ids if device_id in disabled_devices]

def parse_gpu_disabled_devices_update(
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
