from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from cubie.model import ModelRegistry
from cubie.stage import BaseStage
from cubie.task import RequestSequence, TaskStore
from cubie.vram import VRAMAllocator

PipelineListener = Callable[
    [RequestSequence, str, dict[str, Any]],
    Awaitable[None] | None,
]


@dataclass(slots=True)
class CancelRequestResult:
    outcome: str
    sequence: RequestSequence | None


class PipelineQueueFullError(RuntimeError):
    pass


@dataclass(slots=True)
class RecoverySummary:
    scanned: int = 0
    requeued: int = 0
    failed_interrupted: int = 0
    failed_timeout: int = 0


def looks_like_oom(error: BaseException) -> bool:
    message = str(error).lower()
    return "out of memory" in message or "cuda oom" in message or "cuda out of memory" in message


from .execution import ExecutionMixin  # noqa: E402
from .gpu_stage import GPUStageMixin  # noqa: E402
from .lifecycle import LifecycleMixin  # noqa: E402
from .publish import PublishMixin  # noqa: E402
from .recovery import RecoveryMixin  # noqa: E402

__all__ = (
    "CancelRequestResult",
    "PipelineCoordinator",
    "PipelineListener",
    "PipelineQueueFullError",
    "RecoverySummary",
    "looks_like_oom",
)


class PipelineCoordinator(
    LifecycleMixin,
    ExecutionMixin,
    GPUStageMixin,
    PublishMixin,
    RecoveryMixin,
):
    def __init__(
        self,
        task_store: TaskStore,
        stages: list[BaseStage],
        *,
        inference_allocator: VRAMAllocator | None = None,
        model_registry: ModelRegistry | None = None,
        task_timeout_seconds: int = 3600,
        queue_max_size: int = 20,
        worker_count: int = 1,
    ) -> None:
        self._task_store = task_store
        self._stages = stages
        self._inference_allocator = inference_allocator
        self._model_registry = model_registry
        self._listeners: list[PipelineListener] = []
        self._logger = structlog.get_logger(__name__)
        self._task_timeout_seconds = max(int(task_timeout_seconds), 1)
        self._worker_count = max(int(worker_count), 1)
        self._queue_max_size = max(int(queue_max_size), 0)
        self._started = False
