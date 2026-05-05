from __future__ import annotations

import json
from datetime import UTC, datetime

import aiosqlite


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def row_to_dict(row: aiosqlite.Row) -> dict:
    config = json.loads(row["config_json"]) if row["config_json"] else {}
    vram_gb = normalize_vram_gb(row["vram_gb"])
    weight_vram_mb = normalize_optional_vram_mb(row["weight_vram_mb"])
    inference_vram_mb = normalize_optional_vram_mb(row["inference_vram_mb"])
    weight_source = normalize_weight_source(row["weight_source"])
    download_status = normalize_download_status(row["download_status"])
    download_progress = normalize_download_progress(row["download_progress"])
    download_speed_bps = normalize_download_speed_bps(row["download_speed_bps"])
    download_error = normalize_optional_text(row["download_error"])
    resolved_path = normalize_optional_text(row["resolved_path"])
    return {
        "id": str(row["id"]),
        "provider_type": str(row["provider_type"]),
        "display_name": str(row["display_name"]),
        "model_path": str(row["model_path"]),
        "weight_source": weight_source,
        "download_status": download_status,
        "download_progress": download_progress,
        "download_speed_bps": download_speed_bps,
        "download_error": download_error,
        "resolved_path": resolved_path,
        "is_enabled": bool(row["is_enabled"]),
        "is_default": bool(row["is_default"]),
        "min_vram_mb": int(row["min_vram_mb"]),
        "vram_gb": vram_gb,
        "weight_vram_mb": weight_vram_mb,
        "inference_vram_mb": inference_vram_mb,
        "config": config,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def normalize_vram_gb(value: object) -> float | None:
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return round(normalized, 3)


def normalize_optional_vram_mb(value: object) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return None
    return normalized


def normalize_weight_source(value: object) -> str:
    normalized = str(value or "huggingface").strip().lower()
    if normalized not in {"huggingface", "url", "local"}:
        return "huggingface"
    return normalized


def normalize_download_status(value: object) -> str:
    normalized = str(value or "done").strip().lower()
    if normalized not in {"pending", "downloading", "done", "error"}:
        return "done"
    return normalized


def normalize_download_progress(value: object) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, normalized))


def normalize_download_speed_bps(value: object) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


def normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
