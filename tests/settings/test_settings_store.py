from __future__ import annotations

from pathlib import Path

import pytest
from gen3d.settings.store import SettingsStore


@pytest.fixture()
async def store(tmp_path: Path) -> SettingsStore:
    s = SettingsStore(tmp_path / "settings.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.anyio
async def test_set_and_get(store: SettingsStore) -> None:
    await store.set("theme", "dark")
    assert await store.get("theme") == "dark"

    # overwrite
    await store.set("theme", "light")
    assert await store.get("theme") == "light"


@pytest.mark.anyio
async def test_get_all(store: SettingsStore) -> None:
    await store.set("a", 1)
    await store.set("b", [1, 2, 3])
    result = await store.get_all()
    assert result == {"a": 1, "b": [1, 2, 3]}


@pytest.mark.anyio
async def test_set_many(store: SettingsStore) -> None:
    await store.set_many({"x": 10, "y": {"nested": True}})
    assert await store.get("x") == 10
    assert await store.get("y") == {"nested": True}


@pytest.mark.anyio
async def test_delete(store: SettingsStore) -> None:
    await store.set("temp", "value")
    assert await store.delete("temp") is True
    assert await store.get("temp") is None
    # delete non-existent
    assert await store.delete("temp") is False


@pytest.mark.anyio
async def test_get_nonexistent(store: SettingsStore) -> None:
    assert await store.get("no_such_key") is None
