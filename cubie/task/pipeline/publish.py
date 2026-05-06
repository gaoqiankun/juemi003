from __future__ import annotations

import inspect
from typing import Any

from structlog.contextvars import bound_contextvars

from cubie.core.observability.metrics import increment_task_total, observe_task_duration
from cubie.task.sequence import RequestSequence


class PublishMixin:
    async def publish_update(
        self,
        sequence: RequestSequence,
        event: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "status": sequence.status.value,
            "current_stage": sequence.current_stage,
            "progress": sequence.progress,
        }
        if metadata:
            payload.update(metadata)
        await self._task_store.update_task(sequence, event=event, metadata=payload)
        if event in {"succeeded", "failed", "cancelled"}:
            self.record_terminal_telemetry(sequence)
        for listener in self._listeners:
            maybe_awaitable = listener(sequence, event, payload)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

    def record_terminal_telemetry(self, sequence: RequestSequence) -> None:
        duration_seconds = 0.0
        if sequence.completed_at is not None:
            duration_seconds = max(
                (sequence.completed_at - sequence.created_at).total_seconds(),
                0.0,
            )
        observe_task_duration(
            status=sequence.status.value,
            duration_seconds=duration_seconds,
        )
        increment_task_total(status=sequence.status.value)
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.processing_finished",
                status=sequence.status.value,
                duration_seconds=round(duration_seconds, 6),
                failed_stage=sequence.failed_stage,
                error=sequence.error_message,
            )
