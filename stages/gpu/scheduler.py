from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Generic, Iterable, TypeVar

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

    async def acquire(self) -> GPUSlot:
        self._waiting_count += 1
        device_id = await self._available.get()
        self._waiting_count -= 1
        set_gpu_slot_active(device=device_id, active=True)
        return self._slots[device_id]

    async def release(self, device_id: str) -> None:
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
