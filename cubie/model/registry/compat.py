from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable, Protocol

from cubie.model.worker import ModelWorker

if TYPE_CHECKING:
    from cubie.model.registry import ModelRuntime

ModelWorkerFactory = Callable[..., Any]


class _RegistryWorker(Protocol):
    async def load(self) -> None: ...

    async def unload(self) -> None: ...

    @property
    def runtime(self) -> "ModelRuntime": ...

    @property
    def weight_allocated(self) -> bool: ...


class _CompatRuntimeWorker:
    def __init__(self, runtime: "ModelRuntime") -> None:
        self._runtime = runtime
        self._loaded = False

    @property
    def runtime(self) -> "ModelRuntime":
        return self._runtime

    @property
    def weight_allocated(self) -> bool:
        return self._loaded

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


async def invoke_worker_factory(
    worker_factory: ModelWorkerFactory,
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
            maybe_worker = worker_factory(model_name, **kwargs)
            if inspect.isawaitable(maybe_worker):
                worker_obj = await maybe_worker
            else:
                worker_obj = maybe_worker
            return coerce_factory_result(worker_obj)
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


def normalize_name(model_name: str) -> str:
    return str(model_name).strip().lower()


def coerce_factory_result(worker_obj: Any) -> _RegistryWorker:
    from cubie.model.registry import ModelRuntime

    if isinstance(worker_obj, ModelWorker):
        return worker_obj
    if isinstance(worker_obj, ModelRuntime):
        return _CompatRuntimeWorker(worker_obj)
    raise TypeError(
        "worker_factory must return ModelWorker or ModelRuntime; "
        f"got {type(worker_obj).__name__}"
    )


def reset_entry(entry: _ModelEntry) -> None:
    entry.error = None
    entry.state = "not_loaded"
    entry.event = asyncio.Event()
    entry.load_task = None
    entry.requested_device_id = None
    entry.excluded_device_ids = ()
