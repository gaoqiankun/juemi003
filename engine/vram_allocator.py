from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable, Iterable, NewType, Protocol

import structlog


def _normalize_model_name(model_name: str) -> str:
    return str(model_name).strip().lower()


def _normalize_device_id(device_id: str) -> str:
    return str(device_id).strip()


def _normalize_vram_mb(value: object, *, minimum: int = 1) -> int:
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


@dataclass(slots=True)
class VRAMMetricsHook:
    on_acquire_outcome: AcquireOutcomeCallback | None = None
    on_acquire_wait: AcquireWaitCallback | None = None
    on_evict: EvictCallback | None = None


class ModelWorkerInterface(Protocol):
    async def evict(self) -> None: ...


_logger = structlog.get_logger(__name__)


class VRAMAllocator:
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
            _normalize_device_id(device_id): _normalize_vram_mb(reserved, minimum=0)
            for device_id, reserved in (device_reserved_mb or {}).items()
        }
        self._budgets: dict[str, DeviceBudget] = {}
        for raw_device_id, raw_total_mb in device_totals_mb.items():
            device_id = _normalize_device_id(raw_device_id)
            total_vram_mb = _normalize_vram_mb(raw_total_mb)
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

    @property
    def device_ids(self) -> tuple[str, ...]:
        return tuple(self._budgets.keys())

    def assignment_for(self, model_name: str) -> str | None:
        normalized_model = _normalize_model_name(model_name)
        allocation_id = self._model_to_weight_alloc.get(normalized_model)
        if allocation_id is None:
            return None
        return self._weight_alloc_to_device.get(allocation_id)

    def set_evict_callback(
        self,
        cb: Callable[[str, str], asyncio.Future[bool]] | None,
    ) -> None:
        # deprecated: kept for compatibility with older tests/code paths.
        self._evict_callback = cb

    def set_vram_probe(self, probe: VRAMProbe | None) -> None:
        """Inject runtime per-device free VRAM probe (MB). None disables probing."""
        self._vram_probe = probe
        if probe is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self._stop_probe_loop())

    def set_metrics_hook(self, hook: VRAMMetricsHook | None) -> None:
        self._metrics_hook = hook

    def set_external_vram_wait_timeout_seconds(self, seconds: float | None) -> None:
        if seconds is None or seconds <= 0:
            self._external_vram_wait_timeout_seconds = (
                self._DEFAULT_EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS
            )
            return
        self._external_vram_wait_timeout_seconds = float(seconds)

    @property
    def external_vram_wait_timeout_seconds(self) -> float:
        return self._external_vram_wait_timeout_seconds

    def set_internal_vram_wait_timeout_seconds(self, seconds: float | None) -> None:
        if seconds is None or seconds <= 0:
            self._internal_vram_wait_timeout_seconds = (
                self._DEFAULT_INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS
            )
            return
        self._internal_vram_wait_timeout_seconds = float(seconds)

    @property
    def internal_vram_wait_timeout_seconds(self) -> float:
        return self._internal_vram_wait_timeout_seconds

    def active_inference_model_names_on(self, device_id: str) -> frozenset[str]:
        normalized_device = _normalize_device_id(device_id)
        if normalized_device not in self._budgets:
            return frozenset()
        return frozenset(
            model_name
            for allocation_id, inference_device_id in self._inference_to_device.items()
            if inference_device_id == normalized_device
            and (model_name := self._inference_to_model.get(allocation_id)) is not None
        )

    async def request_weight(
        self,
        model_id: str,
        mb: int,
        exclude_device_ids: tuple[str, ...] = (),
    ) -> WeightAllocation:
        normalized_model = _normalize_model_name(model_id)
        required_mb = _normalize_vram_mb(mb)
        excluded = {
            normalized
            for raw in exclude_device_ids
            if (normalized := _normalize_device_id(raw))
        }
        await self._start_probe_loop()
        async with self._lock:
            candidate_device_ids = tuple(
                device_id
                for device_id in self._budgets
                if device_id not in excluded
            )
            if not candidate_device_ids:
                raise VRAMInsufficientError("no allocatable GPU devices are available")

            for device_id in candidate_device_ids:
                allocation = self._try_book_weight(
                    model_id=normalized_model,
                    device_id=device_id,
                    required_mb=required_mb,
                )
                if allocation is not None:
                    return allocation

                idle_candidates = self._idle_candidates_on(
                    device_id=device_id,
                    exclude_model_id=normalized_model,
                )
                for candidate_model_name, candidate_worker in idle_candidates:
                    evicted = await self._evict_worker(
                        device_id=device_id,
                        requester_model_name=normalized_model,
                        candidate_model_name=candidate_model_name,
                        candidate_worker=candidate_worker,
                    )
                    if not evicted:
                        continue
                    allocation = self._try_book_weight(
                        model_id=normalized_model,
                        device_id=device_id,
                        required_mb=required_mb,
                    )
                    if allocation is not None:
                        return allocation

            free_by_device = {
                device_id: self._safe_free_mb(device_id)
                for device_id in candidate_device_ids
            }
            raise VRAMInsufficientError(
                "insufficient VRAM for weight allocation "
                f"(model={normalized_model}, required_mb={required_mb}, "
                f"free_by_device={free_by_device})"
            )

    def release_weight(self, allocation_id: WeightAllocationID) -> None:
        normalized_allocation_id = str(allocation_id).strip()
        if not normalized_allocation_id:
            return

        device_id = self._weight_alloc_to_device.pop(normalized_allocation_id, None)
        self._weight_alloc_to_mb.pop(normalized_allocation_id, None)
        model_id = self._weight_alloc_to_model.pop(normalized_allocation_id, None)
        if model_id is not None and self._model_to_weight_alloc.get(model_id) == normalized_allocation_id:
            self._model_to_weight_alloc.pop(model_id, None)
        if device_id is None:
            return
        budget = self._budgets.get(device_id)
        if budget is None:
            return
        budget.weight_allocations.pop(normalized_allocation_id, None)

    def correct_weight(self, allocation_id: WeightAllocationID, actual_mb: int) -> None:
        normalized_allocation_id = str(allocation_id).strip()
        if not normalized_allocation_id:
            return
        expected_mb = self._weight_alloc_to_mb.get(normalized_allocation_id)
        if expected_mb is None:
            return
        normalized_actual_mb = _normalize_vram_mb(actual_mb)
        if normalized_actual_mb <= expected_mb:
            return
        self._weight_alloc_to_mb[normalized_allocation_id] = normalized_actual_mb
        device_id = self._weight_alloc_to_device.get(normalized_allocation_id)
        if device_id is None:
            return
        budget = self._budgets.get(device_id)
        if budget is None:
            return
        budget.weight_allocations[normalized_allocation_id] = normalized_actual_mb

    def register_worker(self, model_id: str, worker: ModelWorkerInterface) -> None:
        self._worker_registry[_normalize_model_name(model_id)] = worker

    def unregister_worker(self, model_id: str) -> None:
        self._worker_registry.pop(_normalize_model_name(model_id), None)

    async def request_inference(
        self,
        model_id: str,
        device_id: str,
        inference_mb: int,
        weight_mb: int,
    ) -> InferenceAllocation:
        normalized_model = _normalize_model_name(model_id)
        normalized_device = _normalize_device_id(device_id)
        required_inference_mb = _normalize_vram_mb(inference_mb)
        required_weight_mb = _normalize_vram_mb(weight_mb)
        await self._start_probe_loop()
        loop = asyncio.get_running_loop()
        wait_started_at: float | None = None
        evict_succeeded = False

        async with self._lock:
            current_weight_allocation = self._model_to_weight_alloc.get(normalized_model)
            if current_weight_allocation is None:
                raise VRAMAllocatorError(f"model {normalized_model} is not assigned to a GPU device")
            assigned_device = self._weight_alloc_to_device.get(current_weight_allocation)
            if assigned_device is None:
                raise VRAMAllocatorError(
                    f"model {normalized_model} has dangling allocation {current_weight_allocation}"
                )
            if normalized_device != assigned_device:
                normalized_device = assigned_device

            wait_deadline = loop.time() + self._MIGRATION_WAIT_SECONDS
            while True:
                inference_allocation_id = self._try_book_inference(
                    model_id=normalized_model,
                    device_id=normalized_device,
                    required_mb=required_inference_mb,
                )
                if inference_allocation_id is not None:
                    outcome = self._resolve_success_outcome(
                        evict_succeeded=evict_succeeded,
                        waited=wait_started_at is not None,
                    )
                    self._emit_acquire_result(
                        device_id=normalized_device,
                        outcome=outcome,
                        wait_seconds=self._wait_seconds(
                            started_at=wait_started_at,
                            now=loop.time(),
                        ),
                    )
                    return InferenceAllocation(
                        inference_allocation_id=inference_allocation_id,
                        weight_allocation_id=None,
                        device_id=normalized_device,
                    )

                idle_candidates = self._idle_candidates_on(
                    device_id=normalized_device,
                    exclude_model_id=normalized_model,
                )
                if idle_candidates:
                    for candidate_model_name, candidate_worker in idle_candidates:
                        evicted = await self._evict_worker(
                            device_id=normalized_device,
                            requester_model_name=normalized_model,
                            candidate_model_name=candidate_model_name,
                            candidate_worker=candidate_worker,
                        )
                        if not evicted:
                            continue
                        evict_succeeded = True
                        inference_allocation_id = self._try_book_inference(
                            model_id=normalized_model,
                            device_id=normalized_device,
                            required_mb=required_inference_mb,
                        )
                        if inference_allocation_id is not None:
                            self._emit_acquire_result(
                                device_id=normalized_device,
                                outcome="after_evict",
                                wait_seconds=self._wait_seconds(
                                    started_at=wait_started_at,
                                    now=loop.time(),
                                ),
                            )
                            return InferenceAllocation(
                                inference_allocation_id=inference_allocation_id,
                                weight_allocation_id=None,
                                device_id=normalized_device,
                            )

                now = loop.time()
                if now >= wait_deadline:
                    break
                if wait_started_at is None:
                    wait_started_at = now
                await asyncio.sleep(self._INFERENCE_WAIT_SECONDS)

            for candidate_device_id in self._budgets:
                if candidate_device_id == normalized_device:
                    continue
                migration = await self._try_book_migration(
                    model_id=normalized_model,
                    device_id=candidate_device_id,
                    required_inference_mb=required_inference_mb,
                    required_weight_mb=required_weight_mb,
                )
                if migration is None:
                    continue
                inference_allocation_id, weight_allocation_id = migration
                self._emit_acquire_result(
                    device_id=normalized_device,
                    outcome="migrated",
                    wait_seconds=self._wait_seconds(
                        started_at=wait_started_at,
                        now=loop.time(),
                    ),
                )
                return InferenceAllocation(
                    inference_allocation_id=inference_allocation_id,
                    weight_allocation_id=weight_allocation_id,
                    device_id=candidate_device_id,
                )

            self._emit_acquire_result(
                device_id=normalized_device,
                outcome="timeout_internal",
                wait_seconds=self._wait_seconds(
                    started_at=wait_started_at,
                    now=loop.time(),
                ),
            )
            free_by_device = {
                candidate_device: self._safe_free_mb(candidate_device)
                for candidate_device in self._budgets
            }
            raise VRAMInsufficientError(
                "insufficient VRAM for inference "
                f"(model={normalized_model}, device={normalized_device}, "
                f"required_inference_mb={required_inference_mb}, "
                f"required_weight_mb={required_weight_mb}, "
                f"free_by_device={free_by_device})"
            )

    def release_inference(self, allocation_id: InferenceAllocationID | str) -> None:
        normalized_allocation_id = str(allocation_id).strip()
        if not normalized_allocation_id:
            return

        device_id = self._inference_to_device.pop(normalized_allocation_id, None)
        self._inference_to_model.pop(normalized_allocation_id, None)
        self._inference_to_mb.pop(normalized_allocation_id, None)
        if device_id is None:
            return
        budget = self._budgets.get(device_id)
        if budget is None:
            return
        budget.inference_allocations.pop(normalized_allocation_id, None)

    def snapshot(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for device_id, budget in self._budgets.items():
            allocations_by_model: dict[str, int] = {}
            for allocation_id, booked_mb in budget.weight_allocations.items():
                model_name = self._weight_alloc_to_model.get(allocation_id)
                if model_name is None:
                    continue
                allocations_by_model[model_name] = (
                    allocations_by_model.get(model_name, 0) + booked_mb
                )

            result[device_id] = {
                "total_vram_mb": budget.total_vram_mb,
                "reserved_vram_mb": budget.reserved_vram_mb,
                "external_baseline_mb": self._external_baselines.get(device_id, 0),
                "safety_margin_mb": self._safety_margin_mb,
                "used_weight_vram_mb": budget.used_weight_vram_mb,
                "used_inference_vram_mb": budget.used_inference_vram_mb,
                "free_vram_mb": budget.free_vram_mb,
                "safe_free_vram_mb": self._safe_free_mb(device_id),
                "allocations": allocations_by_model,
                "weight_allocations": dict(budget.weight_allocations),
                "weight_allocation_models": {
                    allocation_id: model_name
                    for allocation_id in budget.weight_allocations
                    if (model_name := self._weight_alloc_to_model.get(allocation_id)) is not None
                },
                "inference_allocations": dict(budget.inference_allocations),
                "inference_allocation_models": {
                    allocation_id: model_name
                    for allocation_id in budget.inference_allocations
                    if (model_name := self._inference_to_model.get(allocation_id)) is not None
                },
            }
        return result

    # deprecated
    def reserve(
        self,
        *,
        model_name: str,
        weight_vram_mb: int,
        allowed_device_ids: Iterable[str] | None = None,
        preferred_device_id: str | None = None,
    ) -> str:
        normalized_model = _normalize_model_name(model_name)
        required_mb = _normalize_vram_mb(weight_vram_mb)
        candidate_ids = self._resolve_candidate_ids(
            allowed_device_ids=allowed_device_ids,
            preferred_device_id=preferred_device_id,
        )
        for device_id in candidate_ids:
            allocation = self._try_book_weight(
                model_id=normalized_model,
                device_id=device_id,
                required_mb=required_mb,
            )
            if allocation is not None:
                return allocation.device_id
        free_by_device = {
            device_id: self._safe_free_mb(device_id)
            for device_id in candidate_ids
        }
        raise VRAMAllocatorError(
            "insufficient VRAM to place model "
            f"{normalized_model}: requires {required_mb} MB "
            f"(free_by_device={free_by_device})"
        )

    # deprecated
    def release(self, model_name: str) -> None:
        normalized_model = _normalize_model_name(model_name)
        allocation_id = self._model_to_weight_alloc.get(normalized_model)
        if allocation_id is not None:
            self.release_weight(WeightAllocationID(allocation_id))
        for inference_id, allocated_model in tuple(self._inference_to_model.items()):
            if allocated_model != normalized_model:
                continue
            self.release_inference(inference_id)

    # deprecated
    async def acquire_inference(
        self,
        *,
        model_name: str,
        device_id: str,
        inference_vram_mb: int,
    ) -> str:
        normalized_model = _normalize_model_name(model_name)
        current_weight_allocation = self._model_to_weight_alloc.get(normalized_model)
        if current_weight_allocation is None:
            raise VRAMAllocatorError(f"model {normalized_model} is not assigned to a GPU device")
        weight_mb = self._weight_alloc_to_mb.get(current_weight_allocation, 1)
        inference_allocation = await self.request_inference(
            model_id=normalized_model,
            device_id=device_id,
            inference_mb=inference_vram_mb,
            weight_mb=weight_mb,
        )
        if inference_allocation.weight_allocation_id is not None:
            # Old scheduler path cannot execute migration. Roll back the migration booking.
            self.release_inference(inference_allocation.inference_allocation_id)
            self.release_weight(inference_allocation.weight_allocation_id)
            self._model_to_weight_alloc[normalized_model] = current_weight_allocation
            raise InternalVRAMContentionTimeoutError(
                "inference migration requires ModelWorker execution path"
            )
        return str(inference_allocation.inference_allocation_id)

    def _resolve_candidate_ids(
        self,
        *,
        allowed_device_ids: Iterable[str] | None,
        preferred_device_id: str | None,
    ) -> tuple[str, ...]:
        if allowed_device_ids is None:
            allowed = tuple(self._budgets.keys())
        else:
            allowed = tuple(
                device_id
                for raw_device_id in allowed_device_ids
                if (device_id := _normalize_device_id(raw_device_id)) in self._budgets
            )
        if not allowed:
            raise VRAMAllocatorError("no allocatable GPU devices are available")

        if preferred_device_id is None:
            return allowed

        preferred = _normalize_device_id(preferred_device_id)
        if preferred not in self._budgets:
            raise VRAMAllocatorError(f"preferred GPU device is unknown: {preferred}")
        if preferred not in set(allowed):
            raise VRAMAllocatorError(f"preferred GPU device is not allocatable: {preferred}")
        return (preferred,)

    def _try_book_weight(
        self,
        *,
        model_id: str,
        device_id: str,
        required_mb: int,
    ) -> WeightAllocation | None:
        normalized_device = _normalize_device_id(device_id)
        if normalized_device not in self._budgets:
            raise VRAMAllocatorError(f"unknown GPU device: {normalized_device}")
        if self._safe_free_mb(normalized_device) < required_mb:
            return None

        allocation_id = WeightAllocationID(
            f"{model_id}:weight:{self._next_weight_allocation_id}"
        )
        self._next_weight_allocation_id += 1
        allocation_key = str(allocation_id)
        self._weight_alloc_to_device[allocation_key] = normalized_device
        self._weight_alloc_to_model[allocation_key] = model_id
        self._weight_alloc_to_mb[allocation_key] = required_mb
        self._budgets[normalized_device].weight_allocations[allocation_key] = required_mb
        self._model_to_weight_alloc[model_id] = allocation_key
        return WeightAllocation(allocation_id=allocation_id, device_id=normalized_device)

    def _try_book_inference(
        self,
        *,
        model_id: str,
        device_id: str,
        required_mb: int,
    ) -> InferenceAllocationID | None:
        normalized_device = _normalize_device_id(device_id)
        if normalized_device not in self._budgets:
            raise VRAMAllocatorError(f"unknown GPU device: {normalized_device}")
        if self._safe_free_mb(normalized_device) < required_mb:
            return None

        allocation_id = InferenceAllocationID(
            f"{model_id}:inference:{self._next_inference_allocation_id}"
        )
        self._next_inference_allocation_id += 1
        allocation_key = str(allocation_id)
        self._inference_to_device[allocation_key] = normalized_device
        self._inference_to_model[allocation_key] = model_id
        self._inference_to_mb[allocation_key] = required_mb
        self._budgets[normalized_device].inference_allocations[allocation_key] = required_mb
        return allocation_id

    async def _try_book_migration(
        self,
        *,
        model_id: str,
        device_id: str,
        required_inference_mb: int,
        required_weight_mb: int,
    ) -> tuple[InferenceAllocationID, WeightAllocationID] | None:
        total_required_mb = required_inference_mb + required_weight_mb
        if self._safe_free_mb(device_id) < total_required_mb:
            idle_candidates = self._idle_candidates_on(
                device_id=device_id,
                exclude_model_id=model_id,
            )
            for candidate_model_name, candidate_worker in idle_candidates:
                evicted = await self._evict_worker(
                    device_id=device_id,
                    requester_model_name=model_id,
                    candidate_model_name=candidate_model_name,
                    candidate_worker=candidate_worker,
                )
                if not evicted:
                    continue
                if self._safe_free_mb(device_id) >= total_required_mb:
                    break

        if self._safe_free_mb(device_id) < total_required_mb:
            return None

        weight_allocation = self._try_book_weight(
            model_id=model_id,
            device_id=device_id,
            required_mb=required_weight_mb,
        )
        if weight_allocation is None:
            return None
        inference_allocation = self._try_book_inference(
            model_id=model_id,
            device_id=device_id,
            required_mb=required_inference_mb,
        )
        if inference_allocation is None:
            self.release_weight(weight_allocation.allocation_id)
            return None
        return inference_allocation, weight_allocation.allocation_id

    async def _evict_worker(
        self,
        *,
        device_id: str,
        requester_model_name: str,
        candidate_model_name: str,
        candidate_worker: ModelWorkerInterface,
    ) -> bool:
        _ = requester_model_name
        _ = candidate_model_name
        try:
            await candidate_worker.evict()
        except Exception:
            self._emit_evict_result(device_id=device_id, result="failure")
            _logger.warning(
                "vram_allocator.evict_failed",
                device_id=device_id,
                requester_model_name=requester_model_name,
                candidate_model_name=candidate_model_name,
            )
            return False
        self._emit_evict_result(device_id=device_id, result="success")
        return True

    def _idle_candidates_on(
        self,
        device_id: str,
        exclude_model_id: str,
    ) -> list[tuple[str, ModelWorkerInterface]]:
        normalized_device = _normalize_device_id(device_id)
        candidates: list[tuple[str, ModelWorkerInterface]] = []
        for model_id, worker in self._worker_registry.items():
            if model_id == exclude_model_id:
                continue
            candidate_device = _normalize_device_id(getattr(worker, "device_id", ""))
            if candidate_device != normalized_device:
                continue
            if not bool(getattr(worker, "weight_allocated", False)):
                continue
            if bool(getattr(worker, "inference_busy", False)):
                continue
            if bool(getattr(worker, "evicting", False)):
                continue
            candidates.append((model_id, worker))
        candidates.sort(key=lambda item: int(getattr(item[1], "last_used_tick", 0)))
        return candidates

    def _safe_free_mb(self, device_id: str) -> int:
        normalized_device = _normalize_device_id(device_id)
        budget = self._budgets.get(normalized_device)
        if budget is None:
            raise VRAMAllocatorError(f"unknown GPU device: {normalized_device}")
        baseline = self._external_baselines.get(normalized_device, 0)
        safe_free = (
            budget.total_vram_mb
            - budget.reserved_vram_mb
            - budget.used_weight_vram_mb
            - budget.used_inference_vram_mb
            - baseline
            - self._safety_margin_mb
        )
        return max(safe_free, 0)

    async def _start_probe_loop(self) -> None:
        if self._vram_probe is None:
            return
        if self._probe_task is not None and not self._probe_task.done():
            return
        self._probe_task = asyncio.create_task(
            self._probe_loop(),
            name="vram-allocator-probe-loop",
        )

    async def _stop_probe_loop(self) -> None:
        task = self._probe_task
        if task is None:
            return
        self._probe_task = None
        if task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _probe_loop(self) -> None:
        while True:
            await asyncio.sleep(self._PROBE_INTERVAL_SECONDS)
            await self._apply_external_baselines()

    async def _apply_external_baselines(self) -> None:
        probe = self._vram_probe
        if probe is None:
            return
        async with self._lock:
            for device_id, budget in self._budgets.items():
                if budget.used_inference_vram_mb > 0:
                    continue
                try:
                    probed_free_mb = probe(device_id)
                except Exception as exc:
                    if not self._probe_warned_unavailable:
                        self._probe_warned_unavailable = True
                        _logger.warning(
                            "vram_allocator.probe_unavailable",
                            error=str(exc),
                        )
                    continue
                if probed_free_mb is None:
                    continue
                expected_free_mb = (
                    budget.total_vram_mb
                    - budget.reserved_vram_mb
                    - budget.used_weight_vram_mb
                )
                external_observed_mb = max(expected_free_mb - max(int(probed_free_mb), 0), 0)
                if external_observed_mb <= self._EXTERNAL_BASELINE_NOISE_MB:
                    continue

                baseline = self._external_baselines.get(device_id, 0)
                if external_observed_mb > baseline:
                    baseline = int(round((0.8 * baseline) + (0.2 * external_observed_mb)))
                elif external_observed_mb < baseline * 0.5:
                    baseline = int(round((0.5 * baseline) + (0.5 * external_observed_mb)))
                self._external_baselines[device_id] = max(baseline, 0)

    def _emit_acquire_result(
        self,
        *,
        device_id: str,
        outcome: str,
        wait_seconds: float,
    ) -> None:
        hook = self._metrics_hook
        if hook is None:
            return
        if hook.on_acquire_outcome is not None:
            try:
                hook.on_acquire_outcome(
                    device=device_id,
                    outcome=outcome,
                )
            except Exception as exc:
                _logger.warning(
                    "vram_allocator.metrics_hook_failed",
                    hook="on_acquire_outcome",
                    error=str(exc),
                )
        if hook.on_acquire_wait is not None:
            try:
                hook.on_acquire_wait(
                    device=device_id,
                    wait_seconds=max(wait_seconds, 0.0),
                )
            except Exception as exc:
                _logger.warning(
                    "vram_allocator.metrics_hook_failed",
                    hook="on_acquire_wait",
                    error=str(exc),
                )

    def _emit_evict_result(
        self,
        *,
        device_id: str,
        result: str,
    ) -> None:
        hook = self._metrics_hook
        if hook is None or hook.on_evict is None:
            return
        try:
            hook.on_evict(device=device_id, result=result)
        except Exception as exc:
            _logger.warning(
                "vram_allocator.metrics_hook_failed",
                hook="on_evict",
                error=str(exc),
            )

    @staticmethod
    def _wait_seconds(*, started_at: float | None, now: float) -> float:
        if started_at is None:
            return 0.0
        return max(now - started_at, 0.0)

    @staticmethod
    def _resolve_success_outcome(
        *,
        evict_succeeded: bool,
        waited: bool,
    ) -> str:
        if evict_succeeded:
            return "after_evict"
        if waited:
            return "after_wait"
        return "immediate"
