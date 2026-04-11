from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Generic, Iterable, Protocol, TypeVar

from gen3d.observability.metrics import initialize_gpu_slots, set_gpu_slot_active
from gen3d.stages.gpu.worker import GPUWorkerHandle

T = TypeVar("T")


class FlowMatchingScheduler(Generic[T]):
    def __init__(self) -> None:
        self._waiting: deque[T] = deque()

    def enqueue(self, item: T) -> None:
        self._waiting.append(item)

    def size(self) -> int:
        return len(self._waiting)

    def drain(self) -> list[T]:
        items = list(self._waiting)
        self._waiting.clear()
        return items


@dataclass(slots=True)
class GPUSlot:
    device_id: str
    worker: GPUWorkerHandle


class _InferenceAllocatorProtocol(Protocol):
    async def acquire_inference(
        self,
        *,
        model_name: str,
        device_id: str,
        inference_vram_mb: int,
    ) -> str:
        ...

    def release_inference(self, allocation_id: str) -> None:
        ...


InferenceVRAMEstimator = Callable[[int, dict[str, Any]], int]


class GPUSlotScheduler:
    def __init__(
        self,
        workers: list[GPUWorkerHandle],
        disabled_device_ids: Iterable[str] | None = None,
    ) -> None:
        self._slots = {
            worker.device_id: GPUSlot(device_id=worker.device_id, worker=worker)
            for worker in workers
        }
        self._available: asyncio.Queue[str] = asyncio.Queue()
        self._disabled: set[str] = set()
        self._parked: set[str] = set()
        self._waiting_count = 0
        self._inference_allocator: _InferenceAllocatorProtocol | None = None
        self._inference_model_name: str | None = None
        self._inference_device_id: str | None = None
        self._estimate_inference_vram_mb: InferenceVRAMEstimator | None = None
        self._inference_allocations_by_device: dict[str, str] = {}
        for device_id in disabled_device_ids or ():
            normalized = str(device_id).strip()
            if normalized in self._slots:
                self._disabled.add(normalized)
        initialize_gpu_slots(tuple(self._slots))
        for device_id in self._slots:
            if device_id in self._disabled:
                self._parked.add(device_id)
                continue
            self._available.put_nowait(device_id)

    def configure_inference_admission(
        self,
        *,
        allocator: _InferenceAllocatorProtocol,
        model_name: str,
        device_id: str,
        estimate_inference_vram_mb: InferenceVRAMEstimator,
    ) -> None:
        normalized_device = str(device_id).strip()
        if normalized_device not in self._slots:
            raise ValueError(f"unknown scheduler device: {normalized_device}")
        normalized_model = str(model_name).strip().lower()
        if not normalized_model:
            raise ValueError("model_name must not be empty")
        self._inference_allocator = allocator
        self._inference_model_name = normalized_model
        self._inference_device_id = normalized_device
        self._estimate_inference_vram_mb = estimate_inference_vram_mb

    async def acquire(
        self,
        *,
        batch_size: int = 1,
        options: dict[str, Any] | None = None,
    ) -> GPUSlot:
        inference_allocation_id = await self._acquire_inference_allocation(
            batch_size=batch_size,
            options=options or {},
        )
        try:
            self._waiting_count += 1
            try:
                device_id = await self._available.get()
            finally:
                self._waiting_count = max(self._waiting_count - 1, 0)

            if inference_allocation_id is not None:
                self._inference_allocations_by_device[device_id] = inference_allocation_id
            set_gpu_slot_active(device=device_id, active=True)
            return self._slots[device_id]
        except Exception:
            if inference_allocation_id is not None and self._inference_allocator is not None:
                self._inference_allocator.release_inference(inference_allocation_id)
            raise

    async def release(self, device_id: str) -> None:
        inference_allocation_id = self._inference_allocations_by_device.pop(device_id, None)
        if inference_allocation_id is not None and self._inference_allocator is not None:
            self._inference_allocator.release_inference(inference_allocation_id)
        set_gpu_slot_active(device=device_id, active=False)
        if device_id in self._disabled:
            self._parked.add(device_id)
            return
        await self._available.put(device_id)

    def disable(self, device_id: str) -> None:
        normalized = str(device_id).strip()
        if normalized not in self._slots:
            return
        self._disabled.add(normalized)

        available_items: list[str] = []
        while True:
            try:
                available_items.append(self._available.get_nowait())
            except asyncio.QueueEmpty:
                break

        for available_device_id in available_items:
            if available_device_id in self._disabled:
                self._parked.add(available_device_id)
            else:
                self._available.put_nowait(available_device_id)

    def enable(self, device_id: str) -> None:
        normalized = str(device_id).strip()
        if normalized not in self._slots:
            return
        self._disabled.discard(normalized)
        if normalized in self._parked:
            self._parked.discard(normalized)
            self._available.put_nowait(normalized)

    def disabled_device_ids(self) -> frozenset[str]:
        return frozenset(self._disabled)

    def slot_count(self) -> int:
        return len(self._slots)

    def active_count(self) -> int:
        return max(self.slot_count() - self._available.qsize() - len(self._parked), 0)

    def waiting_count(self) -> int:
        return max(self._waiting_count, 0)

    def device_ids(self) -> tuple[str, ...]:
        return tuple(self._slots)

    async def _acquire_inference_allocation(
        self,
        *,
        batch_size: int,
        options: dict[str, Any],
    ) -> str | None:
        if (
            self._inference_allocator is None
            or self._inference_model_name is None
            or self._inference_device_id is None
            or self._estimate_inference_vram_mb is None
        ):
            return None

        normalized_batch_size = max(int(batch_size), 1)
        required_inference_vram_mb = self._estimate_inference_vram_mb(
            normalized_batch_size,
            options,
        )
        return await self._inference_allocator.acquire_inference(
            model_name=self._inference_model_name,
            device_id=self._inference_device_id,
            inference_vram_mb=required_inference_vram_mb,
        )
