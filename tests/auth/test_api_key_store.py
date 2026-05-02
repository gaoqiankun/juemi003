from __future__ import annotations

from pathlib import Path

import pytest
from gen3d.auth.api_key_store import ApiKeyStore


@pytest.fixture()
async def store(tmp_path: Path) -> ApiKeyStore:
    s = ApiKeyStore(tmp_path / "keys.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.anyio
async def test_record_usage_increments(store: ApiKeyStore) -> None:
    key = await store.create_user_key("test-key")
    key_id = key["key_id"]

    await store.record_usage(key_id)
    await store.record_usage(key_id)
    await store.record_usage(key_id)

    info = await store.get_user_key(key_id)
    assert info is not None
    assert info["request_count"] == 3
    assert info["last_used_at"] is not None


@pytest.mark.anyio
async def test_get_usage_stats(store: ApiKeyStore) -> None:
    k1 = await store.create_user_key("key-1")
    k2 = await store.create_user_key("key-2")

    await store.record_usage(k1["key_id"])
    await store.record_usage(k1["key_id"])
    await store.record_usage(k2["key_id"])

    # deactivate k2
    await store.set_active(k2["key_id"], False)

    stats = await store.get_usage_stats()
    assert stats["total_keys"] == 2
    assert stats["active_keys"] == 1
    assert stats["total_requests"] == 3


@pytest.mark.anyio
async def test_list_keys_includes_usage_fields(store: ApiKeyStore) -> None:
    await store.create_user_key("my-key")
    keys = await store.list_user_keys()
    assert len(keys) == 1
    key = keys[0]
    assert "last_used_at" in key
    assert "request_count" in key
    assert key["request_count"] == 0
    assert key["last_used_at"] is None
