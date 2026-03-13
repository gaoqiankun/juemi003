from __future__ import annotations

from collections import deque
from typing import Generic, TypeVar

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
