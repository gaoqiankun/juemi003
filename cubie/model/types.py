from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cubie.model.base import BaseModelProvider
    from cubie.model.gpu import GPUSlotScheduler, GPUWorkerHandle

__all__ = ("ModelRegistryLoadError", "ModelRuntime")


@dataclass(slots=True)
class ModelRuntime:
    model_name: str
    provider: BaseModelProvider
    workers: list[GPUWorkerHandle]
    scheduler: GPUSlotScheduler
    assigned_device_id: str | None = None
    weight_vram_mb: int | None = None


class ModelRegistryLoadError(RuntimeError):
    pass


@dataclass(slots=True)
class _ModelEntry:
    state: str = "not_loaded"
    event: asyncio.Event = field(default_factory=asyncio.Event)
    worker: Any | None = None
    error: Exception | None = None
    load_task: asyncio.Task[None] | None = None
    requested_device_id: str | None = None
    excluded_device_ids: tuple[str, ...] = ()


def normalize_name(model_name: str) -> str:
    return str(model_name).strip().lower()


def reset_entry(entry: _ModelEntry) -> None:
    entry.error = None
    entry.state = "not_loaded"
    entry.event = asyncio.Event()
    entry.load_task = None
    entry.requested_device_id = None
    entry.excluded_device_ids = ()
