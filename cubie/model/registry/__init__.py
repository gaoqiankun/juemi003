from __future__ import annotations

import asyncio

import structlog

from cubie.model.types import (
    ModelRegistryLoadError,
    ModelRuntime,
    _ModelEntry,
    normalize_name,
    reset_entry,
)

from .compat import ModelWorkerFactory, coerce_factory_result
from .lifecycle import LifecycleMixin
from .listeners import (
    ListenersMixin,
    ModelLoadedListener,
    ModelUnloadedListener,
)
from .queries import QueriesMixin


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
