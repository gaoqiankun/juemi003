from __future__ import annotations

import asyncio
from typing import Iterable

from cubie.vram.allocator import (
    InferenceAllocation,
    InferenceAllocationID,
    VRAMAllocatorError,
    WeightAllocation,
    WeightAllocationID,
    normalize_device_id,
    normalize_model_name,
    normalize_vram_mb,
)


class BookingMixin:
    # deprecated
    def reserve(
        self,
        *,
        model_name: str,
        weight_vram_mb: int,
        allowed_device_ids: Iterable[str] | None = None,
        preferred_device_id: str | None = None,
    ) -> str:
        normalized_model = normalize_model_name(model_name)
        required_mb = normalize_vram_mb(weight_vram_mb)
        candidate_ids = self.resolve_candidate_ids(
            allowed_device_ids=allowed_device_ids,
            preferred_device_id=preferred_device_id,
        )
        for device_id in candidate_ids:
            allocation = self.try_book_weight(
                model_id=normalized_model,
                device_id=device_id,
                required_mb=required_mb,
            )
            if allocation is not None:
                return allocation.device_id
        free_by_device = {
            device_id: self.safe_free_mb(device_id)
            for device_id in candidate_ids
        }
        raise VRAMAllocatorError(
            "insufficient VRAM to place model "
            f"{normalized_model}: requires {required_mb} MB "
            f"(free_by_device={free_by_device})"
        )

    # deprecated
    def release(self, model_name: str) -> None:
        normalized_model = normalize_model_name(model_name)
        allocation_id = self._model_to_weight_alloc.get(normalized_model)
        if allocation_id is not None:
            self.release_weight(WeightAllocationID(allocation_id))
        for inference_id, allocated_model in tuple(self._inference_to_model.items()):
            if allocated_model != normalized_model:
                continue
            self.release_inference(inference_id)

    def try_book_weight(
        self,
        *,
        model_id: str,
        device_id: str,
        required_mb: int,
    ) -> WeightAllocation | None:
        normalized_device = normalize_device_id(device_id)
        if normalized_device not in self._budgets:
            raise VRAMAllocatorError(f"unknown GPU device: {normalized_device}")
        if self.safe_free_mb(normalized_device) < required_mb:
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

    def try_book_inference(
        self,
        *,
        model_id: str,
        device_id: str,
        required_mb: int,
    ) -> InferenceAllocationID | None:
        normalized_device = normalize_device_id(device_id)
        if normalized_device not in self._budgets:
            raise VRAMAllocatorError(f"unknown GPU device: {normalized_device}")
        if self.safe_free_mb(normalized_device) < required_mb:
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

    async def try_book_migration(
        self,
        *,
        model_id: str,
        device_id: str,
        required_inference_mb: int,
        required_weight_mb: int,
    ) -> tuple[InferenceAllocationID, WeightAllocationID] | None:
        total_required_mb = required_inference_mb + required_weight_mb
        if self.safe_free_mb(device_id) < total_required_mb:
            idle_candidates = self.idle_candidates_on(
                device_id=device_id,
                exclude_model_id=model_id,
            )
            for candidate_model_name, candidate_worker in idle_candidates:
                evicted = await self.evict_worker(
                    device_id=device_id,
                    requester_model_name=model_id,
                    candidate_model_name=candidate_model_name,
                    candidate_worker=candidate_worker,
                )
                if not evicted:
                    continue
                if self.safe_free_mb(device_id) >= total_required_mb:
                    break

        if self.safe_free_mb(device_id) < total_required_mb:
            return None

        weight_allocation = self.try_book_weight(
            model_id=model_id,
            device_id=device_id,
            required_mb=required_weight_mb,
        )
        if weight_allocation is None:
            return None
        inference_allocation = self.try_book_inference(
            model_id=model_id,
            device_id=device_id,
            required_mb=required_inference_mb,
        )
        if inference_allocation is None:
            self.release_weight(weight_allocation.allocation_id)
            return None
        return inference_allocation, weight_allocation.allocation_id

    async def _attempt_cross_device_migration(
        self,
        *,
        normalized_model: str,
        normalized_device: str,
        required_inference_mb: int,
        required_weight_mb: int,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[InferenceAllocation | None, float]:
        for candidate_device_id in self._budgets:
            if candidate_device_id == normalized_device:
                continue
            migration = await self.try_book_migration(
                model_id=normalized_model,
                device_id=candidate_device_id,
                required_inference_mb=required_inference_mb,
                required_weight_mb=required_weight_mb,
            )
            if migration is None:
                continue
            inference_allocation_id, weight_allocation_id = migration
            return (
                InferenceAllocation(
                    inference_allocation_id=inference_allocation_id,
                    weight_allocation_id=weight_allocation_id,
                    device_id=candidate_device_id,
                ),
                loop.time(),
            )
        return None, loop.time()
