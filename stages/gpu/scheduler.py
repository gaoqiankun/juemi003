from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from typing import Generic, TypeVar

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
    def __init__(self, workers: list[GPUWorkerHandle]) -> None:
        self._slots = {
            worker.device_id: GPUSlot(device_id=worker.device_id, worker=worker)
            for worker in workers
        }
        self._available: asyncio.Queue[str] = asyncio.Queue()
        self._waiting_count = 0
        initialize_gpu_slots(tuple(self._slots))
        for device_id in self._slots:
            self._available.put_nowait(device_id)

    async def acquire(self) -> GPUSlot:
        self._waiting_count += 1
        device_id = await self._available.get()
        self._waiting_count -= 1
        set_gpu_slot_active(device=device_id, active=True)
        return self._slots[device_id]

    async def release(self, device_id: str) -> None:
        set_gpu_slot_active(device=device_id, active=False)
        await self._available.put(device_id)

    def slot_count(self) -> int:
        return len(self._slots)

    def active_count(self) -> int:
        return self.slot_count() - self._available.qsize()

    def waiting_count(self) -> int:
        return max(self._waiting_count, 0)

    def device_ids(self) -> tuple[str, ...]:
        return tuple(self._slots)
