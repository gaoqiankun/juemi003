from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any, Callable

import aiosqlite
from gen3d.engine.sequence import RequestSequence, TaskStatus, utcnow
from gen3d.storage.task_store_codec import serialize_datetime


class TaskIdempotencyConflictError(RuntimeError):
    def __init__(self, existing_sequence: RequestSequence) -> None:
        super().__init__(
            f"idempotency key already exists for task {existing_sequence.task_id}"
        )
        self.existing_sequence = existing_sequence


_TASK_COLUMNS = (
    "status",
    "type",
    "model",
    "input_url",
    "options_json",
    "idempotency_key",
    "key_id",
    "callback_url",
    "output_artifacts_json",
    "error_message",
    "failed_stage",
    "retry_count",
    "assigned_worker_id",
    "current_stage",
    "progress",
    "queue_position",
    "estimated_wait_seconds",
    "estimated_finish_at",
    "created_at",
    "queued_at",
    "started_at",
    "completed_at",
    "updated_at",
    "deleted_at",
)


def serialize_task_columns(sequence: RequestSequence) -> tuple:
    return (
        sequence.status.value,
        sequence.task_type.value,
        sequence.model,
        sequence.input_url,
        json.dumps(sequence.options),
        sequence.idempotency_key,
        sequence.key_id,
        sequence.callback_url,
        json.dumps(sequence.artifacts),
        sequence.error_message,
        sequence.failed_stage,
        sequence.retry_count,
        sequence.assigned_worker_id,
        sequence.current_stage,
        sequence.progress,
        sequence.queue_position,
        sequence.estimated_wait_seconds,
        serialize_datetime(sequence.estimated_finish_at),
        serialize_datetime(sequence.created_at),
        serialize_datetime(sequence.queued_at),
        serialize_datetime(sequence.started_at),
        serialize_datetime(sequence.completed_at),
        serialize_datetime(sequence.updated_at),
        serialize_datetime(sequence.deleted_at),
    )


async def create_task(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    sequence: RequestSequence,
    *,
    row_to_sequence: Callable[[aiosqlite.Row], RequestSequence],
) -> None:
    columns_sql = ", ".join(("id", *_TASK_COLUMNS))
    placeholders = ", ".join(["?"] * (len(_TASK_COLUMNS) + 1))
    async with lock:
        try:
            await db.execute(
                f"INSERT INTO tasks ({columns_sql}) VALUES ({placeholders})",
                (sequence.task_id, *serialize_task_columns(sequence)),
            )
        except aiosqlite.IntegrityError as exc:
            await raise_idempotency_conflict_or_passthrough(
                db, exc, sequence, row_to_sequence,
            )
        await insert_task_event(
            db,
            task_id=sequence.task_id,
            event="submitted",
            metadata={
                "status": sequence.status.value,
                "current_stage": sequence.current_stage,
                "progress": sequence.progress,
            },
            created_at=sequence.created_at,
        )
        await db.commit()


async def raise_idempotency_conflict_or_passthrough(
    db: aiosqlite.Connection,
    exc: aiosqlite.IntegrityError,
    sequence: RequestSequence,
    row_to_sequence: Callable[[aiosqlite.Row], RequestSequence],
) -> None:
    conflict_text = str(exc).lower()
    if not sequence.idempotency_key or "idempotency_key" not in conflict_text:
        raise exc
    async with db.execute(
        "SELECT * FROM tasks WHERE idempotency_key = ?",
        (sequence.idempotency_key,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        raise exc
    raise TaskIdempotencyConflictError(row_to_sequence(row)) from exc


async def update_task(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    sequence: RequestSequence,
    *,
    event: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    set_clause = ", ".join(f"{column} = ?" for column in _TASK_COLUMNS)
    async with lock:
        await db.execute(
            f"UPDATE tasks SET {set_clause} WHERE id = ?",
            (*serialize_task_columns(sequence), sequence.task_id),
        )
        if event is not None:
            await insert_task_event(
                db,
                task_id=sequence.task_id,
                event=event,
                metadata=metadata or {},
                created_at=sequence.updated_at,
            )
        await db.commit()


async def append_task_event(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    task_id: str,
    *,
    event: str,
    metadata: dict[str, Any] | None = None,
    created_at: datetime | None = None,
) -> None:
    async with lock:
        await insert_task_event(
            db,
            task_id=task_id,
            event=event,
            metadata=metadata or {},
            created_at=created_at,
        )
        await db.commit()


async def requeue_task(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    task_id: str,
) -> bool:
    async with lock:
        now = serialize_datetime(utcnow())
        async with db.execute(
            """
            UPDATE tasks
            SET status = ?,
                current_stage = ?,
                progress = ?,
                assigned_worker_id = NULL,
                started_at = NULL,
                queue_position = NULL,
                estimated_wait_seconds = NULL,
                estimated_finish_at = NULL,
                error_message = NULL,
                failed_stage = NULL,
                updated_at = ?
            WHERE id = ?
              AND deleted_at IS NULL
            """,
            (
                TaskStatus.QUEUED.value,
                TaskStatus.QUEUED.value,
                0,
                now,
                task_id,
            ),
        ) as cursor:
            was_updated = cursor.rowcount > 0
        await db.commit()
        return was_updated


async def delete_task(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    task_id: str,
) -> None:
    async with lock:
        await db.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
        await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await db.commit()


async def soft_delete_task(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    task_id: str,
    *,
    deleted_at: datetime | None = None,
) -> bool:
    async with lock:
        async with db.execute(
            """
            UPDATE tasks
            SET deleted_at = ?, cleanup_done = 0, updated_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                serialize_datetime(deleted_at or utcnow()),
                serialize_datetime(utcnow()),
                task_id,
            ),
        ) as cursor:
            was_deleted = cursor.rowcount > 0
        await db.commit()
        return was_deleted


async def mark_cleanup_done(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    task_id: str,
) -> bool:
    async with lock:
        async with db.execute(
            """
            UPDATE tasks
            SET cleanup_done = 1, updated_at = ?
            WHERE id = ?
              AND deleted_at IS NOT NULL
              AND COALESCE(cleanup_done, 0) = 0
            """,
            (serialize_datetime(utcnow()), task_id),
        ) as cursor:
            was_marked = cursor.rowcount > 0
        await db.commit()
        return was_marked


async def insert_task_event(
    db: aiosqlite.Connection,
    *,
    task_id: str,
    event: str,
    metadata: dict[str, Any],
    created_at: datetime | None,
) -> None:
    await db.execute(
        """
        INSERT INTO task_events (task_id, event, metadata_json, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            task_id,
            event,
            json.dumps(metadata),
            serialize_datetime(created_at or utcnow()),
        ),
    )
