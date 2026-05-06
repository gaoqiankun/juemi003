from __future__ import annotations

from typing import Iterable

from cubie.model.gpu_scheduler import GPUSlotScheduler
from cubie.model.registry import ModelRuntime
from cubie.model.registry.compat import normalize_name
from cubie.model.worker import ModelWorker


class QueriesMixin:
    def get_state(self, model_name: str) -> str:
        entry = self._entries.get(normalize_name(model_name))
        return entry.state if entry is not None else "not_loaded"

    def runtime_states(self) -> dict[str, str]:
        return {
            model_name: entry.state
            for model_name, entry in self._entries.items()
        }

    def get_error(self, model_name: str) -> Exception | None:
        entry = self._entries.get(normalize_name(model_name))
        if entry is None:
            return None
        return entry.error

    def has_ready_model(self) -> bool:
        return any(entry.state == "ready" for entry in self._entries.values())

    def ready_models(self) -> tuple[str, ...]:
        return tuple(
            model_name
            for model_name, entry in self._entries.items()
            if entry.state == "ready"
        )

    def iter_schedulers(self) -> Iterable[GPUSlotScheduler]:
        schedulers: list[GPUSlotScheduler] = []
        for entry in self._entries.values():
            if entry.state != "ready" or entry.worker is None:
                continue
            try:
                schedulers.append(entry.worker.runtime.scheduler)
            except Exception:
                continue
        return tuple(schedulers)

    def get_runtime(self, model_name: str) -> ModelRuntime:
        normalized = normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None or entry.state != "ready" or entry.worker is None:
            state = entry.state if entry is not None else "not_loaded"
            raise RuntimeError(f"model {normalized} is not ready (state={state})")
        return entry.worker.runtime

    def get_worker(self, model_name: str) -> ModelWorker | None:
        normalized = normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None or entry.state != "ready" or entry.worker is None:
            return None
        if not isinstance(entry.worker, ModelWorker):
            return None
        return entry.worker
