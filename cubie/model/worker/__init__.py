from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Protocol, cast

import structlog

from cubie.model.base import GenerationResult, StageProgress
from cubie.model.gpu_scheduler import GPUSlotScheduler, GPUWorkerHandle
from cubie.vram.allocator import VRAMAllocator, WeightAllocation


class _ModelStoreProtocol(Protocol):
    async def get_model(self, model_id: str) -> dict[str, Any] | None: ...

    async def update_model(self, model_id: str, **updates: object) -> dict[str, Any] | None: ...


class _ModelRuntimeProtocol(Protocol):
    model_name: str
    provider: Any
    workers: list[GPUWorkerHandle]
    scheduler: GPUSlotScheduler
    assigned_device_id: str | None
    weight_vram_mb: int | None


GPUWorkerFactory = Callable[..., _ModelRuntimeProtocol | Awaitable[_ModelRuntimeProtocol]]


def normalize_model_name(model_id: str) -> str:
    return str(model_id).strip().lower()


def normalize_optional_vram_mb(value: object) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if normalized < 0:
        return None
    return normalized


def resolve_total_vram_mb(model_definition: dict[str, Any]) -> int | None:
    raw_vram_gb = model_definition.get("vram_gb")
    if raw_vram_gb is not None:
        try:
            parsed = float(raw_vram_gb)
        except (TypeError, ValueError):
            parsed = 0.0
        if parsed > 0:
            return int(round(parsed * 1024.0))
    min_vram = normalize_optional_vram_mb(model_definition.get("min_vram_mb"))
    return min_vram


def looks_like_worker_crash(error: BaseException) -> bool:
    message = str(error).lower()
    return "exited unexpectedly" in message or "worker process" in message and "exit" in message


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


class _ModelWorkerSchedulerAdapter:
    def __init__(self, owner: "ModelWorker") -> None:
        self._owner = owner

    @property
    def worker_id(self) -> str:
        return self._owner.worker_id

    @property
    def device_id(self) -> str:
        return self._owner.device_id or ""

    @property
    def startup_weight_mb(self) -> int | None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb=None,
    ) -> list[GenerationResult]:
        callback = cast(Callable[[StageProgress], Awaitable[None] | None] | None, progress_cb)
        return await self._owner.run_batch(
            batch=prepared_inputs,
            options=options,
            progress_cb=callback,
        )


# Public types above are imported by submodules during package initialization.
from cubie.model.worker.inference import InferenceMixin  # noqa: E402
from cubie.model.worker.lifecycle import LifecycleMixin  # noqa: E402
from cubie.model.worker.vram_estimate import VRAMEstimateMixin  # noqa: E402

__all__ = (
    "GPUWorkerFactory",
    "ModelWorker",
    "looks_like_worker_crash",
    "maybe_empty_cuda_cache",
    "normalize_model_name",
    "normalize_optional_vram_mb",
    "resolve_total_vram_mb",
)


class ModelWorker(LifecycleMixin, InferenceMixin, VRAMEstimateMixin):
    _EVICT_POLL_SECONDS = 0.05
    _INFERENCE_EMA_OLD_WEIGHT = 0.7
    _INFERENCE_EMA_NEW_WEIGHT = 0.3

    def __init__(
        self,
        model_id: str,
        allocator: VRAMAllocator,
        gpu_worker_factory: GPUWorkerFactory,
        db_store: _ModelStoreProtocol,
    ) -> None:
        self.model_id = normalize_model_name(model_id)
        self._allocator = allocator
        self._gpu_worker_factory = gpu_worker_factory
        self._db_store = db_store
        self._logger = structlog.get_logger(__name__)
        self._weight_allocated = False
        self._inference_busy_holds = 0
        self._evicting = False
        self.weight_vram_mb = 1
        self.inference_vram_mb = 1
        self._weight_allocation: WeightAllocation | None = None
        self._device_id: str | None = None
        self._gpu_worker: GPUWorkerHandle | None = None
        self._runtime: _ModelRuntimeProtocol | None = None
        self._runtime_adapter = _ModelWorkerSchedulerAdapter(self)
        self._load_lock = asyncio.Lock()
        self._last_inference_peak_mb: int | None = None
        self._last_used_tick = time.monotonic_ns()

    @property
    def worker_id(self) -> str:
        if self._gpu_worker is not None:
            return str(self._gpu_worker.worker_id)
        return f"model-worker-{self.model_id}"

    @property
    def device_id(self) -> str | None:
        return self._device_id

    @property
    def runtime(self) -> _ModelRuntimeProtocol:
        if self._runtime is None:
            raise RuntimeError(f"model {self.model_id} is not loaded")
        return self._runtime

    @property
    def weight_allocated(self) -> bool:
        return self._weight_allocated

    @property
    def inference_busy(self) -> bool:
        return self._inference_busy_holds > 0

    @property
    def evicting(self) -> bool:
        return self._evicting

    @property
    def last_used_tick(self) -> int:
        return self._last_used_tick
