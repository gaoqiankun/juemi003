from __future__ import annotations

from gen3d.auth.api_key_store import ApiKeyStore


def short_key_id(key_id: str | None) -> str:
    normalized = str(key_id or "").strip()
    if not normalized:
        return "-"
    if len(normalized) <= 8:
        return normalized
    return f"{normalized[:8]}…"

def resolve_task_owner(
    key_id: str | None,
    key_label_map: dict[str, str],
) -> tuple[str, str]:
    normalized_key_id = str(key_id or "").strip()
    if not normalized_key_id:
        return "-", ""
    label = key_label_map.get(normalized_key_id, "").strip()
    if label:
        return label, label
    return short_key_id(normalized_key_id), ""

async def build_user_key_label_map(
    api_key_store: ApiKeyStore,
) -> dict[str, str]:
    try:
        api_keys = await api_key_store.list_user_keys()
    except Exception:
        return {}
    label_map: dict[str, str] = {}
    for api_key in api_keys:
        key_id = str(api_key.get("key_id") or "").strip()
        label = str(api_key.get("label") or "").strip()
        if key_id and label:
            label_map[key_id] = label
    return label_map

async def safe_record_usage(api_key_store: ApiKeyStore, key_id: str) -> None:
    try:
        await api_key_store.record_usage(key_id)
    except Exception:
        pass
