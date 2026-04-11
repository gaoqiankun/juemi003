from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


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

    @property
    def used_vram_mb(self) -> int:
        return sum(self.allocations.values())

    @property
    def free_vram_mb(self) -> int:
        return max(self.total_vram_mb - self.reserved_vram_mb - self.used_vram_mb, 0)


class VRAMAllocatorError(RuntimeError):
    pass


class VRAMAllocator:
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

    @property
    def device_ids(self) -> tuple[str, ...]:
        return tuple(self._budgets.keys())

    def assignment_for(self, model_name: str) -> str | None:
        return self._model_to_device.get(_normalize_model_name(model_name))

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

    def snapshot(self) -> dict[str, dict[str, object]]:
        result: dict[str, dict[str, object]] = {}
        for device_id, budget in self._budgets.items():
            result[device_id] = {
                "total_vram_mb": budget.total_vram_mb,
                "reserved_vram_mb": budget.reserved_vram_mb,
                "free_vram_mb": budget.free_vram_mb,
                "allocations": dict(budget.allocations),
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
