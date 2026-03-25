from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import httpx
from gen3d.engine.sequence import RequestSequence

WebhookSender = Callable[[str, dict[str, Any]], Awaitable[None]]
SleepFn = Callable[[float], Awaitable[None]]


class TaskEventAppender(Protocol):
    async def __call__(
        self,
        task_id: str,
        *,
        event: str,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...


class WebhookResultRecorder(Protocol):
    def __call__(self, *, result: str) -> None: ...


def build_default_webhook_sender(timeout_seconds: float) -> WebhookSender:
    async def sender(callback_url: str, payload: dict[str, Any]) -> None:
        await default_webhook_sender(
            callback_url,
            payload,
            timeout_seconds=timeout_seconds,
        )

    return sender


async def default_webhook_sender(
    callback_url: str,
    payload: dict[str, Any],
    *,
    timeout_seconds: float,
) -> None:
    async with httpx.AsyncClient(timeout=timeout_seconds) as client:
        await client.post(callback_url, json=payload)


def build_webhook_payload(sequence: RequestSequence) -> dict[str, Any]:
    return {
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


def backoff_seconds(attempt: int) -> float:
    return float(2 ** (attempt - 1))


async def send_webhook_with_retries(
    *,
    sequence: RequestSequence,
    sender: WebhookSender,
    append_task_event: TaskEventAppender,
    record_result: WebhookResultRecorder,
    logger: Any,
    max_retries: int,
    sleep: SleepFn = asyncio.sleep,
) -> None:
    callback_url = sequence.callback_url
    if not callback_url:
        return
    retries = max(int(max_retries), 0)
    payload = build_webhook_payload(sequence)
    max_attempts = 1 + retries
    for attempt in range(1, max_attempts + 1):
        try:
            await sender(callback_url, payload)
        except Exception as exc:
            error_message = str(exc)
            record_result(result="failure")
            if attempt <= retries:
                delay_seconds = backoff_seconds(attempt)
                await append_task_event(
                    sequence.task_id,
                    event="webhook_retry",
                    metadata={
                        "status": sequence.status.value,
                        "current_stage": sequence.current_stage,
                        "callback_url": callback_url,
                        "attempt": attempt,
                        "max_retries": retries,
                        "delay_seconds": delay_seconds,
                        "error": error_message,
                    },
                )
                logger.warning(
                    "webhook.retry_scheduled",
                    callback_url=callback_url,
                    attempt=attempt,
                    max_retries=retries,
                    delay_seconds=delay_seconds,
                    error=error_message,
                )
                await sleep(delay_seconds)
                continue

            await append_task_event(
                sequence.task_id,
                event="webhook_failed",
                metadata={
                    "status": sequence.status.value,
                    "current_stage": sequence.current_stage,
                    "callback_url": callback_url,
                    "attempts": attempt,
                    "max_retries": retries,
                    "error": error_message,
                    "message": (
                        "webhook delivery failed after "
                        f"{attempt} attempts: {error_message}"
                    ),
                },
            )
            logger.warning(
                "webhook.delivery_failed",
                callback_url=callback_url,
                attempts=attempt,
                max_retries=retries,
                error=error_message,
            )
            return

        record_result(result="success")
        await append_task_event(
            sequence.task_id,
            event="webhook_delivered",
            metadata={
                "status": sequence.status.value,
                "current_stage": sequence.current_stage,
                "callback_url": callback_url,
                "attempt": attempt,
                "max_retries": retries,
            },
        )
        logger.info(
            "webhook.delivered",
            callback_url=callback_url,
            status=sequence.status.value,
            attempt=attempt,
            max_retries=retries,
        )
        return
