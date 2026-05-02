from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Iterable, Iterator
from typing import Any

from gen3d.task.sequence import RequestSequence, TaskStatus

EventPayload = dict[str, Any]
EventQueue = asyncio.Queue[EventPayload]
TaskEventQueues = defaultdict[str, set[EventQueue]]

_TERMINAL_EVENT_STATUSES = frozenset(
    {
        TaskStatus.SUCCEEDED.value,
        TaskStatus.FAILED.value,
        TaskStatus.CANCELLED.value,
    }
)


def build_event_queues() -> TaskEventQueues:
    return defaultdict(set)


def subscribe_event_queue(event_queues: TaskEventQueues, task_id: str) -> EventQueue:
    queue: EventQueue = asyncio.Queue()
    event_queues[task_id].add(queue)
    return queue


def unsubscribe_event_queue(
    event_queues: TaskEventQueues,
    *,
    task_id: str,
    queue: EventQueue,
) -> None:
    subscribers = event_queues.get(task_id)
    if subscribers is None:
        return
    subscribers.discard(queue)
    if not subscribers:
        event_queues.pop(task_id, None)


def publish_event(
    event_queues: TaskEventQueues,
    *,
    task_id: str,
    payload: EventPayload,
) -> None:
    for subscriber_queue in list(event_queues.get(task_id, ())):
        subscriber_queue.put_nowait(payload)


def replay_event_payloads(
    *,
    task_id: str,
    history: Iterable[dict[str, Any]],
) -> Iterator[EventPayload]:
    for event_record in history:
        yield build_replayed_event_payload(task_id=task_id, event_record=event_record)


def build_event_payload(
    sequence: RequestSequence,
    *,
    event: str,
    metadata: dict[str, Any],
) -> EventPayload:
    return {
        "event": event,
        "taskId": sequence.task_id,
        "status": sequence.status.value,
        "progress": sequence.progress,
        "currentStage": sequence.current_stage,
        "metadata": metadata,
    }


def build_replayed_event_payload(
    *,
    task_id: str,
    event_record: dict[str, Any],
) -> EventPayload:
    metadata = event_record["metadata"]
    return {
        "event": event_record["event"],
        "taskId": task_id,
        "status": metadata.get("status"),
        "progress": metadata.get("progress"),
        "currentStage": metadata.get("current_stage"),
        "metadata": metadata,
    }


def is_terminal_event_status(status: str | None) -> bool:
    return status in _TERMINAL_EVENT_STATUSES


def is_terminal_task_status(status: TaskStatus | None) -> bool:
    return status is not None and status.value in _TERMINAL_EVENT_STATUSES
