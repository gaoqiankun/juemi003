from __future__ import annotations

import asyncio
import gc
import inspect
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable

import structlog
from gen3d.model.base import BaseModelProvider
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle

_ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep

ModelRuntimeLoader = Callable[..., "ModelRuntime | Awaitable[ModelRuntime]"]
ModelLoadedListener = Callable[[str], Awaitable[None] | None]
ModelUnloadedListener = Callable[[str], Awaitable[None] | None]


@dataclass(slots=True)
class ModelRuntime:
    model_name: str
    provider: BaseModelProvider
    workers: list[GPUWorkerHandle]
    scheduler: GPUSlotScheduler
    assigned_device_id: str | None = None
    weight_vram_mb: int | None = None


@dataclass(slots=True)
class _ModelEntry:
    state: str = "not_loaded"
    event: asyncio.Event = field(default_factory=asyncio.Event)
    runtime: ModelRuntime | None = None
    error: Exception | None = None
    load_task: asyncio.Task[None] | None = None
    requested_device_id: str | None = None
    excluded_device_ids: tuple[str, ...] = ()


class ModelRegistryLoadError(RuntimeError):
    pass


class ModelRegistry:
    _WAIT_READY_POLL_SECONDS = 0.1
    _WAIT_READY_TIMEOUT_SECONDS = 1800.0

    def __init__(self, runtime_loader: ModelRuntimeLoader) -> None:
        self._runtime_loader = runtime_loader
        self._entries: dict[str, _ModelEntry] = {}
        self._lock = asyncio.Lock()
        self._model_loaded_listeners: list[ModelLoadedListener] = []
        self._model_unloaded_listeners: list[ModelUnloadedListener] = []
        self._logger = structlog.get_logger(__name__)

    async def close(self) -> None:
        async with self._lock:
            model_names = list(self._entries.keys())
        for model_name in model_names:
            await self.unload(model_name)

    def get_state(self, model_name: str) -> str:
        entry = self._entries.get(self._normalize_name(model_name))
        return entry.state if entry is not None else "not_loaded"

    def runtime_states(self) -> dict[str, str]:
        return {
            model_name: entry.state
            for model_name, entry in self._entries.items()
        }

    def get_error(self, model_name: str) -> Exception | None:
        entry = self._entries.get(self._normalize_name(model_name))
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
        return tuple(
            entry.runtime.scheduler
            for entry in self._entries.values()
            if entry.state == "ready" and entry.runtime is not None
        )

    def add_model_loaded_listener(self, listener: ModelLoadedListener) -> None:
        self._model_loaded_listeners.append(listener)

    def add_model_unloaded_listener(self, listener: ModelUnloadedListener) -> None:
        self._model_unloaded_listeners.append(listener)

    def load(self, model_name: str, *, device_id: str | None = None) -> None:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None:
            entry = _ModelEntry()
            self._entries[normalized] = entry

        if entry.state in {"loading", "ready"}:
            return

        entry.state = "loading"
        entry.error = None
        entry.event = asyncio.Event()
        entry.requested_device_id = (
            str(device_id).strip() if device_id is not None and str(device_id).strip() else None
        )
        entry.excluded_device_ids = ()
        entry.load_task = asyncio.create_task(
            self._load_runtime(normalized, entry),
            name=f"model-load-{normalized}",
        )

    async def reload(
        self,
        model_name: str,
        *,
        exclude_device_ids: Iterable[str] | None = None,
    ) -> ModelRuntime:
        normalized = self._normalize_name(model_name)
        normalized_excluded_device_ids = tuple(
            normalized_device
            for raw_device_id in (exclude_device_ids or ())
            if (normalized_device := str(raw_device_id).strip())
        )
        async with self._lock:
            entry = self._entries.get(normalized)
            if entry is not None and entry.state == "loading" and entry.excluded_device_ids:
                pass
            else:
                await self.unload(normalized)
                entry = _ModelEntry(
                    state="loading",
                    event=asyncio.Event(),
                    excluded_device_ids=normalized_excluded_device_ids,
                )
                self._entries[normalized] = entry
                entry.load_task = asyncio.create_task(
                    self._load_runtime(normalized, entry),
                    name=f"model-reload-{normalized}",
                )
        return await self.wait_ready(normalized)

    async def wait_ready(
        self,
        model_name: str,
        timeout_seconds: float = _WAIT_READY_TIMEOUT_SECONDS,
    ) -> ModelRuntime:
        normalized = self._normalize_name(model_name)
        poll_interval = self._WAIT_READY_POLL_SECONDS
        timeout = max(float(timeout_seconds), 0.0)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout

        while True:
            entry = self._entries.get(normalized)
            state = "not_loaded" if entry is None else entry.state

            if state == "ready":
                if entry is not None and entry.runtime is not None:
                    return entry.runtime
                raise ModelRegistryLoadError(f"model {normalized} failed to load")

            if state == "error":
                message = f"model {normalized} failed to load"
                if entry is not None and entry.error is not None:
                    message = f"{message}: {entry.error}"
                raise ModelRegistryLoadError(message)

            remaining = deadline - loop.time()
            if remaining <= 0:
                if state == "not_loaded":
                    raise ModelRegistryLoadError(
                        f"model {normalized} still not loaded after timeout"
                    )
                raise ModelRegistryLoadError(
                    f"model {normalized} did not become ready before timeout"
                )

            await _ORIGINAL_ASYNCIO_SLEEP(min(poll_interval, remaining))

    def get_runtime(self, model_name: str) -> ModelRuntime:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None or entry.state != "ready" or entry.runtime is None:
            raise RuntimeError(f"model {normalized} is not ready")
        return entry.runtime

    async def unload(self, model_name: str) -> None:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None:
            return
        had_runtime_or_task = entry.runtime is not None or entry.load_task is not None

        load_task = entry.load_task
        if load_task is not None and not load_task.done():
            load_task.cancel()
            await asyncio.gather(load_task, return_exceptions=True)

        runtime = entry.runtime
        if runtime is not None:
            for worker in runtime.workers:
                await worker.stop()
            entry.runtime = None

        entry.error = None
        entry.state = "not_loaded"
        entry.event = asyncio.Event()
        entry.load_task = None
        entry.requested_device_id = None
        entry.excluded_device_ids = ()

        if runtime is not None:
            del runtime
            gc.collect()
            _maybe_empty_cuda_cache()

        self._logger.info(
            "model.unloaded",
            model_name=normalized,
        )
        if had_runtime_or_task:
            await self._notify_model_unloaded(normalized)

    async def _load_runtime(self, model_name: str, entry: _ModelEntry) -> None:
        try:
            runtime = await self._invoke_runtime_loader(
                model_name,
                device_id=entry.requested_device_id,
                exclude_device_ids=entry.excluded_device_ids or None,
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
            await self._notify_model_unloaded(model_name)
        else:
            entry.runtime = runtime
            entry.error = None
            entry.state = "ready"
            self._logger.info(
                "model.ready",
                model_name=model_name,
                worker_count=len(runtime.workers),
            )
            await self._notify_model_loaded(model_name)
        finally:
            entry.load_task = None
            entry.event.set()

    async def _notify_model_loaded(self, model_name: str) -> None:
        for listener in self._model_loaded_listeners:
            try:
                maybe_awaitable = listener(model_name)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception as exc:
                self._logger.warning(
                    "model.loaded_listener_failed",
                    model_name=model_name,
                    error=str(exc),
                )

    async def _notify_model_unloaded(self, model_name: str) -> None:
        for listener in self._model_unloaded_listeners:
            try:
                maybe_awaitable = listener(model_name)
                if inspect.isawaitable(maybe_awaitable):
                    await maybe_awaitable
            except Exception as exc:
                self._logger.warning(
                    "model.unloaded_listener_failed",
                    model_name=model_name,
                    error=str(exc),
                )

    async def _invoke_runtime_loader(
        self,
        model_name: str,
        *,
        device_id: str | None,
        exclude_device_ids: tuple[str, ...] | None,
    ) -> ModelRuntime:
        if inspect.iscoroutinefunction(self._runtime_loader):
            runtime = await self._call_runtime_loader(
                self._runtime_loader,
                model_name,
                device_id=device_id,
                exclude_device_ids=exclude_device_ids,
            )
            return runtime
        maybe_runtime = await asyncio.to_thread(
            self._call_runtime_loader,
            self._runtime_loader,
            model_name,
            device_id,
            exclude_device_ids,
        )
        if inspect.isawaitable(maybe_runtime):
            return await maybe_runtime
        return maybe_runtime

    @staticmethod
    def _call_runtime_loader(
        runtime_loader: ModelRuntimeLoader,
        model_name: str,
        device_id: str | None,
        exclude_device_ids: tuple[str, ...] | None,
    ) -> ModelRuntime | Awaitable[ModelRuntime]:
        kwargs: dict[str, str | tuple[str, ...]] = {}
        if device_id is not None:
            kwargs["device_id"] = device_id
        if exclude_device_ids:
            kwargs["exclude_device_ids"] = exclude_device_ids

        if not kwargs:
            return runtime_loader(model_name)

        while True:
            try:
                return runtime_loader(model_name, **kwargs)
            except TypeError as exc:
                message = str(exc)
                if (
                    "unexpected keyword argument 'exclude_device_ids'" in message
                    and "exclude_device_ids" in kwargs
                ):
                    kwargs.pop("exclude_device_ids", None)
                elif (
                    "unexpected keyword argument 'device_id'" in message
                    and "device_id" in kwargs
                ):
                    kwargs.pop("device_id", None)
                else:
                    raise
                if not kwargs:
                    return runtime_loader(model_name)

    @staticmethod
    def _normalize_name(model_name: str) -> str:
        return str(model_name).strip().lower()


def _maybe_empty_cuda_cache() -> None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return
