from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import httpx

from gen3d.engine.pipeline import CancelRequestResult, PipelineCoordinator
from gen3d.engine.sequence import (
    RequestSequence,
    TERMINAL_STATUSES,
    TaskStatus,
    TaskType,
)
from gen3d.security import (
    TokenRateLimiter,
    validate_callback_url,
    validate_image_url,
)
from gen3d.storage.artifact_store import ArtifactStore
from gen3d.storage.task_store import TaskStore

WebhookSender = Callable[[str, dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class TaskCancelResult:
    outcome: str
    sequence: RequestSequence | None


class AsyncGen3DEngine:
    def __init__(
        self,
        *,
        task_store: TaskStore,
        pipeline: PipelineCoordinator,
        artifact_store: ArtifactStore | None = None,
        webhook_sender: WebhookSender | None = None,
        webhook_timeout_seconds: float = 2.0,
        provider_mode: str = "mock",
        allowed_callback_domains: tuple[str, ...] = (),
        rate_limiter: TokenRateLimiter | None = None,
    ) -> None:
        self._task_store = task_store
        self._pipeline = pipeline
        self._artifact_store = artifact_store
        self._started = False
        self._event_queues: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._webhook_sender = webhook_sender or self._default_webhook_sender
        self._webhook_timeout_seconds = webhook_timeout_seconds
        self._allow_local_inputs = provider_mode.strip().lower() == "mock"
        self._allowed_callback_domains = allowed_callback_domains
        self._rate_limiter = rate_limiter
        self._pipeline.add_listener(self._publish_update)

    async def start(self) -> None:
        if self._started:
            return
        await self._pipeline.start()
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        await self._pipeline.stop()
        self._started = False

    async def submit_task(
        self,
        *,
        task_type: TaskType,
        image_url: str,
        options: dict,
        callback_url: str | None = None,
        idempotency_key: str | None = None,
        api_token: str | None = None,
    ) -> tuple[RequestSequence, bool]:
        image_url = validate_image_url(
            image_url,
            allow_local_inputs=self._allow_local_inputs,
        )
        callback_url = validate_callback_url(
            callback_url,
            allowed_domains=self._allowed_callback_domains,
        )
        rate_limit_key = api_token or "anonymous"
        if self._rate_limiter is not None:
            await self._rate_limiter.record_request(rate_limit_key)
        if idempotency_key:
            existing = await self._task_store.get_task_by_idempotency_key(idempotency_key)
            if existing is not None:
                return existing, False
        if self._rate_limiter is not None:
            await self._rate_limiter.check_concurrent_tasks(rate_limit_key)

        sequence = RequestSequence.new_task(
            input_url=image_url,
            options=options,
            callback_url=callback_url,
            idempotency_key=idempotency_key,
            task_type=task_type,
        )
        await self._task_store.create_task(sequence)
        await self._pipeline.enqueue(sequence.task_id)
        if self._rate_limiter is not None:
            await self._rate_limiter.register_task(rate_limit_key, sequence.task_id)
        return sequence, True

    async def get_task(self, task_id: str) -> RequestSequence | None:
        sequence = await self._task_store.get_task(task_id)
        if sequence is None:
            return None
        if self._artifact_store is not None and not sequence.artifacts:
            sequence.artifacts = await self._artifact_store.list_artifacts(task_id)
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

    @property
    def ready(self) -> bool:
        return self._started

    async def stream_events(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._event_queues[task_id].add(queue)
        try:
            history = await self._task_store.list_task_events(task_id)
            for event_record in history:
                yield self._build_replayed_event_payload(task_id, event_record)

            current = await self.get_task(task_id)
            if current is not None and current.status in {
                TaskStatus.SUCCEEDED,
                TaskStatus.FAILED,
                TaskStatus.CANCELLED,
            }:
                return

            while True:
                payload = await queue.get()
                yield payload
                if payload["status"] in {
                    TaskStatus.SUCCEEDED.value,
                    TaskStatus.FAILED.value,
                    TaskStatus.CANCELLED.value,
                }:
                    break
        finally:
            subscribers = self._event_queues.get(task_id)
            if subscribers is not None:
                subscribers.discard(queue)
                if not subscribers:
                    self._event_queues.pop(task_id, None)

    async def _publish_update(
        self,
        sequence: RequestSequence,
        event: str,
        metadata: dict[str, Any],
    ) -> None:
        payload = self._build_event_payload(sequence, event, metadata)
        for queue in list(self._event_queues.get(sequence.task_id, ())):
            queue.put_nowait(payload)
        if self._rate_limiter is not None and sequence.status in TERMINAL_STATUSES:
            await self._rate_limiter.release_task(sequence.task_id)
        if (
            event in {"succeeded", "failed"}
            and sequence.callback_url
        ):
            await self._send_webhook(sequence)

    def _build_event_payload(
        self,
        sequence: RequestSequence,
        event: str,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "event": event,
            "taskId": sequence.task_id,
            "status": sequence.status.value,
            "progress": sequence.progress,
            "currentStage": sequence.current_stage,
            "metadata": metadata,
        }

    def _build_replayed_event_payload(
        self,
        task_id: str,
        event_record: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = event_record["metadata"]
        return {
            "event": event_record["event"],
            "taskId": task_id,
            "status": metadata.get("status"),
            "progress": metadata.get("progress"),
            "currentStage": metadata.get("current_stage"),
            "metadata": metadata,
        }

    async def _send_webhook(self, sequence: RequestSequence) -> None:
        payload = {
            "taskId": sequence.task_id,
            "status": sequence.status.value,
            "artifacts": sequence.artifacts,
            "error": (
                {
                    "message": sequence.error_message,
                    "failed_stage": sequence.failed_stage,
                }
                if sequence.error_message is not None
                else None
            ),
        }
        try:
            await self._webhook_sender(sequence.callback_url, payload)
        except Exception:
            return

    async def _default_webhook_sender(
        self,
        callback_url: str,
        payload: dict[str, Any],
    ) -> None:
        async with httpx.AsyncClient(timeout=self._webhook_timeout_seconds) as client:
            await client.post(callback_url, json=payload)
