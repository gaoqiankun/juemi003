from __future__ import annotations

import asyncio
import math
import subprocess
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

    def load(self, model_name: str) -> None:
        ...

    async def unload(self, model_name: str) -> None:
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
        vram_detection_enabled: bool = True,
    ) -> None:
        self._model_registry = model_registry
        self._task_store = task_store
        self._model_store = model_store
        self._settings_store = settings_store
        self._enabled = bool(enabled)
        self._vram_detection_enabled = bool(vram_detection_enabled)
        self._max_possible_loaded = 1
        self._max_loaded_models = self.DEFAULT_MAX_LOADED_MODELS
        self._max_tasks_per_slot = self.DEFAULT_MAX_TASKS_PER_SLOT
        self._tasks_processed: dict[str, int] = {}
        self._quota_exceeded: set[str] = set()
        self._last_used_tick = 0
        self._last_used: dict[str, int] = {}
        self._lock = asyncio.Lock()
        self._logger = structlog.get_logger(__name__)

    @property
    def max_possible_loaded(self) -> int:
        return self._max_possible_loaded

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

    async def initialize(self) -> None:
        model_definitions = await self._model_store.list_models()
        known_model_vram = _extract_known_model_vram(model_definitions)
        total_vram_gb = (
            self._detect_total_vram_gb()
            if self._enabled and self._vram_detection_enabled
            else None
        )
        self._max_possible_loaded = _compute_max_possible_loaded(
            total_vram_gb=total_vram_gb,
            known_model_vram_gb=known_model_vram,
        )

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
            vram_detection_enabled=self._vram_detection_enabled,
            max_possible_loaded=self._max_possible_loaded,
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
        await self._enforce_loaded_slot_limit()

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
        if len(loaded_models) < self._max_loaded_models:
            self._model_registry.load(target_model)
            return

        candidate = await self._select_eviction_candidate(
            loaded_models=loaded_models,
            pending_counts=await self._task_store.count_pending_tasks_by_model(),
            running_counts=await self._task_store.count_running_tasks_by_model(),
            exclude_model=target_model,
        )
        if candidate is None:
            return
        await self._evict_and_load(candidate_model=candidate, target_model=target_model)

    async def _select_eviction_candidate(
        self,
        *,
        loaded_models: tuple[str, ...],
        pending_counts: dict[str, int],
        running_counts: dict[str, int],
        exclude_model: str,
    ) -> str | None:
        eligible: list[str] = []
        async with self._lock:
            for model_name in loaded_models:
                if model_name == exclude_model:
                    continue
                if self._model_registry.get_state(model_name) != "ready":
                    continue
                if running_counts.get(model_name, 0) > 0:
                    continue
                pending_count = pending_counts.get(model_name, 0)
                if model_name in self._quota_exceeded or pending_count == 0:
                    eligible.append(model_name)
            if not eligible:
                return None
            return min(
                eligible,
                key=lambda model_name: self._last_used.get(model_name, 0),
            )

    async def _evict_and_load(self, *, candidate_model: str, target_model: str) -> None:
        await self._model_registry.unload(candidate_model)
        async with self._lock:
            self._quota_exceeded.discard(candidate_model)
            self._tasks_processed.pop(candidate_model, None)
            self._last_used.pop(candidate_model, None)
        self._model_registry.load(target_model)

    async def _enforce_loaded_slot_limit(self) -> None:
        if not self._enabled:
            return
        while True:
            runtime_states = self._model_registry.runtime_states()
            loaded_models = tuple(
                model_name
                for model_name, state in runtime_states.items()
                if state in {"ready", "loading"}
            )
            if len(loaded_models) <= self._max_loaded_models:
                return
            candidate = await self._select_eviction_candidate(
                loaded_models=loaded_models,
                pending_counts=await self._task_store.count_pending_tasks_by_model(),
                running_counts=await self._task_store.count_running_tasks_by_model(),
                exclude_model="",
            )
            if candidate is None:
                return
            await self._model_registry.unload(candidate)
            async with self._lock:
                self._quota_exceeded.discard(candidate)
                self._tasks_processed.pop(candidate, None)
                self._last_used.pop(candidate, None)

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
        parsed = max(parsed, 1)
        return min(parsed, self._max_possible_loaded)

    def _normalize_max_tasks_per_slot(self, value: object) -> int:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            parsed = self.DEFAULT_MAX_TASKS_PER_SLOT
        return max(parsed, 1)

    def _touch_locked(self, model_name: str) -> None:
        self._last_used_tick += 1
        self._last_used[model_name] = self._last_used_tick

    def _detect_total_vram_gb(self) -> float | None:
        total_from_torch = _detect_total_vram_with_torch()
        if total_from_torch is not None:
            return total_from_torch
        total_from_nvidia_smi = _detect_total_vram_with_nvidia_smi()
        if total_from_nvidia_smi is not None:
            return total_from_nvidia_smi
        self._logger.warning("scheduler.vram_detection_failed")
        return None


def _normalize_model_name(model_name: str) -> str:
    return str(model_name).strip().lower()


def _extract_known_model_vram(model_definitions: list[dict]) -> tuple[float, ...]:
    values: list[float] = []
    for model in model_definitions:
        raw_value = model.get("vram_gb")
        if raw_value is None:
            continue
        try:
            parsed = float(raw_value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            values.append(parsed)
    return tuple(values)


def _compute_max_possible_loaded(
    *,
    total_vram_gb: float | None,
    known_model_vram_gb: tuple[float, ...],
) -> int:
    if total_vram_gb is None or total_vram_gb <= 0:
        return 1
    if not known_model_vram_gb:
        return 1
    largest_model = max(known_model_vram_gb)
    if largest_model <= 0:
        return 1
    return max(1, math.floor(total_vram_gb / largest_model))


def _parse_iso_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value))
    except Exception:
        return datetime.max.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _detect_total_vram_with_torch() -> float | None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return None
    try:
        if not torch.cuda.is_available():
            return None
        _, total_bytes = torch.cuda.mem_get_info()
        if total_bytes <= 0:
            return None
        return float(total_bytes) / (1024.0 ** 3)
    except Exception:
        return None


def _detect_total_vram_with_nvidia_smi() -> float | None:
    try:
        output = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2.0,
        )
    except Exception:
        return None

    values: list[float] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            values.append(float(line))
        except ValueError:
            continue
    if not values:
        return None
    return max(values) / 1024.0
