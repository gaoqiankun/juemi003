from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from structlog.contextvars import bound_contextvars

from cubie.core.observability.metrics import set_queue_depth
from cubie.core.pagination import CursorPageResult
from cubie.core.security import validate_callback_url, validate_image_url
from cubie.task.engine import TaskCancelResult
from cubie.task.eta import decorate_sequence_eta
from cubie.task.events import (
    is_terminal_event_status,
    is_terminal_task_status,
    replay_event_payloads,
    subscribe_event_queue,
    unsubscribe_event_queue,
)
from cubie.task.pipeline import CancelRequestResult, PipelineQueueFullError
from cubie.task.sequence import RequestSequence, TaskType, utcnow
from cubie.task.store import TaskIdempotencyConflictError


class TasksMixin:
    async def submit_task(
        self,
        *,
        task_type: TaskType,
        image_url: str,
        options: dict,
        callback_url: str | None = None,
        idempotency_key: str | None = None,
        key_id: str | None = None,
        model: str = "trellis",
    ) -> tuple[RequestSequence, bool]:
        image_url = validate_image_url(
            image_url,
            allow_local_inputs=self._allow_local_inputs,
        )
        callback_url = validate_callback_url(
            callback_url,
            allowed_domains=self._allowed_callback_domains,
        )
        normalized_model = str(model).strip().lower() or "trellis"
        rate_limit_key = key_id or "anonymous"
        if self._rate_limiter is not None:
            await self._rate_limiter.record_request(rate_limit_key)
        if idempotency_key:
            existing = await self._task_store.get_task_by_idempotency_key(idempotency_key)
            if existing is not None:
                with bound_contextvars(task_id=existing.task_id):
                    self._logger.info(
                        "task.reused",
                        idempotency_key=idempotency_key,
                        status=existing.status.value,
                    )
                await self.decorate_sequence(existing)
                return existing, False
        if self._rate_limiter is not None:
            await self._rate_limiter.check_concurrent_tasks(rate_limit_key)
        if await self._task_store.count_incomplete_tasks() >= self._queue_capacity:
            raise PipelineQueueFullError("pipeline queue is full")

        sequence = RequestSequence.new_task(
            model=normalized_model,
            input_url=image_url,
            options=options,
            callback_url=callback_url,
            idempotency_key=idempotency_key,
            key_id=key_id,
            task_type=task_type,
        )
        try:
            await self._task_store.create_task(sequence)
        except TaskIdempotencyConflictError as exc:
            existing = exc.existing_sequence
            with bound_contextvars(task_id=existing.task_id):
                self._logger.info(
                    "task.reused_after_conflict",
                    idempotency_key=idempotency_key,
                    status=existing.status.value,
                )
            await self.decorate_sequence(existing)
            return existing, False
        if self._rate_limiter is not None:
            await self._rate_limiter.register_task(rate_limit_key, sequence.task_id)
        sequence.queue_position = await self._task_store.get_queue_position(sequence.task_id) or 1
        stage_stats = await self._task_store.get_stage_stats(sequence.model)
        decorate_sequence_eta(
            sequence,
            worker_count=self._worker_count,
            queue_position=sequence.queue_position,
            stage_stats=stage_stats,
            now=utcnow(),
        )
        set_queue_depth(await self._task_store.count_queued_tasks())
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info(
                "task.submitted",
                task_type=task_type.value,
                callback_enabled=bool(callback_url),
                idempotency_key=idempotency_key,
                key_id=key_id,
                model=sequence.model,
            )
        return sequence, True

    def update_queue_capacity(self, queue_max_size: int) -> None:
        self._queue_capacity = self._worker_count + max(int(queue_max_size), 0)

    async def list_tasks(
        self,
        *,
        key_id: str | None,
        limit: int = 20,
        before=None,
    ) -> CursorPageResult[RequestSequence]:
        page = await self._task_store.list_tasks(
            key_id=key_id,
            limit=limit,
            before=before,
        )
        for sequence in page.items:
            await self.decorate_sequence(sequence)
        return page

    async def delete_task(self, task_id: str) -> RequestSequence | None:
        sequence = await self._task_store.get_task(task_id)
        if sequence is None:
            return None
        deleted = await self._task_store.soft_delete_task(task_id, deleted_at=utcnow())
        if not deleted:
            return None
        self._cleanup_event.set()
        return sequence

    async def get_task(self, task_id: str) -> RequestSequence | None:
        sequence = await self._task_store.get_task(task_id)
        if sequence is None:
            return None
        await self.decorate_sequence(sequence)
        return sequence

    async def get_artifacts(self, task_id: str) -> list[dict[str, Any]] | None:
        sequence = await self.get_task(task_id)
        if sequence is None:
            return None
        if sequence.artifacts:
            return sequence.artifacts
        if self._artifact_store is None:
            return []
        return await self._artifact_store.list_artifacts(task_id)

    async def cancel_task(self, task_id: str) -> TaskCancelResult:
        result: CancelRequestResult = await self._pipeline.cancel_task(task_id)
        return TaskCancelResult(outcome=result.outcome, sequence=result.sequence)

    async def stream_events(
        self,
        task_id: str,
        *,
        heartbeat_interval: float = 15.0,
    ) -> AsyncIterator[dict[str, Any] | None]:
        """Yield event payloads for the given task.

        Yields ``None`` as a heartbeat sentinel every *heartbeat_interval*
        seconds when no real event arrives.  Callers must filter out ``None``
        values and treat them as keep-alive signals (e.g. send an SSE comment).
        This prevents reverse-proxy idle-timeout disconnections during long
        inference gaps (e.g. between GPU_SS and GPU_SHAPE).
        """
        queue = subscribe_event_queue(self._event_queues, task_id)
        try:
            history = await self._task_store.list_task_events(task_id)
            for replayed_payload in replay_event_payloads(
                task_id=task_id,
                history=history,
            ):
                yield replayed_payload
            current = await self._task_store.get_task(task_id)
            if current is not None and is_terminal_task_status(current.status):
                return
            while True:
                try:
                    payload = await asyncio.wait_for(
                        queue.get(),
                        timeout=heartbeat_interval,
                    )
                except asyncio.TimeoutError:
                    yield None  # heartbeat - no event within interval
                    continue
                yield payload
                if is_terminal_event_status(payload.get("status")):
                    break
        finally:
            unsubscribe_event_queue(self._event_queues, task_id=task_id, queue=queue)
