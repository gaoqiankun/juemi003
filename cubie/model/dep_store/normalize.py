from __future__ import annotations

import aiosqlite

_DEP_STATUSES = frozenset({"pending", "downloading", "done", "error"})
_WEIGHT_SOURCES = frozenset({"huggingface", "local", "url"})


def normalize_required_text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def normalize_dep_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    if normalized not in _DEP_STATUSES:
        return "pending"
    return normalized


def normalize_weight_source(value: object) -> str:
    normalized = str(value or "huggingface").strip().lower()
    if normalized not in _WEIGHT_SOURCES:
        return "huggingface"
    return normalized


def normalize_weight_source_strict(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _WEIGHT_SOURCES:
        raise ValueError("weight_source must be one of: huggingface, local, url")
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


def row_to_dep_instance(row: aiosqlite.Row) -> dict:
    return {
        "id": str(row["id"]),
        "dep_type": str(row["dep_type"]),
        "hf_repo_id": str(row["hf_repo_id"]),
        "display_name": str(row["display_name"]),
        "weight_source": normalize_weight_source(row["weight_source"]),
        "dep_model_path": normalize_optional_text(row["dep_model_path"]),
        "resolved_path": normalize_optional_text(row["resolved_path"]),
        "download_status": normalize_dep_status(row["download_status"]),
        "download_progress": normalize_download_progress(row["download_progress"]),
        "download_speed_bps": normalize_download_speed_bps(row["download_speed_bps"]),
        "download_error": normalize_optional_text(row["download_error"]),
        "created_at": normalize_optional_text(row["created_at"]),
    }
