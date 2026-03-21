from __future__ import annotations

import pytest

from storage.model_store import ModelStore


@pytest.fixture()
async def store(tmp_path):
    s = ModelStore(tmp_path / "models.db")
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.anyio
async def test_initialize_seeds_defaults(store: ModelStore):
    models = await store.list_models()
    assert len(models) == 2
    ids = {m["id"] for m in models}
    assert ids == {"trellis2", "hunyuan3d"}

    trellis = await store.get_model("trellis2")
    assert trellis is not None
    assert trellis["provider_type"] == "trellis2"
    assert trellis["display_name"] == "TRELLIS2"
    assert trellis["is_enabled"] is True
    assert trellis["is_default"] is True

    hunyuan = await store.get_model("hunyuan3d")
    assert hunyuan is not None
    assert hunyuan["is_enabled"] is False
    assert hunyuan["is_default"] is False


@pytest.mark.anyio
async def test_list_models(store: ModelStore):
    models = await store.list_models()
    assert isinstance(models, list)
    assert len(models) == 2
    # sorted by created_at — both seeded at the same time, order is stable
    assert models[0]["id"] == "trellis2"
    assert models[1]["id"] == "hunyuan3d"


@pytest.mark.anyio
async def test_create_and_get_model(store: ModelStore):
    created = await store.create_model(
        id="test-model",
        provider_type="test",
        display_name="Test Model",
        model_path="org/test-model",
        min_vram_mb=16000,
        config={"key": "value"},
    )
    assert created["id"] == "test-model"
    assert created["provider_type"] == "test"
    assert created["is_enabled"] is True
    assert created["is_default"] is False
    assert created["min_vram_mb"] == 16000
    assert created["config"] == {"key": "value"}

    fetched = await store.get_model("test-model")
    assert fetched is not None
    assert fetched["id"] == "test-model"
    assert fetched["config"] == {"key": "value"}

    # get non-existent
    assert await store.get_model("no-such-model") is None


@pytest.mark.anyio
async def test_update_model_set_default_clears_others(store: ModelStore):
    # trellis2 is the default seed
    default = await store.get_default_model()
    assert default is not None
    assert default["id"] == "trellis2"

    # Set hunyuan3d as default — should clear trellis2
    updated = await store.update_model("hunyuan3d", is_default=True)
    assert updated is not None
    assert updated["is_default"] is True

    old_default = await store.get_model("trellis2")
    assert old_default is not None
    assert old_default["is_default"] is False

    new_default = await store.get_default_model()
    assert new_default is not None
    assert new_default["id"] == "hunyuan3d"


@pytest.mark.anyio
async def test_delete_model(store: ModelStore):
    assert await store.delete_model("hunyuan3d") is True
    assert await store.get_model("hunyuan3d") is None
    assert await store.delete_model("hunyuan3d") is False

    models = await store.list_models()
    assert len(models) == 1


@pytest.mark.anyio
async def test_get_enabled_models(store: ModelStore):
    enabled = await store.get_enabled_models()
    # Only trellis2 is enabled by default
    assert len(enabled) == 1
    assert enabled[0]["id"] == "trellis2"

    # Enable hunyuan3d
    await store.update_model("hunyuan3d", is_enabled=True)
    enabled = await store.get_enabled_models()
    assert len(enabled) == 2


@pytest.mark.anyio
async def test_create_duplicate_raises(store: ModelStore):
    with pytest.raises(ValueError, match="already exists"):
        await store.create_model(
            id="trellis2",
            provider_type="trellis2",
            display_name="Duplicate",
            model_path="dup/path",
        )
