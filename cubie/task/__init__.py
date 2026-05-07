from __future__ import annotations

from typing import TYPE_CHECKING, Any

from cubie.task.eta import PROCESSING_STATUSES, decorate_sequence_eta
from cubie.task.events import (
    EventQueue,
    TaskEventQueues,
    build_event_payload,
    build_event_queues,
    is_terminal_event_status,
    is_terminal_task_status,
    publish_event,
    replay_event_payloads,
    subscribe_event_queue,
    unsubscribe_event_queue,
)
from cubie.task.sequence import (
    DEFAULT_PROGRESS_BY_STATUS,
    TERMINAL_STATUSES,
    RequestSequence,
    TaskStatus,
    TaskType,
    utcnow,
)
from cubie.task.webhook import (
    WebhookSender,
    build_default_webhook_sender,
    send_webhook_with_retries,
)

if TYPE_CHECKING:
    from cubie.task.engine import AsyncGen3DEngine, TaskCancelResult
    from cubie.task.pipeline import (
        CancelRequestResult,
        PipelineCoordinator,
        PipelineQueueFullError,
        RecoverySummary,
    )
    from cubie.task.store import (
        TaskIdempotencyConflictError,
        TaskStore,
        serialize_datetime,
    )

__all__ = (
    "AsyncGen3DEngine",
    "CancelRequestResult",
    "DEFAULT_PROGRESS_BY_STATUS",
    "EventQueue",
    "PROCESSING_STATUSES",
    "PipelineCoordinator",
    "PipelineQueueFullError",
    "RecoverySummary",
    "RequestSequence",
    "TERMINAL_STATUSES",
    "TaskCancelResult",
    "TaskEventQueues",
    "TaskIdempotencyConflictError",
    "TaskStatus",
    "TaskStore",
    "TaskType",
    "WebhookSender",
    "build_default_webhook_sender",
    "build_event_payload",
    "build_event_queues",
    "decorate_sequence_eta",
    "is_terminal_event_status",
    "is_terminal_task_status",
    "publish_event",
    "replay_event_payloads",
    "send_webhook_with_retries",
    "serialize_datetime",
    "subscribe_event_queue",
    "unsubscribe_event_queue",
    "utcnow",
)


_LAZY_ATTRS = {
    "AsyncGen3DEngine": ("cubie.task.engine", "AsyncGen3DEngine"),
    "CancelRequestResult": ("cubie.task.pipeline", "CancelRequestResult"),
    "TaskCancelResult": ("cubie.task.engine", "TaskCancelResult"),
    "TaskIdempotencyConflictError": (
        "cubie.task.store",
        "TaskIdempotencyConflictError",
    ),
    "PipelineCoordinator": ("cubie.task.pipeline", "PipelineCoordinator"),
    "PipelineQueueFullError": ("cubie.task.pipeline", "PipelineQueueFullError"),
    "RecoverySummary": ("cubie.task.pipeline", "RecoverySummary"),
    "TaskStore": ("cubie.task.store", "TaskStore"),
    "serialize_datetime": ("cubie.task.store", "serialize_datetime"),
}


def __getattr__(name: str) -> Any:
    target = _LAZY_ATTRS.get(name)
    if target is None:
        raise AttributeError(f"module 'cubie.task' has no attribute {name!r}")
    module_name, attr_name = target
    from importlib import import_module

    module = import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
