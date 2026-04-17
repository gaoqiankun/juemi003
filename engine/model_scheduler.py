from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Protocol

import structlog
from gen3d.storage.settings_store import (
    MAX_LOADED_MODELS_KEY,
    MAX_TASKS_PER_SLOT_KEY,
)


class _RegistryProtocol(Protocol):
    def get_state(self, model_name: str) -> str:
        ...

    def runtime_states(self) -> dict[str, str]:
        ...

    def load(self, model_name: str, *, device_id: str | None = None) -> None:
        ...


class _TaskStoreProtocol(Protocol):
    async def count_pending_tasks_by_model(self) -> dict[str, int]:
        ...

    async def count_running_tasks_by_model(self) -> dict[str, int]:
        ...

    async def get_oldest_queued_task_time_by_model(self) -> dict[str, str]:
        ...


class _ModelStoreProtocol(Protocol):
    async def list_models(self) -> list[dict]:
        ...


class _SettingsStoreProtocol(Protocol):
    async def get(self, key: str):
        ...

    async def set_many(self, settings: dict):
        ...


class ModelScheduler:
    DEFAULT_MAX_LOADED_MODELS = 1
    DEFAULT_MAX_TASKS_PER_SLOT = 8

    def __init__(
        self,
        *,
        model_registry: _RegistryProtocol,
        task_store: _TaskStoreProtocol,
        model_store: _ModelStoreProtocol,
        settings_store: _SettingsStoreProtocol,
        enabled: bool,
        gpu_device_count: int = 1,
    ) -> None:
        self._model_registry = model_registry
        self._task_store = task_store
        self._model_store = model_store
        self._settings_store = settings_store
        self._enabled = bool(enabled)
        self._gpu_device_count = max(1, int(gpu_device_count))
        self._max_loaded_models = self.DEFAULT_MAX_LOADED_MODELS
        self._max_tasks_per_slot = self.DEFAULT_MAX_TASKS_PER_SLOT
        self._tasks_processed: dict[str, int] = {}
        self._quota_exceeded: set[str] = set()
        self._last_used_tick = 0
        self._last_used: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._logger = structlog.get_logger(__name__)

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def max_loaded_models(self) -> int:
        return self._max_loaded_models

    @property
    def max_tasks_per_slot(self) -> int:
        return self._max_tasks_per_slot

    def get_tasks_processed(self, model_id: str) -> int:
        normalized = _normalize_model_name(model_id)
        return int(self._tasks_processed.get(normalized, 0))

    def get_last_used_tick(self, model_name: str) -> int:
        normalized = _normalize_model_name(model_name)
        return int(self._last_used.get(normalized, 0))

    async def initialize(self) -> None:
        configured_max_loaded_models = await self._settings_store.get(MAX_LOADED_MODELS_KEY)
        configured_max_tasks_per_slot = await self._settings_store.get(MAX_TASKS_PER_SLOT_KEY)
        self._max_loaded_models = self._normalize_max_loaded_models(configured_max_loaded_models)
        self._max_tasks_per_slot = self._normalize_max_tasks_per_slot(configured_max_tasks_per_slot)

        updates: dict[str, int] = {}
        if configured_max_loaded_models != self._max_loaded_models:
            updates[MAX_LOADED_MODELS_KEY] = self._max_loaded_models
        if configured_max_tasks_per_slot != self._max_tasks_per_slot:
            updates[MAX_TASKS_PER_SLOT_KEY] = self._max_tasks_per_slot
        if updates:
            await self._settings_store.set_many(updates)

        self._logger.info(
            "scheduler.initialized",
            enabled=self._enabled,
            max_loaded_models=self._max_loaded_models,
            max_tasks_per_slot=self._max_tasks_per_slot,
        )
        await self._startup_scan_queued_models()

    async def request_load(self, model_id: str) -> None:
        if not self._enabled:
            return
        try:
            await self._load_or_queue(_normalize_model_name(model_id))
        except Exception as exc:
            self._logger.warning(
                "scheduler.request_load_failed",
                model_id=model_id,
                error=str(exc),
            )

    async def on_task_queued(self, model_id: str) -> None:
        if not self._enabled:
            return
        try:
            await self._load_or_queue(_normalize_model_name(model_id))
        except Exception as exc:
            self._logger.warning(
                "scheduler.on_task_queued_failed",
                model_id=model_id,
                error=str(exc),
            )

    async def on_task_completed(self, model_id: str) -> None:
        if not self._enabled:
            return
        normalized_model = _normalize_model_name(model_id)
        pending_counts = await self._task_store.count_pending_tasks_by_model()
        has_other_pending = any(
            model_name != normalized_model and count > 0
            for model_name, count in pending_counts.items()
        )
        async with self._lock:
            self._tasks_processed[normalized_model] = self._tasks_processed.get(normalized_model, 0) + 1
            self._touch_locked(normalized_model)
            processed = self._tasks_processed[normalized_model]
            if processed >= self._max_tasks_per_slot and has_other_pending:
                self._quota_exceeded.add(normalized_model)

    async def on_model_loaded(self, model_id: str) -> None:
        if not self._enabled:
            return
        normalized_model = _normalize_model_name(model_id)
        async with self._lock:
            self._tasks_processed[normalized_model] = 0
            self._quota_exceeded.discard(normalized_model)
            self._touch_locked(normalized_model)
        await self._startup_scan_queued_models()

    async def update_limits(
        self,
        *,
        max_loaded_models: int | None = None,
        max_tasks_per_slot: int | None = None,
    ) -> None:
        if max_loaded_models is None and max_tasks_per_slot is None:
            return
        async with self._lock:
            if max_loaded_models is not None:
                self._max_loaded_models = self._normalize_max_loaded_models(max_loaded_models)
            if max_tasks_per_slot is not None:
                self._max_tasks_per_slot = self._normalize_max_tasks_per_slot(max_tasks_per_slot)
                for model_name in tuple(self._quota_exceeded):
                    if self._tasks_processed.get(model_name, 0) < self._max_tasks_per_slot:
                        self._quota_exceeded.discard(model_name)

    async def _load_or_queue(self, target_model: str) -> None:
        if not target_model:
            return
        state = self._model_registry.get_state(target_model)
        if state in {"ready", "loading"}:
            if state == "ready":
                async with self._lock:
                    self._touch_locked(target_model)
            return

        runtime_states = self._model_registry.runtime_states()
        loaded_models = tuple(
            model_name
            for model_name, runtime_state in runtime_states.items()
            if runtime_state in {"ready", "loading"}
        )
        if len(loaded_models) >= self._max_loaded_models:
            return

        self._model_registry.load(target_model)

    async def _startup_scan_queued_models(self) -> None:
        if not self._enabled:
            return
        oldest_task_time_by_model = await self._task_store.get_oldest_queued_task_time_by_model()
        if not oldest_task_time_by_model:
            return
        sorted_models = sorted(
            oldest_task_time_by_model.items(),
            key=lambda item: (_parse_iso_datetime(item[1]), item[0]),
        )
        for model_id, _ in sorted_models:
            await self._load_or_queue(model_id)

    def _normalize_max_loaded_models(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = self.DEFAULT_MAX_LOADED_MODELS
        return max(parsed, 1)

    def _normalize_max_tasks_per_slot(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = self.DEFAULT_MAX_TASKS_PER_SLOT
        return max(parsed, 1)

    def _touch_locked(self, model_name: str) -> None:
        self._last_used_tick += 1
        self._last_used[model_name] = self._last_used_tick


def _normalize_model_name(model_name: str) -> str:
    return str(model_name).strip().lower()


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return datetime.max.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
