from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable, Protocol

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


@dataclass(slots=True)
class DeviceBudget:
    device_id: str
    total_vram_mb: int
    reserved_vram_mb: int = 0
    allocations: dict[str, int] = field(default_factory=dict)
    inference_allocations: dict[str, int] = field(default_factory=dict)

    @property
    def used_weight_vram_mb(self) -> int:
        return sum(self.allocations.values())

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


_logger = structlog.get_logger(__name__)


class VRAMAllocator:
    _INFERENCE_WAIT_SECONDS = 0.01
    _EVICT_WAIT_WINDOW_SECONDS = 2.0
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
        self._model_to_device: dict[str, str] = {}
        self._inference_to_device: dict[str, str] = {}
        self._inference_to_model: dict[str, str] = {}
        self._next_inference_allocation_id = 1
        self._evict_callback: Callable[[str, str], Awaitable[bool]] | None = None
        self._vram_probe: VRAMProbe | None = None
        self._external_vram_wait_timeout_seconds = (
            self._DEFAULT_EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS
        )
        self._internal_vram_wait_timeout_seconds = (
            self._DEFAULT_INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS
        )
        self._metrics_hook: VRAMMetricsHook | None = None

    @property
    def device_ids(self) -> tuple[str, ...]:
        return tuple(self._budgets.keys())

    def assignment_for(self, model_name: str) -> str | None:
        return self._model_to_device.get(_normalize_model_name(model_name))

    def set_evict_callback(
        self,
        cb: Callable[[str, str], Awaitable[bool]] | None,
    ) -> None:
        self._evict_callback = cb

    def set_vram_probe(self, probe: VRAMProbe | None) -> None:
        """Inject runtime per-device free VRAM probe (MB). None disables probing."""
        self._vram_probe = probe

    def set_metrics_hook(self, hook: VRAMMetricsHook | None) -> None:
        self._metrics_hook = hook

    def set_external_vram_wait_timeout_seconds(self, seconds: float | None) -> None:
        """Set external VRAM wait timeout. None/<=0 falls back to default."""
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
        """Set internal contention timeout. None/<=0 falls back to default."""
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

        current_device = self._model_to_device.get(normalized_model)
        if current_device is not None:
            budget = self._budgets.get(current_device)
            if budget is not None:
                budget.allocations[normalized_model] = required_mb
                return budget.device_id

        candidate_ids = self._resolve_candidate_ids(
            allowed_device_ids=allowed_device_ids,
            preferred_device_id=preferred_device_id,
        )
        for device_id in candidate_ids:
            budget = self._budgets[device_id]
            if self._effective_free_mb(device_id, budget) < required_mb:
                continue
            budget.allocations[normalized_model] = required_mb
            self._model_to_device[normalized_model] = device_id
            return device_id

        free_by_device = {
            device_id: self._budgets[device_id].free_vram_mb for device_id in candidate_ids
        }
        requested = (
            f"preferred device {preferred_device_id} "
            if preferred_device_id is not None
            else "any allowed device "
        )
        raise VRAMAllocatorError(
            "insufficient VRAM to place model "
            f"{normalized_model}: requires {required_mb} MB on {requested}"
            f"(free_by_device={free_by_device})"
        )

    def release(self, model_name: str) -> None:
        normalized_model = _normalize_model_name(model_name)
        device_id = self._model_to_device.pop(normalized_model, None)
        if device_id is None:
            return
        budget = self._budgets.get(device_id)
        if budget is None:
            return
        budget.allocations.pop(normalized_model, None)
        for allocation_id, allocated_model in tuple(self._inference_to_model.items()):
            if allocated_model != normalized_model:
                continue
            self._inference_to_model.pop(allocation_id, None)
            inference_device = self._inference_to_device.pop(allocation_id, None)
            if inference_device is None:
                continue
            inference_budget = self._budgets.get(inference_device)
            if inference_budget is not None:
                inference_budget.inference_allocations.pop(allocation_id, None)

    async def acquire_inference(
        self,
        *,
        model_name: str,
        device_id: str,
        inference_vram_mb: int,
    ) -> str:
        normalized_model = _normalize_model_name(model_name)
        normalized_device = _normalize_device_id(device_id)
        required_mb = _normalize_vram_mb(inference_vram_mb)
        loop = asyncio.get_running_loop()
        wait_window_start = loop.time()
        internal_wait_started_at: float | None = None
        external_occupied_since: float | None = None
        evict_succeeded = False

        while True:
            allocation_id = self._try_acquire_inference(
                model_name=normalized_model,
                device_id=normalized_device,
                inference_vram_mb=required_mb,
            )
            if allocation_id is not None:
                outcome = self._resolve_success_outcome(
                    evict_succeeded=evict_succeeded,
                    internal_wait_started_at=internal_wait_started_at,
                )
                self._emit_acquire_result(
                    device_id=normalized_device,
                    outcome=outcome,
                    wait_seconds=self._wait_seconds(
                        started_at=internal_wait_started_at,
                        now=loop.time(),
                    ),
                )
                return allocation_id
            now = loop.time()
            internal_wait_started_at = self._touch_internal_wait_or_raise(
                device_id=normalized_device,
                started_at=internal_wait_started_at,
                now=now,
            )

            budget = self._budgets.get(normalized_device)
            if budget is not None:
                try:
                    external_occupied_since = self._track_external_occupation_wait(
                        device_id=normalized_device,
                        budget=budget,
                        external_occupied_since=external_occupied_since,
                        now=now,
                    )
                except ExternalVRAMOccupationTimeoutError:
                    self._emit_acquire_result(
                        device_id=normalized_device,
                        outcome="timeout_external",
                        wait_seconds=self._wait_seconds(
                            started_at=internal_wait_started_at,
                            now=loop.time(),
                        ),
                    )
                    raise

            wait_window_start, evicted = await self._maybe_evict(
                device_id=normalized_device,
                model_name=normalized_model,
                wait_window_start=wait_window_start,
                now=loop.time(),
            )
            if evicted:
                evict_succeeded = True
                allocation_id = self._try_acquire_inference(
                    model_name=normalized_model,
                    device_id=normalized_device,
                    inference_vram_mb=required_mb,
                )
                if allocation_id is not None:
                    self._emit_acquire_result(
                        device_id=normalized_device,
                        outcome="after_evict",
                        wait_seconds=self._wait_seconds(
                            started_at=internal_wait_started_at,
                            now=loop.time(),
                        ),
                    )
                    return allocation_id
                # A successful evict starts a new waiting round.
                reset_at = loop.time()
                wait_window_start = reset_at
                internal_wait_started_at = reset_at
                external_occupied_since = None
            await asyncio.sleep(self._INFERENCE_WAIT_SECONDS)

    def release_inference(self, allocation_id: str) -> None:
        normalized_allocation_id = str(allocation_id).strip()
        if not normalized_allocation_id:
            return

        device_id = self._inference_to_device.pop(normalized_allocation_id, None)
        self._inference_to_model.pop(normalized_allocation_id, None)
        if device_id is None:
            return
        budget = self._budgets.get(device_id)
        if budget is None:
            return
        budget.inference_allocations.pop(normalized_allocation_id, None)

    def snapshot(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for device_id, budget in self._budgets.items():
            result[device_id] = {
                "total_vram_mb": budget.total_vram_mb,
                "reserved_vram_mb": budget.reserved_vram_mb,
                "used_weight_vram_mb": budget.used_weight_vram_mb,
                "used_inference_vram_mb": budget.used_inference_vram_mb,
                "free_vram_mb": budget.free_vram_mb,
                "effective_free_vram_mb": self._effective_free_mb(device_id, budget),
                "allocations": dict(budget.allocations),
                "inference_allocations": dict(budget.inference_allocations),
                "inference_allocation_models": {
                    allocation_id: model_name
                    for allocation_id in budget.inference_allocations
                    if (
                        model_name := self._inference_to_model.get(allocation_id)
                    ) is not None
                },
            }
        return result

    def _effective_free_mb(self, device_id: str, budget: DeviceBudget) -> int:
        """Return min(booked_free, probe_free) if probe available, else booked_free."""
        booked_free = budget.free_vram_mb
        if self._vram_probe is None:
            return booked_free
        try:
            probed = self._vram_probe(_normalize_device_id(device_id))
        except Exception:
            return booked_free
        if probed is None:
            return booked_free
        return min(booked_free, max(int(probed), 0))

    def _track_external_occupation_wait(
        self,
        *,
        device_id: str,
        budget: DeviceBudget,
        external_occupied_since: float | None,
        now: float,
    ) -> float | None:
        booked_free = budget.free_vram_mb
        effective_free = self._effective_free_mb(device_id, budget)
        if effective_free >= booked_free:
            return None
        if external_occupied_since is None:
            return now
        if now - external_occupied_since <= self._external_vram_wait_timeout_seconds:
            return external_occupied_since
        raise ExternalVRAMOccupationTimeoutError(
            "external VRAM occupation timeout after "
            f"{self._external_vram_wait_timeout_seconds:.1f}s "
            f"on device {device_id}"
        )

    async def _maybe_evict(
        self,
        *,
        device_id: str,
        model_name: str,
        wait_window_start: float,
        now: float,
    ) -> tuple[float, bool]:
        if now - wait_window_start < self._EVICT_WAIT_WINDOW_SECONDS:
            return wait_window_start, False
        evict_callback = self._evict_callback
        if evict_callback is None:
            return now, False
        try:
            evicted = await evict_callback(device_id, model_name)
        except Exception:
            self._emit_evict_result(device_id=device_id, result="failure")
            raise
        self._emit_evict_result(
            device_id=device_id,
            result="success" if evicted else "noop",
        )
        return asyncio.get_running_loop().time(), evicted

    def _raise_internal_contention_timeout(
        self,
        *,
        device_id: str,
        started_at: float,
        now: float,
    ) -> None:
        wait_seconds = self._wait_seconds(started_at=started_at, now=now)
        self._emit_acquire_result(
            device_id=device_id,
            outcome="timeout_internal",
            wait_seconds=wait_seconds,
        )
        raise InternalVRAMContentionTimeoutError(
            "internal VRAM contention timeout after "
            f"{self._internal_vram_wait_timeout_seconds:.1f}s "
            f"on device {device_id}"
        )

    def _touch_internal_wait_or_raise(
        self,
        *,
        device_id: str,
        started_at: float | None,
        now: float,
    ) -> float:
        if started_at is None:
            return now
        if now - started_at > self._internal_vram_wait_timeout_seconds:
            self._raise_internal_contention_timeout(
                device_id=device_id,
                started_at=started_at,
                now=now,
            )
        return started_at

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
        internal_wait_started_at: float | None,
    ) -> str:
        if evict_succeeded:
            return "after_evict"
        if internal_wait_started_at is not None:
            return "after_wait"
        return "immediate"

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

    def _try_acquire_inference(
        self,
        *,
        model_name: str,
        device_id: str,
        inference_vram_mb: int,
    ) -> str | None:
        budget = self._budgets.get(device_id)
        if budget is None:
            raise VRAMAllocatorError(f"unknown GPU device: {device_id}")

        assigned_device = self._model_to_device.get(model_name)
        if assigned_device is None:
            raise VRAMAllocatorError(f"model {model_name} is not assigned to a GPU device")
        if assigned_device != device_id:
            raise VRAMAllocatorError(
                f"model {model_name} is assigned to GPU {assigned_device}, not {device_id}"
            )

        if self._effective_free_mb(device_id, budget) < inference_vram_mb:
            return None

        allocation_id = f"{model_name}:inference:{self._next_inference_allocation_id}"
        self._next_inference_allocation_id += 1
        budget.inference_allocations[allocation_id] = inference_vram_mb
        self._inference_to_device[allocation_id] = device_id
        self._inference_to_model[allocation_id] = model_name
        return allocation_id
