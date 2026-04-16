from __future__ import annotations

from typing import Any

import structlog
from gen3d.api.helpers.gpu_device import _get_gpu_device_info

_DEFAULT_DEVICE_TOTAL_VRAM_MB = 24 * 1024
_DEFAULT_WEIGHT_RATIO = 0.75

_logger = structlog.get_logger("gen3d.api.server")


def _normalize_vram_mb(value: object) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if normalized < 0:
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
