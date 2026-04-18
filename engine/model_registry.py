from __future__ import annotations

import asyncio
import gc
import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Protocol

import structlog
from gen3d.engine.model_worker import ModelWorker
from gen3d.model.base import BaseModelProvider
from gen3d.stages.gpu.scheduler import GPUSlotScheduler
from gen3d.stages.gpu.worker import GPUWorkerHandle

_ORIGINAL_ASYNCIO_SLEEP = asyncio.sleep

ModelWorkerFactory = Callable[..., Any]
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


class _RegistryWorker(Protocol):
    async def load(self) -> None: ...

    async def unload(self) -> None: ...

    @property
    def runtime(self) -> ModelRuntime: ...


class _CompatRuntimeWorker:
    def __init__(self, runtime: ModelRuntime) -> None:
        self._runtime = runtime
        self._loaded = False

    @property
    def runtime(self) -> ModelRuntime:
        return self._runtime

    async def load(self) -> None:
        if self._loaded:
            return
        for worker in self._runtime.workers:
            await worker.start()
        self._loaded = True

    async def unload(self) -> None:
        if not self._loaded:
            scheduler_shutdown = getattr(self._runtime.scheduler, "shutdown", None)
            if callable(scheduler_shutdown):
                scheduler_shutdown()
            return
        scheduler_shutdown = getattr(self._runtime.scheduler, "shutdown", None)
        if callable(scheduler_shutdown):
            scheduler_shutdown()
        for worker in self._runtime.workers:
            await worker.stop()
        self._loaded = False


@dataclass(slots=True)
class _ModelEntry:
    state: str = "not_loaded"
    event: asyncio.Event = field(default_factory=asyncio.Event)
    worker: _RegistryWorker | None = None
    error: Exception | None = None
    load_task: asyncio.Task[None] | None = None
    requested_device_id: str | None = None
    excluded_device_ids: tuple[str, ...] = ()


class ModelRegistryLoadError(RuntimeError):
    pass


class ModelRegistry:
    _WAIT_READY_POLL_SECONDS = 0.1
    _WAIT_READY_TIMEOUT_SECONDS = 1800.0

    def __init__(
        self,
        worker_factory: ModelWorkerFactory,
        *,
        weight_measurement_enabled: bool = True,
    ) -> None:
        _ = weight_measurement_enabled
        self._worker_factory = worker_factory
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
        schedulers: list[GPUSlotScheduler] = []
        for entry in self._entries.values():
            if entry.state != "ready" or entry.worker is None:
                continue
            try:
                schedulers.append(entry.worker.runtime.scheduler)
            except Exception:
                continue
        return tuple(schedulers)

    def add_model_loaded_listener(self, listener: ModelLoadedListener) -> None:
        self._model_loaded_listeners.append(listener)

    def add_model_unloaded_listener(self, listener: ModelUnloadedListener) -> None:
        self._model_unloaded_listeners.append(listener)

    def add_weight_measured_listener(self, listener) -> None:
        # Deprecated: kept as no-op compatibility API.
        _ = listener

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
            self._load_worker(normalized, entry),
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
                    self._load_worker(normalized, entry),
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
                if entry is not None and entry.worker is not None:
                    return entry.worker.runtime
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
        if entry is None or entry.state != "ready" or entry.worker is None:
            state = entry.state if entry is not None else "not_loaded"
            raise RuntimeError(f"model {normalized} is not ready (state={state})")
        return entry.worker.runtime

    def get_worker(self, model_name: str) -> ModelWorker | None:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None or entry.state != "ready" or entry.worker is None:
            return None
        if not isinstance(entry.worker, ModelWorker):
            return None
        return entry.worker

    async def unload(self, model_name: str) -> None:
        normalized = self._normalize_name(model_name)
        entry = self._entries.get(normalized)
        if entry is None:
            return
        if entry.state == "unloading":
            return
        had_runtime_or_task = entry.worker is not None or entry.load_task is not None
        entry.state = "unloading"

        load_task = entry.load_task
        if load_task is not None and not load_task.done():
            load_task.cancel()
            await asyncio.gather(load_task, return_exceptions=True)

        worker = entry.worker
        if worker is not None:
            await worker.unload()
            entry.worker = None

        entry.error = None
        entry.state = "not_loaded"
        entry.event = asyncio.Event()
        entry.load_task = None
        entry.requested_device_id = None
        entry.excluded_device_ids = ()

        if worker is not None:
            del worker
            gc.collect()
            _maybe_empty_cuda_cache()

        self._logger.info(
            "model.unloaded",
            model_name=normalized,
        )
        if had_runtime_or_task:
            await self._notify_model_unloaded(normalized)

    async def _load_worker(self, model_name: str, entry: _ModelEntry) -> None:
        try:
            worker = await self._invoke_worker_factory(
                model_name,
                device_id=entry.requested_device_id,
                exclude_device_ids=entry.excluded_device_ids or None,
            )
            await worker.load()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            entry.worker = None
            entry.error = exc
            entry.state = "error"
            self._logger.warning(
                "model.load_failed",
                model_name=model_name,
                error=str(exc),
            )
            await self._notify_model_unloaded(model_name)
        else:
            entry.worker = worker
            entry.error = None
            entry.state = "ready"
            self._logger.info(
                "model.ready",
                model_name=model_name,
                worker_count=1,
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

    async def _invoke_worker_factory(
        self,
        model_name: str,
        *,
        device_id: str | None,
        exclude_device_ids: tuple[str, ...] | None,
    ) -> _RegistryWorker:
        kwargs: dict[str, str | tuple[str, ...]] = {}
        if device_id is not None:
            kwargs["device_id"] = device_id
        if exclude_device_ids:
            kwargs["exclude_device_ids"] = exclude_device_ids

        while True:
            try:
                maybe_worker = self._worker_factory(model_name, **kwargs)
                if inspect.isawaitable(maybe_worker):
                    worker_obj = await maybe_worker
                else:
                    worker_obj = maybe_worker
                if isinstance(worker_obj, ModelWorker):
                    return worker_obj
                if isinstance(worker_obj, ModelRuntime):
                    return _CompatRuntimeWorker(worker_obj)
                raise TypeError(
                    "worker_factory must return ModelWorker or ModelRuntime; "
                    f"got {type(worker_obj).__name__}"
                )
            except TypeError as exc:
                message = str(exc)
                if (
                    "unexpected keyword argument 'exclude_device_ids'" in message
                    and "exclude_device_ids" in kwargs
                ):
                    kwargs.pop("exclude_device_ids", None)
                    continue
                if (
                    "unexpected keyword argument 'device_id'" in message
                    and "device_id" in kwargs
                ):
                    kwargs.pop("device_id", None)
                    continue
                raise

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
