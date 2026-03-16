from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar

T = TypeVar("T")

DEFAULT_CURSOR_PAGE_LIMIT = 20
MAX_CURSOR_PAGE_LIMIT = 50


def normalize_cursor_page_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_CURSOR_PAGE_LIMIT
    return max(1, min(int(limit), MAX_CURSOR_PAGE_LIMIT))


@dataclass(slots=True)
class CursorPageResult(Generic[T]):
    items: list[T] = field(default_factory=list)
    has_more: bool = False
    next_cursor: datetime | None = None
