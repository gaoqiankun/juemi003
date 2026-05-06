from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, NewType, Protocol

import structlog


def normalize_model_name(model_name: str) -> str:
    return str(model_name).strip().lower()


def normalize_device_id(device_id: str) -> str:
    return str(device_id).strip()


def normalize_vram_mb(value: object, *, minimum: int = 1) -> int:
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        normalized = minimum
    return max(normalized, minimum)


WeightAllocationID = NewType("WeightAllocationID", str)
InferenceAllocationID = NewType("InferenceAllocationID", str)


@dataclass(slots=True)
class WeightAllocation:
    allocation_id: WeightAllocationID
    device_id: str


@dataclass(slots=True)
class InferenceAllocation:
    inference_allocation_id: InferenceAllocationID
    weight_allocation_id: WeightAllocationID | None
    device_id: str


class InferenceLease:
    """Per-task inference allocation holder.

    The lease acquires inference allocation on enter and always releases it on
    exit. Callers can bump the estimate and re-request once after an OOM.
    """

    def __init__(
        self,
        *,
        allocator: "VRAMAllocator",
        model_id: str,
        device_id: str,
        estimate_mb: int,
        weight_mb: int,
    ) -> None:
        self._allocator = allocator
        self._model_id = normalize_model_name(model_id)
        self._device_id = normalize_device_id(device_id)
        self._estimate_mb = normalize_vram_mb(estimate_mb)
        self._weight_mb = normalize_vram_mb(weight_mb)
        self._allocation: InferenceAllocation | None = None
        self._entered = False

    @property
    def allocation(self) -> InferenceAllocation:
        if self._allocation is None:
            raise RuntimeError("inference lease is not active")
        return self._allocation

    async def __aenter__(self) -> "InferenceLease":
        if self._entered:
            raise RuntimeError("inference lease cannot be entered twice")
        self._allocation = await self._allocator.request_inference(
            model_id=self._model_id,
            device_id=self._device_id,
            inference_mb=self._estimate_mb,
            weight_mb=self._weight_mb,
        )
        self._device_id = self._allocation.device_id
        self._entered = True
        return self

    async def bump_and_retry_once(self, new_estimate_mb: int) -> None:
        if not self._entered or self._allocation is None:
            raise RuntimeError("cannot bump a lease that is not active")
        self._allocator.release_inference(self._allocation.inference_allocation_id)
        self._estimate_mb = normalize_vram_mb(new_estimate_mb)
        self._allocation = await self._allocator.request_inference(
            model_id=self._model_id,
            device_id=self._device_id,
            inference_mb=self._estimate_mb,
            weight_mb=self._weight_mb,
        )
        self._device_id = self._allocation.device_id

    async def __aexit__(self, exc_type, exc, tb) -> None:
        _ = exc_type
        _ = exc
        _ = tb
        allocation = self._allocation
        self._allocation = None
        self._entered = False
        if allocation is not None:
            self._allocator.release_inference(allocation.inference_allocation_id)


@dataclass(slots=True)
class DeviceBudget:
    device_id: str
    total_vram_mb: int
    reserved_vram_mb: int = 0
    weight_allocations: dict[str, int] = field(default_factory=dict)
    inference_allocations: dict[str, int] = field(default_factory=dict)

    @property
    def used_weight_vram_mb(self) -> int:
        return sum(self.weight_allocations.values())

    @property
    def used_inference_vram_mb(self) -> int:
        return sum(self.inference_allocations.values())

    @property
    def used_vram_mb(self) -> int:
        return self.used_weight_vram_mb + self.used_inference_vram_mb

    @property
    def free_vram_mb(self) -> int:
        return max(self.total_vram_mb - self.reserved_vram_mb - self.used_vram_mb, 0)


class VRAMAllocatorError(RuntimeError):
    pass


class VRAMInsufficientError(VRAMAllocatorError):
    pass


class ExternalVRAMOccupationTimeoutError(VRAMAllocatorError):
    pass


class InternalVRAMContentionTimeoutError(VRAMAllocatorError):
    pass


VRAMProbe = Callable[[str], int | None]


class AcquireOutcomeCallback(Protocol):
    def __call__(self, *, device: str, outcome: str) -> None: ...


class AcquireWaitCallback(Protocol):
    def __call__(self, *, device: str, wait_seconds: float) -> None: ...


class EvictCallback(Protocol):
    def __call__(self, *, device: str, result: str) -> None: ...


EvictionListener = Callable[[str], Awaitable[None] | None]


@dataclass(slots=True)
class VRAMMetricsHook:
    on_acquire_outcome: AcquireOutcomeCallback | None = None
    on_acquire_wait: AcquireWaitCallback | None = None
    on_evict: EvictCallback | None = None


class ModelWorkerInterface(Protocol):
    async def evict(self) -> None: ...


_logger = structlog.get_logger(__name__)

# Public types above are imported by submodules during package initialization.
from cubie.vram.allocator.booking import BookingMixin  # noqa: E402
from cubie.vram.allocator.config import ConfigMixin  # noqa: E402
from cubie.vram.allocator.eviction import EvictionMixin  # noqa: E402
from cubie.vram.allocator.inference import InferenceMixin  # noqa: E402
from cubie.vram.allocator.metrics import MetricsMixin  # noqa: E402
from cubie.vram.allocator.probe import ProbeMixin  # noqa: E402
from cubie.vram.allocator.weight import WeightMixin  # noqa: E402

__all__ = (
    "AcquireOutcomeCallback",
    "AcquireWaitCallback",
    "DeviceBudget",
    "EvictCallback",
    "EvictionListener",
    "ExternalVRAMOccupationTimeoutError",
    "InferenceAllocation",
    "InferenceAllocationID",
    "InferenceLease",
    "InternalVRAMContentionTimeoutError",
    "ModelWorkerInterface",
    "VRAMAllocator",
    "VRAMAllocatorError",
    "VRAMInsufficientError",
    "VRAMMetricsHook",
    "VRAMProbe",
    "WeightAllocation",
    "WeightAllocationID",
    "normalize_device_id",
    "normalize_model_name",
    "normalize_vram_mb",
)


class VRAMAllocator(
    ConfigMixin,
    WeightMixin,
    InferenceMixin,
    BookingMixin,
    EvictionMixin,
    ProbeMixin,
    MetricsMixin,
):
    _INFERENCE_WAIT_SECONDS = 0.05
    _MIGRATION_WAIT_SECONDS = 5.0
    _PROBE_INTERVAL_SECONDS = 5.0
    _DEFAULT_SAFETY_MARGIN_MB = 1024
    _EXTERNAL_BASELINE_NOISE_MB = 512
    _DEFAULT_EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS = 30.0
    _DEFAULT_INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS = 60.0

    def __init__(
        self,
        *,
        device_totals_mb: dict[str, int],
        device_reserved_mb: dict[str, int] | None = None,
    ) -> None:
        if not device_totals_mb:
            raise ValueError("device_totals_mb must not be empty")
        reserved_lookup = {
            normalize_device_id(device_id): normalize_vram_mb(reserved, minimum=0)
            for device_id, reserved in (device_reserved_mb or {}).items()
        }
        self._budgets: dict[str, DeviceBudget] = {}
        for raw_device_id, raw_total_mb in device_totals_mb.items():
            device_id = normalize_device_id(raw_device_id)
            total_vram_mb = normalize_vram_mb(raw_total_mb)
            reserved_vram_mb = min(
                reserved_lookup.get(device_id, 0),
                max(total_vram_mb - 1, 0),
            )
            self._budgets[device_id] = DeviceBudget(
                device_id=device_id,
                total_vram_mb=total_vram_mb,
                reserved_vram_mb=reserved_vram_mb,
            )
        self._worker_registry: dict[str, ModelWorkerInterface] = {}
        self._weight_alloc_to_device: dict[str, str] = {}
        self._weight_alloc_to_model: dict[str, str] = {}
        self._weight_alloc_to_mb: dict[str, int] = {}
        self._model_to_weight_alloc: dict[str, str] = {}
        self._inference_to_device: dict[str, str] = {}
        self._inference_to_model: dict[str, str] = {}
        self._inference_to_mb: dict[str, int] = {}
        self._next_weight_allocation_id = 1
        self._next_inference_allocation_id = 1
        self._lock = asyncio.Lock()
        self._vram_probe: VRAMProbe | None = None
        self._external_baselines: dict[str, int] = {
            device_id: 0 for device_id in self._budgets
        }
        self._probe_task: asyncio.Task | None = None
        self._probe_warned_unavailable = False
        self._safety_margin_mb = self._DEFAULT_SAFETY_MARGIN_MB
        self._external_vram_wait_timeout_seconds = (
            self._DEFAULT_EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS
        )
        self._internal_vram_wait_timeout_seconds = (
            self._DEFAULT_INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS
        )
        self._metrics_hook: VRAMMetricsHook | None = None
        self._evict_callback: Callable[[str, str], asyncio.Future[bool]] | None = None
        self._eviction_listeners: list[EvictionListener] = []
        self._eviction_listener_tasks: set[asyncio.Task[None]] = set()
