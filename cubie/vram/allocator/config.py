from __future__ import annotations

import asyncio
from typing import Callable

from cubie.vram.allocator import (
    EvictionListener,
    VRAMAllocatorError,
    VRAMMetricsHook,
    VRAMProbe,
    normalize_device_id,
    normalize_model_name,
)


class ConfigMixin:
    @property
    def device_ids(self) -> tuple[str, ...]:
        return tuple(self._budgets.keys())

    def assignment_for(self, model_name: str) -> str | None:
        normalized_model = normalize_model_name(model_name)
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

    def add_eviction_listener(self, listener: EvictionListener) -> None:
        self._eviction_listeners.append(listener)

    def set_vram_probe(self, probe: VRAMProbe | None) -> None:
        """Inject runtime per-device free VRAM probe (MB). None disables probing."""
        self._vram_probe = probe
        if probe is None:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return
            loop.create_task(self.stopprobe_loop())

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
        normalized_device = normalize_device_id(device_id)
        if normalized_device not in self._budgets:
            return frozenset()
        return frozenset(
            model_name
            for allocation_id, inference_device_id in self._inference_to_device.items()
            if inference_device_id == normalized_device
            and (model_name := self._inference_to_model.get(allocation_id)) is not None
        )

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
                "safe_free_vram_mb": self.safe_free_mb(device_id),
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

    def safe_free_mb(self, device_id: str) -> int:
        normalized_device = normalize_device_id(device_id)
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
