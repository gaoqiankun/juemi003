from __future__ import annotations

import asyncio
from datetime import timedelta

import aiosqlite

from cubie.task.sequence import TERMINAL_STATUSES, TaskStatus, utcnow
from cubie.task.store.codec import serialize_datetime


async def update_stage_stats(
    db: aiosqlite.Connection,
    lock: asyncio.Lock,
    *,
    model: str,
    stage: str,
    duration_seconds: float,
) -> None:
    normalized_model = model.strip() or "trellis"
    normalized_stage = stage.strip()
    if not normalized_stage:
        return

    duration = max(float(duration_seconds), 0.0)
    async with lock:
        async with db.execute(
            """
            SELECT count, mean_seconds, m2_seconds
            FROM stage_stats
            WHERE model_name = ? AND stage_name = ?
            """,
            (normalized_model, normalized_stage),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            await db.execute(
                """
                INSERT INTO stage_stats (
                    model_name,
                    stage_name,
                    count,
                    mean_seconds,
                    m2_seconds
                ) VALUES (?, ?, 1, ?, 0.0)
                """,
                (
                    normalized_model,
                    normalized_stage,
                    duration,
                ),
            )
        else:
            previous_count = int(row["count"])
            previous_mean = float(row["mean_seconds"])
            previous_m2 = float(row["m2_seconds"])
            new_count = previous_count + 1
            delta = duration - previous_mean
            new_mean = previous_mean + (delta / new_count)
            delta2 = duration - new_mean
            new_m2 = previous_m2 + (delta * delta2)
            await db.execute(
                """
                UPDATE stage_stats
                SET count = ?, mean_seconds = ?, m2_seconds = ?
                WHERE model_name = ? AND stage_name = ?
                """,
                (
                    new_count,
                    new_mean,
                    new_m2,
                    normalized_model,
                    normalized_stage,
                ),
            )


async def get_stage_stats(
    db: aiosqlite.Connection,
    model: str,
) -> dict[str, dict[str, float | int]]:
    normalized_model = model.strip() or "trellis"
    async with db.execute(
        """
        SELECT stage_name, count, mean_seconds, m2_seconds
        FROM stage_stats
        WHERE model_name = ?
        """,
        (normalized_model,),
    ) as cursor:
        rows = await cursor.fetchall()
    return {
        str(row["stage_name"]): {
            "count": int(row["count"]),
            "mean_seconds": float(row["mean_seconds"]),
            "m2_seconds": float(row["m2_seconds"]),
        }
        for row in rows
    }


async def count_tasks_by_status(db: aiosqlite.Connection) -> dict[str, int]:
    result: dict[str, int] = {s.value: 0 for s in TaskStatus}
    async with db.execute(
        """
        SELECT status, COUNT(*) AS cnt
        FROM tasks
        WHERE deleted_at IS NULL
        GROUP BY status
        """
    ) as cursor:
        rows = await cursor.fetchall()
    for row in rows:
        result[str(row["status"])] = int(row["cnt"])
    return result


async def get_recent_tasks(
    db: aiosqlite.Connection,
    limit: int = 10,
) -> list[dict]:
    clamped = max(1, min(limit, 50))
    async with db.execute(
        """
        SELECT id, status, model, input_url, progress, current_stage,
               created_at, started_at, completed_at, key_id, error_message
        FROM tasks
        WHERE deleted_at IS NULL
        ORDER BY created_at DESC
        LIMIT ?
        """,
        (clamped,),
    ) as cursor:
        rows = await cursor.fetchall()
    return [
        {
            "id": row["id"],
            "status": row["status"],
            "model": row["model"],
            "input_url": row["input_url"],
            "progress": int(row["progress"]),
            "current_stage": row["current_stage"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "completed_at": row["completed_at"],
            "key_id": row["key_id"],
            "error_message": row["error_message"],
        }
        for row in rows
    ]


async def get_throughput_stats(
    db: aiosqlite.Connection,
    hours: int = 1,
) -> dict:
    safe_hours = max(1, int(hours))
    cutoff = serialize_datetime(utcnow() - timedelta(hours=safe_hours))
    async with db.execute(
        """
        SELECT
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS completed_count,
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) AS failed_count,
            AVG(
                CASE WHEN status = ? AND started_at IS NOT NULL
                THEN (julianday(completed_at) - julianday(started_at)) * 86400
                ELSE NULL END
            ) AS avg_duration_seconds
        FROM tasks
        WHERE deleted_at IS NULL
          AND completed_at IS NOT NULL
          AND status IN (?, ?)
          AND completed_at >= ?
        """,
        (
            TaskStatus.SUCCEEDED.value,
            TaskStatus.FAILED.value,
            TaskStatus.SUCCEEDED.value,
            TaskStatus.SUCCEEDED.value,
            TaskStatus.FAILED.value,
            cutoff,
        ),
    ) as cursor:
        row = await cursor.fetchone()
    return {
        "completed_count": int(row["completed_count"] or 0) if row else 0,
        "failed_count": int(row["failed_count"] or 0) if row else 0,
        "avg_duration_seconds": (
            float(row["avg_duration_seconds"])
            if row and row["avg_duration_seconds"] is not None
            else None
        ),
    }


async def get_active_task_count(db: aiosqlite.Connection) -> int:
    terminal_values = tuple(s.value for s in TERMINAL_STATUSES)
    placeholders = ", ".join("?" for _ in terminal_values)
    async with db.execute(
        f"""
        SELECT COUNT(*) AS c
        FROM tasks
        WHERE deleted_at IS NULL
          AND status NOT IN ({placeholders})
        """,
        terminal_values,
    ) as cursor:
        row = await cursor.fetchone()
    return int(row["c"] if row else 0)
