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

    async def count_pending_tasks_by_model(self) -> dict[str, int]:
        return dict(self.pending_counts)

    async def count_running_tasks_by_model(self) -> dict[str, int]:
        return dict(self.running_counts)


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
            vram_detection_enabled=False,
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
            vram_detection_enabled=False,
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
            vram_detection_enabled=False,
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
            vram_detection_enabled=True,
        )
        await scheduler.initialize()
        await scheduler.on_task_queued("trellis2")
        assert registry.load_calls == []

    asyncio.run(scenario())


def test_scheduler_vram_detection_failure_falls_back_to_one_slot() -> None:
    async def scenario() -> None:
        settings_store = FakeSettingsStore({MAX_LOADED_MODELS_KEY: 4})
        scheduler = ModelScheduler(
            model_registry=FakeRegistry(states={}),
            task_store=FakeTaskStore(),
            model_store=FakeModelStore(
                [
                    {"id": "trellis2", "vram_gb": 24.0},
                    {"id": "hunyuan3d", "vram_gb": 24.0},
                ]
            ),
            settings_store=settings_store,
            enabled=True,
            vram_detection_enabled=True,
        )
        scheduler._detect_total_vram_gb = lambda: None  # type: ignore[method-assign]
        await scheduler.initialize()
        assert scheduler.max_possible_loaded == 1
        assert scheduler.max_loaded_models == 1

    asyncio.run(scenario())


def test_scheduler_normalize_model_name_keeps_empty_string() -> None:
    assert _normalize_model_name("") == ""
