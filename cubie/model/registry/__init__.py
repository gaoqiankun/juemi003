from __future__ import annotations

import asyncio
from dataclasses import dataclass

import structlog

from cubie.model.base import BaseModelProvider
from cubie.model.gpu_scheduler import GPUSlotScheduler, GPUWorkerHandle


@dataclass(slots=True)
class ModelRuntime:
    model_name: str
    provider: BaseModelProvider
    workers: list[GPUWorkerHandle]
    scheduler: GPUSlotScheduler
    assigned_device_id: str | None = None
    weight_vram_mb: int | None = None


class ModelRegistryLoadError(RuntimeError):
    pass


def maybe_empty_cuda_cache() -> None:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return
    try:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        return


# Public types above are imported by submodules during package initialization.
from cubie.model.registry.compat import (  # noqa: E402
    ModelWorkerFactory,
    _ModelEntry,
    coerce_factory_result,
    normalize_name,
    reset_entry,
)
from cubie.model.registry.lifecycle import LifecycleMixin  # noqa: E402
from cubie.model.registry.listeners import (  # noqa: E402
    ListenersMixin,
    ModelLoadedListener,
    ModelUnloadedListener,
)
from cubie.model.registry.queries import QueriesMixin  # noqa: E402

__all__ = (
    "ModelRegistry",
    "ModelRegistryLoadError",
    "ModelRuntime",
    "maybe_empty_cuda_cache",
)


class ModelRegistry(LifecycleMixin, QueriesMixin, ListenersMixin):
    _WAIT_READY_POLL_SECONDS = 0.1
    _WAIT_READY_TIMEOUT_SECONDS = 1800.0

    normalize_name = staticmethod(normalize_name)
    coerce_factory_result = staticmethod(coerce_factory_result)
    reset_entry = staticmethod(reset_entry)

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
