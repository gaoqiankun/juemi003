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


def _build_scheduler(
    *,
    registry: FakeRegistry,
    task_store: FakeTaskStore,
    max_loaded_models: int,
    max_tasks_per_slot: int,
    enabled: bool = True,
) -> ModelScheduler:
    return ModelScheduler(
        model_registry=registry,
        task_store=task_store,
        model_store=FakeModelStore([]),
        settings_store=FakeSettingsStore(
            {
                MAX_LOADED_MODELS_KEY: max_loaded_models,
                MAX_TASKS_PER_SLOT_KEY: max_tasks_per_slot,
            }
        ),
        enabled=enabled,
    )


def test_scheduler_auto_load_on_task_queued() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "not_loaded"})
        scheduler = _build_scheduler(
            registry=registry,
            task_store=FakeTaskStore(),
            max_loaded_models=1,
            max_tasks_per_slot=8,
        )
        await scheduler.initialize()
        await scheduler.on_task_queued("trellis2")
        assert registry.load_calls == ["trellis2"]

    asyncio.run(scenario())


def test_scheduler_does_not_evict_when_slots_are_full() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"model-a": "ready", "model-b": "not_loaded"})
        task_store = FakeTaskStore()
        task_store.pending_counts = {"model-b": 1}
        scheduler = _build_scheduler(
            registry=registry,
            task_store=task_store,
            max_loaded_models=1,
            max_tasks_per_slot=8,
        )
        await scheduler.initialize()
        await scheduler.on_task_queued("model-b")

        assert registry.load_calls == []
        assert registry.unload_calls == []

    asyncio.run(scenario())


def test_scheduler_on_task_completed_updates_quota_state() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "ready"})
        task_store = FakeTaskStore()
        task_store.pending_counts = {"hunyuan3d": 1}
        scheduler = _build_scheduler(
            registry=registry,
            task_store=task_store,
            max_loaded_models=1,
            max_tasks_per_slot=2,
        )
        await scheduler.initialize()
        await scheduler.on_model_loaded("trellis2")
        await scheduler.on_task_completed("trellis2")
        await scheduler.on_task_completed("trellis2")

        assert scheduler.get_tasks_processed("trellis2") == 2

    asyncio.run(scenario())


def test_scheduler_startup_scan_respects_slot_limit() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.oldest_queued_task_time_by_model = {
            "hunyuan3d": "2026-03-23T10:00:00+00:00",
            "trellis2": "2026-03-23T09:00:00+00:00",
        }
        registry = FakeRegistry(states={"trellis2": "not_loaded", "hunyuan3d": "not_loaded"})
        scheduler = _build_scheduler(
            registry=registry,
            task_store=task_store,
            max_loaded_models=1,
            max_tasks_per_slot=8,
        )
        await scheduler.initialize()

        assert registry.load_calls == ["trellis2"]

    asyncio.run(scenario())


def test_scheduler_on_model_loaded_triggers_rescan_only_when_capacity_allows() -> None:
    async def scenario() -> None:
        task_store = FakeTaskStore()
        task_store.oldest_queued_task_time_by_model = {"modelb": "2026-03-23T10:00:00+00:00"}

        registry = FakeRegistry(states={"modela": "loading", "modelb": "not_loaded"})
        scheduler = _build_scheduler(
            registry=registry,
            task_store=task_store,
            max_loaded_models=1,
            max_tasks_per_slot=8,
        )
        await scheduler.initialize()
        assert registry.load_calls == []

        # Still full after modela transitions to ready.
        registry._states["modela"] = "ready"
        await scheduler.on_model_loaded("modela")
        assert registry.load_calls == []

        # Free the slot and notify again.
        registry._states["modela"] = "not_loaded"
        await scheduler.on_model_loaded("modela")
        assert registry.load_calls == ["modelb"]

    asyncio.run(scenario())


def test_scheduler_on_task_queued_is_noop_when_disabled() -> None:
    async def scenario() -> None:
        registry = FakeRegistry(states={"trellis2": "not_loaded"})
        scheduler = _build_scheduler(
            registry=registry,
            task_store=FakeTaskStore(),
            max_loaded_models=1,
            max_tasks_per_slot=8,
            enabled=False,
        )
        await scheduler.initialize()
        await scheduler.on_task_queued("trellis2")
        assert registry.load_calls == []

    asyncio.run(scenario())


def test_scheduler_normalize_model_name_keeps_empty_string() -> None:
    assert _normalize_model_name("") == ""
