from __future__ import annotations

import asyncio
import sys
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.engine.model_scheduler import ModelScheduler, _normalize_model_name
from gen3d.storage.settings_store import (
    MAX_LOADED_MODELS_KEY,
    MAX_TASKS_PER_SLOT_KEY,
)


class FakeRegistry:
    def __init__(self, *, states: dict[str, str]) -> None:
        self._states = {str(key).strip().lower(): value for key, value in states.items()}
        self.load_calls: list[str] = []
        self.unload_calls: list[str] = []

    def get_state(self, model_name: str) -> str:
        return self._states.get(str(model_name).strip().lower(), "not_loaded")

    def runtime_states(self) -> dict[str, str]:
        return dict(self._states)

    def load(self, model_name: str) -> None:
        normalized = str(model_name).strip().lower()
        self.load_calls.append(normalized)
        self._states[normalized] = "loading"

    async def unload(self, model_name: str) -> None:
        normalized = str(model_name).strip().lower()
        self.unload_calls.append(normalized)
        self._states[normalized] = "not_loaded"


class FakeTaskStore:
    def __init__(self) -> None:
        self.pending_counts: dict[str, int] = {}
        self.running_counts: dict[str, int] = {}
        self.oldest_queued_task_time_by_model: dict[str, str] = {}

    async def count_pending_tasks_by_model(self) -> dict[str, int]:
        return dict(self.pending_counts)

    async def count_running_tasks_by_model(self) -> dict[str, int]:
        return dict(self.running_counts)

    async def get_oldest_queued_task_time_by_model(self) -> dict[str, str]:
        return dict(self.oldest_queued_task_time_by_model)


class FakeModelStore:
    def __init__(self, models: list[dict]) -> None:
        self._models = models

    async def list_models(self) -> list[dict]:
        return list(self._models)


class FakeSettingsStore:
    def __init__(self, values: dict[str, object] | None = None) -> None:
        self._values = dict(values or {})

    async def get(self, key: str):
        return self._values.get(key)

    async def set_many(self, settings: dict) -> None:
        self._values.update(settings)


def test_scheduler_auto_load_on_task_queued() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "not_loaded"})
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=FakeTaskStore(),
            model_store=FakeModelStore([{"id": "trellis2", "vram_gb": 24.0}]),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 1,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()
        await scheduler.on_task_queued("trellis2")
        assert registry.load_calls == ["trellis2"]

    asyncio.run(scenario())


def test_scheduler_eviction_lru() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "ready", "hunyuan3d": "not_loaded"})
        task_store = FakeTaskStore()
        task_store.pending_counts = {"hunyuan3d": 1}
        task_store.running_counts = {"trellis2": 0}

        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore(
                [
                    {"id": "trellis2", "vram_gb": 24.0},
                    {"id": "hunyuan3d", "vram_gb": 24.0},
                ]
            ),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 1,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()
        await scheduler.on_model_loaded("trellis2")
        await scheduler.on_task_queued("hunyuan3d")

        assert registry.unload_calls == ["trellis2"]
        assert registry.load_calls == ["hunyuan3d"]

    asyncio.run(scenario())


def test_scheduler_quota_prevents_starvation() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "ready", "hunyuan3d": "ready", "step1x3d": "not_loaded"})
        task_store = FakeTaskStore()
        task_store.pending_counts = {"step1x3d": 2}
        task_store.running_counts = {"trellis2": 0, "hunyuan3d": 0}

        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore(
                [
                    {"id": "trellis2", "vram_gb": 24.0},
                    {"id": "hunyuan3d", "vram_gb": 24.0},
                    {"id": "step1x3d", "vram_gb": 27.0},
                ]
            ),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 2,
                    MAX_TASKS_PER_SLOT_KEY: 2,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()
        await scheduler.on_model_loaded("trellis2")
        await scheduler.on_model_loaded("hunyuan3d")
        await scheduler.on_task_completed("trellis2")
        await scheduler.on_task_completed("trellis2")

        task_store.pending_counts = {"hunyuan3d": 1, "step1x3d": 1}
        await scheduler.on_task_queued("step1x3d")

        assert registry.unload_calls == ["trellis2"]
        assert registry.load_calls == ["step1x3d"]

    asyncio.run(scenario())


def test_scheduler_on_task_queued_is_noop_when_disabled() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "not_loaded"})
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=FakeTaskStore(),
            model_store=FakeModelStore([{"id": "trellis2", "vram_gb": 24.0}]),
            settings_store=FakeSettingsStore(),
            enabled=False,
        )
        await scheduler.initialize()
        await scheduler.on_task_queued("trellis2")
        assert registry.load_calls == []

    asyncio.run(scenario())



def test_scheduler_normalize_model_name_keeps_empty_string() -> None:
    assert _normalize_model_name("") == ""


def test_scheduler_startup_scan_loads_model_with_oldest_task() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.oldest_queued_task_time_by_model = {
            "hunyuan3d": "2026-03-23T10:00:00+00:00",
            "trellis2": "2026-03-23T09:00:00+00:00",
        }
        registry = FakeRegistry(states={"trellis2": "not_loaded", "hunyuan3d": "not_loaded"})
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore(
                [
                    {"id": "trellis2", "vram_gb": 24.0},
                    {"id": "hunyuan3d", "vram_gb": 24.0},
                ]
            ),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 2,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()
        assert registry.load_calls == ["trellis2", "hunyuan3d"]

    asyncio.run(scenario())


def test_scheduler_startup_scan_respects_slot_limit() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.oldest_queued_task_time_by_model = {
            "hunyuan3d": "2026-03-23T10:00:00+00:00",
            "trellis2": "2026-03-23T09:00:00+00:00",
        }
        registry = FakeRegistry(states={"trellis2": "not_loaded", "hunyuan3d": "not_loaded"})
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore(
                [
                    {"id": "trellis2", "vram_gb": 24.0},
                    {"id": "hunyuan3d", "vram_gb": 24.0},
                ]
            ),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 1,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()
        assert registry.load_calls == ["trellis2"]
        assert registry.unload_calls == []

    asyncio.run(scenario())


def test_scheduler_startup_scan_skips_when_disabled() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.oldest_queued_task_time_by_model = {
            "hunyuan3d": "2026-03-23T10:00:00+00:00",
        }
        registry = FakeRegistry(states={"hunyuan3d": "not_loaded"})
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore([{"id": "hunyuan3d", "vram_gb": 24.0}]),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 1,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=False,
        )
        await scheduler.initialize()
        assert registry.load_calls == []

    asyncio.run(scenario())


def test_scheduler_on_model_loaded_rescans_and_loads_pending_model() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.pending_counts = {"modelb": 1}
        task_store.running_counts = {"modela": 0}
        task_store.oldest_queued_task_time_by_model = {
            "modelb": "2026-03-23T10:00:00+00:00",
        }
        registry = FakeRegistry(states={"modela": "loading", "modelb": "not_loaded"})
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore(
                [
                    {"id": "modela", "vram_gb": 24.0},
                    {"id": "modelb", "vram_gb": 24.0},
                ]
            ),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 1,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()
        assert registry.load_calls == []
        assert registry.unload_calls == []

        await scheduler.on_task_queued("modelb")
        assert registry.load_calls == []
        assert registry.unload_calls == []

        registry._states["modela"] = "ready"
        await scheduler.on_model_loaded("modela")

        assert registry.unload_calls == ["modela"]
        assert registry.load_calls == ["modelb"]

    asyncio.run(scenario())


def test_scheduler_on_model_loaded_scan_does_not_evict_just_loaded_model() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.pending_counts = {"modela": 0, "modelb": 1, "modelc": 0}
        task_store.running_counts = {"modela": 0, "modelc": 0}
        registry = FakeRegistry(
            states={
                "modela": "ready",
                "modelb": "not_loaded",
                "modelc": "ready",
            }
        )
        scheduler = ModelScheduler(
            model_registry=registry,
            task_store=task_store,
            model_store=FakeModelStore(
                [
                    {"id": "modela", "vram_gb": 24.0},
                    {"id": "modelb", "vram_gb": 24.0},
                    {"id": "modelc", "vram_gb": 24.0},
                ]
            ),
            settings_store=FakeSettingsStore(
                {
                    MAX_LOADED_MODELS_KEY: 2,
                    MAX_TASKS_PER_SLOT_KEY: 8,
                }
            ),
            enabled=True,
        )
        await scheduler.initialize()

        # Initialize LRU so modelc is older than modela.
        await scheduler.on_model_loaded("modelc")
        task_store.oldest_queued_task_time_by_model = {
            "modelb": "2026-03-23T10:00:00+00:00",
        }

        await scheduler.on_model_loaded("modela")

        assert registry.load_calls == ["modelb"]
        assert registry.unload_calls == ["modelc"]
        assert "modela" not in registry.unload_calls

    asyncio.run(scenario())
