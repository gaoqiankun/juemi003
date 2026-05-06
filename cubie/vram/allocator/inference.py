from __future__ import annotations

import asyncio
from typing import Iterable

from cubie.vram.allocator import (
    InferenceAllocation,
    InferenceAllocationID,
    InferenceLease,
    InternalVRAMContentionTimeoutError,
    VRAMAllocatorError,
    VRAMInsufficientError,
    normalize_device_id,
    normalize_model_name,
    normalize_vram_mb,
)


class InferenceMixin:
    async def request_inference(
        self,
        model_id: str,
        device_id: str,
        inference_mb: int,
        weight_mb: int,
    ) -> InferenceAllocation:
        normalized_model = normalize_model_name(model_id)
        normalized_device = normalize_device_id(device_id)
        required_inference_mb = normalize_vram_mb(inference_mb)
        required_weight_mb = normalize_vram_mb(weight_mb)
        await self.startprobe_loop()
        loop = asyncio.get_running_loop()
        wait_started_at: float | None = None

        async with self._lock:
            normalized_device = self._resolve_assigned_device_for_inference(
                normalized_model=normalized_model,
                requested_device=normalized_device,
            )

            # Reset stale external baseline accumulated during the previous export window.
            # The probe is suspended while inference is active (used_inference_vram_mb > 0),
            # so any prior baseline would persist unchanged and inflate the "external" display.
            self._external_baselines[normalized_device] = 0

            allocation, wait_started_at, evict_succeeded, acquired_at = (
                await self._attempt_local_book_with_eviction(
                    normalized_model=normalized_model,
                    normalized_device=normalized_device,
                    required_inference_mb=required_inference_mb,
                    wait_started_at=wait_started_at,
                    loop=loop,
                )
            )
            if allocation is not None:
                outcome = "after_evict" if evict_succeeded else self.resolve_success_outcome(
                    evict_succeeded=evict_succeeded,
                    waited=wait_started_at is not None,
                )
                self.emit_acquire_result(
                    device_id=normalized_device,
                    outcome=outcome,
                    wait_seconds=self.wait_seconds(
                        started_at=wait_started_at,
                        now=acquired_at,
                    ),
                )
                return allocation

            migration, migrated_at = await self._attempt_cross_device_migration(
                normalized_model=normalized_model,
                normalized_device=normalized_device,
                required_inference_mb=required_inference_mb,
                required_weight_mb=required_weight_mb,
                loop=loop,
            )
            if migration is not None:
                self.emit_acquire_result(
                    device_id=normalized_device,
                    outcome="migrated",
                    wait_seconds=self.wait_seconds(
                        started_at=wait_started_at,
                        now=migrated_at,
                    ),
                )
                return migration

            self.emit_acquire_result(
                device_id=normalized_device,
                outcome="timeout_internal",
                wait_seconds=self.wait_seconds(
                    started_at=wait_started_at,
                    now=loop.time(),
                ),
            )
            free_by_device = {
                candidate_device: self.safe_free_mb(candidate_device)
                for candidate_device in self._budgets
            }
            raise VRAMInsufficientError(
                "insufficient VRAM for inference "
                f"(model={normalized_model}, device={normalized_device}, "
                f"required_inference_mb={required_inference_mb}, "
                f"required_weight_mb={required_weight_mb}, "
                f"free_by_device={free_by_device})"
            )

    def _resolve_assigned_device_for_inference(
        self,
        *,
        normalized_model: str,
        requested_device: str,
    ) -> str:
        current_weight_allocation = self._model_to_weight_alloc.get(normalized_model)
        if current_weight_allocation is None:
            raise VRAMAllocatorError(f"model {normalized_model} is not assigned to a GPU device")
        assigned_device = self._weight_alloc_to_device.get(current_weight_allocation)
        if assigned_device is None:
            raise VRAMAllocatorError(
                f"model {normalized_model} has dangling allocation {current_weight_allocation}"
            )
        if requested_device != assigned_device:
            return assigned_device
        return requested_device

    async def _attempt_local_book_with_eviction(
        self,
        *,
        normalized_model: str,
        normalized_device: str,
        required_inference_mb: int,
        wait_started_at: float | None,
        loop: asyncio.AbstractEventLoop,
    ) -> tuple[InferenceAllocation | None, float | None, bool, float]:
        wait_deadline = loop.time() + self._MIGRATION_WAIT_SECONDS
        evict_succeeded = False
        while True:
            inference_allocation_id = self.try_book_inference(
                model_id=normalized_model,
                device_id=normalized_device,
                required_mb=required_inference_mb,
            )
            if inference_allocation_id is not None:
                return (
                    InferenceAllocation(
                        inference_allocation_id=inference_allocation_id,
                        weight_allocation_id=None,
                        device_id=normalized_device,
                    ),
                    wait_started_at,
                    evict_succeeded,
                    loop.time(),
                )

            inference_allocation_id, evicted = await self._try_book_after_idle_evictions(
                normalized_model=normalized_model,
                normalized_device=normalized_device,
                required_inference_mb=required_inference_mb,
            )
            if evicted:
                evict_succeeded = True
            if inference_allocation_id is not None:
                return (
                    InferenceAllocation(
                        inference_allocation_id=inference_allocation_id,
                        weight_allocation_id=None,
                        device_id=normalized_device,
                    ),
                    wait_started_at,
                    evict_succeeded,
                    loop.time(),
                )

            now = loop.time()
            if now >= wait_deadline:
                return None, wait_started_at, evict_succeeded, now
            if wait_started_at is None:
                wait_started_at = now
            await asyncio.sleep(self._INFERENCE_WAIT_SECONDS)

    async def _try_book_after_idle_evictions(
        self,
        *,
        normalized_model: str,
        normalized_device: str,
        required_inference_mb: int,
    ) -> tuple[InferenceAllocationID | None, bool]:
        evict_succeeded = False
        idle_candidates = self.idle_candidates_on(
            device_id=normalized_device,
            exclude_model_id=normalized_model,
        )
        for candidate_model_name, candidate_worker in idle_candidates:
            evicted = await self.evict_worker(
                device_id=normalized_device,
                requester_model_name=normalized_model,
                candidate_model_name=candidate_model_name,
                candidate_worker=candidate_worker,
            )
            if not evicted:
                continue
            evict_succeeded = True
            inference_allocation_id = self.try_book_inference(
                model_id=normalized_model,
                device_id=normalized_device,
                required_mb=required_inference_mb,
            )
            if inference_allocation_id is not None:
                return inference_allocation_id, evict_succeeded
        return None, evict_succeeded

    def reserve_for_task(
        self,
        *,
        model_id: str,
        estimate_mb: int,
        weight_mb: int,
    ) -> InferenceLease:
        normalized_model = normalize_model_name(model_id)
        assigned_device = self.assignment_for(normalized_model)
        if assigned_device is None:
            raise VRAMAllocatorError(f"model {normalized_model} is not assigned to a GPU device")
        return InferenceLease(
            allocator=self,
            model_id=normalized_model,
            device_id=assigned_device,
            estimate_mb=estimate_mb,
            weight_mb=weight_mb,
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

    async def acquire_inference(
        self,
        *,
        model_name: str,
        device_id: str,
        inference_vram_mb: int,
    ) -> str:
        normalized_model = normalize_model_name(model_name)
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

    def resolve_candidate_ids(
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
                if (device_id := normalize_device_id(raw_device_id)) in self._budgets
            )
        if not allowed:
            raise VRAMAllocatorError("no allocatable GPU devices are available")

        if preferred_device_id is None:
            return allowed

        preferred = normalize_device_id(preferred_device_id)
        if preferred not in self._budgets:
            raise VRAMAllocatorError(f"preferred GPU device is unknown: {preferred}")
        if preferred not in set(allowed):
            raise VRAMAllocatorError(f"preferred GPU device is not allocatable: {preferred}")
        return (preferred,)
