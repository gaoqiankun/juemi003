from __future__ import annotations

import json
from datetime import UTC, datetime

import aiosqlite

from cubie.auth.api_key_store.constants import VALID_API_KEY_SCOPES


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def serialize_row(
    row: aiosqlite.Row,
) -> dict[str, str | bool | int | list[str] | None]:
    allowed_ips = deserialize_allowed_ips(row["allowed_ips"])
    result: dict[str, str | bool | int | list[str] | None] = {
        "key_id": str(row["key_id"]),
        "label": str(row["label"]),
        "scope": str(row["scope"]),
        "allowed_ips": allowed_ips,
        "created_at": str(row["created_at"]),
        "is_active": bool(row["is_active"]),
    }
    # Older rows/tests may select only the original columns.
    try:
        result["last_used_at"] = row["last_used_at"]
        result["request_count"] = int(row["request_count"])
    except (IndexError, KeyError):
        pass
    return result


def normalize_scope(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized not in VALID_API_KEY_SCOPES:
        raise ValueError(
            "scope must be one of: user, key_manager, task_viewer, metrics"
        )
    return normalized


def normalize_allowed_ips(raw: list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    normalized: list[str] = []
    for item in raw:
        value = str(item).strip()
        if not value:
            raise ValueError("allowed_ips must not contain empty values")
        if value not in normalized:
            normalized.append(value)
    return normalized


def deserialize_allowed_ips(raw: object) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        decoded = raw
    if not isinstance(decoded, list):
        return None
    return [str(item) for item in decoded]
