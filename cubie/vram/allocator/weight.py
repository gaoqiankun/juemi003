from __future__ import annotations

from cubie.vram.allocator import (
    ModelWorkerInterface,
    VRAMInsufficientError,
    WeightAllocation,
    WeightAllocationID,
    normalize_device_id,
    normalize_model_name,
    normalize_vram_mb,
)


class WeightMixin:
    async def request_weight(
        self,
        model_id: str,
        mb: int,
        exclude_device_ids: tuple[str, ...] = (),
    ) -> WeightAllocation:
        normalized_model = normalize_model_name(model_id)
        required_mb = normalize_vram_mb(mb)
        excluded = {
            normalized
            for raw in exclude_device_ids
            if (normalized := normalize_device_id(raw))
        }
        await self.startprobe_loop()
        async with self._lock:
            candidate_device_ids = tuple(
                device_id
                for device_id in self._budgets
                if device_id not in excluded
            )
            if not candidate_device_ids:
                raise VRAMInsufficientError("no allocatable GPU devices are available")

            for device_id in candidate_device_ids:
                allocation = self.try_book_weight(
                    model_id=normalized_model,
                    device_id=device_id,
                    required_mb=required_mb,
                )
                if allocation is not None:
                    return allocation

                idle_candidates = self.idle_candidates_on(
                    device_id=device_id,
                    exclude_model_id=normalized_model,
                )
                for candidate_model_name, candidate_worker in idle_candidates:
                    evicted = await self.evict_worker(
                        device_id=device_id,
                        requester_model_name=normalized_model,
                        candidate_model_name=candidate_model_name,
                        candidate_worker=candidate_worker,
                    )
                    if not evicted:
                        continue
                    allocation = self.try_book_weight(
                        model_id=normalized_model,
                        device_id=device_id,
                        required_mb=required_mb,
                    )
                    if allocation is not None:
                        return allocation

            free_by_device = {
                device_id: self.safe_free_mb(device_id)
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
        normalized_actual_mb = normalize_vram_mb(actual_mb)
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
        self._worker_registry[normalize_model_name(model_id)] = worker

    def unregister_worker(self, model_id: str) -> None:
        self._worker_registry.pop(normalize_model_name(model_id), None)
