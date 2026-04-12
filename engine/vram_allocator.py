from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Iterable


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


class VRAMAllocator:
    _INFERENCE_WAIT_SECONDS = 0.01
    _EVICT_WAIT_WINDOW_SECONDS = 2.0

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
            if budget.free_vram_mb < required_mb:
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
        wait_window_start = asyncio.get_running_loop().time()
        evict_allowed = self._evict_callback is not None

        while True:
            allocation_id = self._try_acquire_inference(
                model_name=normalized_model,
                device_id=normalized_device,
                inference_vram_mb=required_mb,
            )
            if allocation_id is not None:
                return allocation_id

            elapsed = asyncio.get_running_loop().time() - wait_window_start
            if evict_allowed and elapsed >= self._EVICT_WAIT_WINDOW_SECONDS:
                evict_callback = self._evict_callback
                if evict_callback is None:
                    evict_allowed = False
                else:
                    evicted = await evict_callback(normalized_device, normalized_model)
                    if evicted:
                        allocation_id = self._try_acquire_inference(
                            model_name=normalized_model,
                            device_id=normalized_device,
                            inference_vram_mb=required_mb,
                        )
                        if allocation_id is not None:
                            return allocation_id
                        wait_window_start = asyncio.get_running_loop().time()
                        continue
                    evict_allowed = False
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
                "allocations": dict(budget.allocations),
                "inference_allocations": dict(budget.inference_allocations),
            }
        return result

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

        if budget.free_vram_mb < inference_vram_mb:
            return None

        allocation_id = f"{model_name}:inference:{self._next_inference_allocation_id}"
        self._next_inference_allocation_id += 1
        budget.inference_allocations[allocation_id] = inference_vram_mb
        self._inference_to_device[allocation_id] = device_id
        self._inference_to_model[allocation_id] = model_name
        return allocation_id
