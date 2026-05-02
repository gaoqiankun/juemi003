from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

import aiosqlite
from gen3d.core.pagination import CursorPageResult, normalize_cursor_page_limit
from gen3d.task.sequence import RequestSequence, TaskStatus, utcnow
from gen3d.task.store.codec import deserialize_datetime, serialize_datetime

_TERMINAL_STATUSES = (
    TaskStatus.SUCCEEDED.value,
    TaskStatus.FAILED.value,
    TaskStatus.CANCELLED.value,
)


async def fetch_one(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple = (),
) -> aiosqlite.Row | None:
    async with db.execute(sql, params) as cursor:
        return await cursor.fetchone()


async def fetch_all(
    db: aiosqlite.Connection,
    sql: str,
    params: tuple = (),
) -> list[aiosqlite.Row]:
    async with db.execute(sql, params) as cursor:
        return await cursor.fetchall()


def rows_to_model_count_map(rows: list[aiosqlite.Row]) -> dict[str, int]:
    return {str(row["model"]).strip().lower(): int(row["c"]) for row in rows}


async def count_incomplete_tasks(db: aiosqlite.Connection) -> int:
    row = await fetch_one(
        db,
        """
        SELECT COUNT(*) AS c
        FROM tasks
        WHERE deleted_at IS NULL
          AND status NOT IN (?, ?, ?)
        """,
        _TERMINAL_STATUSES,
    )
    return int(row["c"] if row else 0)


async def count_queued_tasks(db: aiosqlite.Connection) -> int:
    row = await fetch_one(
        db,
        """
        SELECT COUNT(*) AS c
        FROM tasks
        WHERE deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
        """,
        (TaskStatus.QUEUED.value,),
    )
    return int(row["c"] if row else 0)


async def count_pending_tasks_by_model(db: aiosqlite.Connection) -> dict[str, int]:
    rows = await fetch_all(
        db,
        """
        SELECT model, COUNT(*) AS c
        FROM tasks
        WHERE deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
        GROUP BY model
        """,
        (TaskStatus.QUEUED.value,),
    )
    return rows_to_model_count_map(rows)


async def count_running_tasks_by_model(db: aiosqlite.Connection) -> dict[str, int]:
    rows = await fetch_all(
        db,
        """
        SELECT model, COUNT(*) AS c
        FROM tasks
        WHERE deleted_at IS NULL
          AND assigned_worker_id IS NOT NULL
          AND status NOT IN (?, ?, ?)
        GROUP BY model
        """,
        _TERMINAL_STATUSES,
    )
    return rows_to_model_count_map(rows)


async def get_oldest_queued_task_time_by_model(db: aiosqlite.Connection) -> dict[str, str]:
    rows = await fetch_all(
        db,
        """
        SELECT model, MIN(created_at) AS oldest_created_at
        FROM tasks
        WHERE deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
        GROUP BY model
        """,
        (TaskStatus.QUEUED.value,),
    )
    return {
        str(row["model"]).strip().lower(): str(row["oldest_created_at"])
        for row in rows
        if row["oldest_created_at"] is not None
    }


async def claim_next_queued_task(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    worker_id: str,
    *,
    get_task: Callable[[str], Awaitable[RequestSequence | None]],
) -> RequestSequence | None:
    while True:
        async with lock:
            task_id = await find_next_queued_task_id_locked(db)
            if task_id is None:
                return None
            was_claimed = await try_claim_task_locked(db, task_id, worker_id)
            await db.commit()
        if was_claimed:
            return await get_task(task_id)


async def find_next_queued_task_id_locked(db: aiosqlite.Connection) -> str | None:
    row = await fetch_one(
        db,
        """
        SELECT id
        FROM tasks
        WHERE deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
        ORDER BY queued_at ASC, id ASC
        LIMIT 1
        """,
        (TaskStatus.QUEUED.value,),
    )
    return str(row["id"]) if row is not None else None


async def try_claim_task_locked(
    db: aiosqlite.Connection,
    task_id: str,
    worker_id: str,
) -> bool:
    now = serialize_datetime(utcnow())
    async with db.execute(
        """
        UPDATE tasks
        SET assigned_worker_id = ?,
            started_at = COALESCE(started_at, ?),
            updated_at = ?
        WHERE id = ?
          AND deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
        """,
        (worker_id, now, now, task_id, TaskStatus.QUEUED.value),
    ) as cursor:
        return cursor.rowcount > 0


async def get_task(
    db: aiosqlite.Connection,
    task_id: str,
    *,
    row_to_sequence: Callable[[aiosqlite.Row], RequestSequence],
    include_deleted: bool = False,
) -> RequestSequence | None:
    if include_deleted:
        query = "SELECT * FROM tasks WHERE id = ?"
    else:
        query = "SELECT * FROM tasks WHERE id = ? AND deleted_at IS NULL"
    row = await fetch_one(db, query, (task_id,))
    return row_to_sequence(row) if row is not None else None


async def list_task_events(db: aiosqlite.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = await fetch_all(
        db,
        """
        SELECT id, task_id, event, metadata_json, created_at
        FROM task_events
        WHERE task_id = ?
        ORDER BY id ASC
        """,
        (task_id,),
    )
    return [
        {
            "id": row["id"],
            "task_id": row["task_id"],
            "event": row["event"],
            "metadata": json.loads(row["metadata_json"]),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


async def get_task_by_idempotency_key(
    db: aiosqlite.Connection,
    idempotency_key: str,
    *,
    row_to_sequence: Callable[[aiosqlite.Row], RequestSequence],
    include_deleted: bool = False,
) -> RequestSequence | None:
    if include_deleted:
        query = "SELECT * FROM tasks WHERE idempotency_key = ?"
    else:
        query = "SELECT * FROM tasks WHERE idempotency_key = ? AND deleted_at IS NULL"
    row = await fetch_one(db, query, (idempotency_key,))
    return row_to_sequence(row) if row is not None else None


async def list_incomplete_tasks(
    db: aiosqlite.Connection,
    *,
    row_to_sequence: Callable[[aiosqlite.Row], RequestSequence],
) -> list[RequestSequence]:
    rows = await fetch_all(
        db,
        """
        SELECT * FROM tasks
        WHERE deleted_at IS NULL
          AND status NOT IN (?, ?, ?)
        ORDER BY created_at ASC, id ASC
        """,
        _TERMINAL_STATUSES,
    )
    return [row_to_sequence(row) for row in rows]


async def list_tasks(
    db: aiosqlite.Connection,
    *,
    row_to_sequence: Callable[[aiosqlite.Row], RequestSequence],
    key_id: str | None,
    limit: int = 20,
    before: datetime | None = None,
) -> CursorPageResult[RequestSequence]:
    normalized_limit = normalize_cursor_page_limit(limit)
    where_parts = ["deleted_at IS NULL"]
    parameters: list[Any] = []
    if key_id is not None:
        where_parts.append("key_id = ?")
        parameters.append(key_id)
    if before is not None:
        where_parts.append("created_at < ?")
        parameters.append(serialize_datetime(before))
    where_sql = " AND ".join(where_parts)
    rows = await fetch_all(
        db,
        f"SELECT * FROM tasks WHERE {where_sql} ORDER BY created_at DESC, id DESC LIMIT ?",
        (*parameters, normalized_limit + 1),
    )
    page_rows = rows[:normalized_limit]
    has_more = len(rows) > normalized_limit
    next_cursor = (
        deserialize_datetime(page_rows[-1]["created_at"])
        if has_more and page_rows
        else None
    )
    return CursorPageResult(
        items=[row_to_sequence(row) for row in page_rows],
        has_more=has_more,
        next_cursor=next_cursor,
    )


async def get_queue_position(db: aiosqlite.Connection, task_id: str) -> int:
    row = await fetch_one(
        db,
        """
        SELECT queued_at, id
        FROM tasks
        WHERE id = ?
          AND deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
        """,
        (task_id, TaskStatus.QUEUED.value),
    )
    if row is None:
        return 0

    count_row = await fetch_one(
        db,
        """
        SELECT COUNT(*) AS c
        FROM tasks
        WHERE deleted_at IS NULL
          AND status = ?
          AND assigned_worker_id IS NULL
          AND (
            queued_at < ?
            OR (queued_at = ? AND id <= ?)
          )
        """,
        (TaskStatus.QUEUED.value, row["queued_at"], row["queued_at"], row["id"]),
    )
    return int(count_row["c"] if count_row else 0)


async def list_pending_cleanups(
    db: aiosqlite.Connection,
    *,
    limit: int = 20,
) -> list[str]:
    normalized_limit = max(int(limit), 1)
    rows = await fetch_all(
        db,
        """
        SELECT id
        FROM tasks
        WHERE deleted_at IS NOT NULL
          AND COALESCE(cleanup_done, 0) = 0
        ORDER BY deleted_at ASC, id ASC
        LIMIT ?
        """,
        (normalized_limit,),
    )
    return [str(row["id"]) for row in rows]
