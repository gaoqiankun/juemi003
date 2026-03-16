from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import structlog

from gen3d.model.base import BaseModelProvider
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle

ModelRuntimeLoader = Callable[[str], "ModelRuntime | Awaitable[ModelRuntime]"]


@dataclass(slots=True)
class ModelRuntime:
    model_name: str
    provider: BaseModelProvider
    workers: list[GPUWorkerHandle]
    scheduler: GPUSlotScheduler


@dataclass(slots=True)
class _ModelEntry:
    state: str = "not_loaded"
    event: asyncio.Event = field(default_factory=asyncio.Event)
    runtime: ModelRuntime | None = None
    error: Exception | None = None
    load_task: asyncio.Task[None] | None = None


class ModelRegistryLoadError(RuntimeError):
    pass


class ModelRegistry:
    def __init__(self, runtime_loader: ModelRuntimeLoader) -> None:
        self._runtime_loader = runtime_loader
        self._entries: dict[str, _ModelEntry] = {}
        self._lock = asyncio.Lock()
        self._logger = structlog.get_logger(__name__)

    async def close(self) -> None:
        async with self._lock:
            entries = list(self._entries.values())
            for entry in entries:
                if entry.load_task is not None:
                    entry.load_task.cancel()
            load_tasks = [entry.load_task for entry in entries if entry.load_task is not None]
        if load_tasks:
            await asyncio.gather(*load_tasks, return_exceptions=True)

        for entry in entries:
            runtime = entry.runtime
            if runtime is None:
                continue
            for worker in runtime.workers:
                await worker.stop()
            entry.runtime = None
            entry.state = "not_loaded"
            entry.error = None
            entry.event = asyncio.Event()
            entry.load_task = None

    def get_state(self, model_name: str) -> str:
        entry = self._entries.get(self._normalize_name(model_name))
        return entry.state if entry is not None else "not_loaded"

    def has_ready_model(self) -> bool:
        return any(entry.state == "ready" for entry in self._entries.values())

    def ready_models(self) -> tuple[str, ...]:
        return tuple(
            model_name
            for model_name, entry in self._entries.items()
            if entry.state == "ready"
        )

    def load(self, model_name: str) -> None:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None:
            entry = _ModelEntry()
            self._entries[normalized] = entry

        if entry.state in {"loading", "ready", "error"}:
            return

        entry.state = "loading"
        entry.error = None
        entry.event = asyncio.Event()
        entry.load_task = asyncio.create_task(
            self._load_runtime(normalized, entry),
            name=f"model-load-{normalized}",
        )

    async def wait_ready(self, model_name: str) -> ModelRuntime:
        normalized = self._normalize_name(model_name)
        self.load(normalized)
        entry = self._entries[normalized]
        await entry.event.wait()
        if entry.state != "ready" or entry.runtime is None:
            message = f"model {normalized} failed to load"
            if entry.error is not None:
                message = f"{message}: {entry.error}"
            raise ModelRegistryLoadError(message)
        return entry.runtime

    def get_runtime(self, model_name: str) -> ModelRuntime:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None or entry.state != "ready" or entry.runtime is None:
            raise RuntimeError(f"model {normalized} is not ready")
        return entry.runtime

    async def _load_runtime(self, model_name: str, entry: _ModelEntry) -> None:
        try:
            if inspect.iscoroutinefunction(self._runtime_loader):
                runtime = await self._runtime_loader(model_name)
            else:
                maybe_runtime = await asyncio.to_thread(
                    self._runtime_loader,
                    model_name,
                )
                runtime = (
                    await maybe_runtime
                    if inspect.isawaitable(maybe_runtime)
                    else maybe_runtime
                )
            for worker in runtime.workers:
                await worker.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            entry.runtime = None
            entry.error = exc
            entry.state = "error"
            self._logger.warning(
                "model.load_failed",
                model_name=model_name,
                error=str(exc),
            )
        else:
            entry.runtime = runtime
            entry.error = None
            entry.state = "ready"
            self._logger.info(
                "model.ready",
                model_name=model_name,
                worker_count=len(runtime.workers),
            )
        finally:
            entry.event.set()

    @staticmethod
    def _normalize_name(model_name: str) -> str:
        normalized = str(model_name).strip().lower()
        return normalized or "trellis"
