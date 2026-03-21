from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from gen3d.engine.sequence import (
    TERMINAL_STATUSES,
    RequestSequence,
    TaskStatus,
    TaskType,
    utcnow,
)
from gen3d.pagination import CursorPageResult, normalize_cursor_page_limit


class TaskIdempotencyConflictError(RuntimeError):
    def __init__(self, existing_sequence: RequestSequence) -> None:
        super().__init__(
            f"idempotency key already exists for task {existing_sequence.task_id}"
        )
        self.existing_sequence = existing_sequence


def _serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _deserialize_datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _deserialize_status(value: str) -> TaskStatus:
    normalized = str(value).strip().lower()
    if normalized == "submitted":
        normalized = TaskStatus.QUEUED.value
    return TaskStatus(normalized)


class TaskStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._database_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA synchronous=NORMAL")
        await self._db.execute("PRAGMA temp_store=MEMORY")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'image_to_3d',
                model TEXT NOT NULL DEFAULT 'trellis',
                input_url TEXT NOT NULL,
                options_json TEXT NOT NULL,
                idempotency_key TEXT UNIQUE,
                key_id TEXT,
                callback_url TEXT,
                output_artifacts_json TEXT NOT NULL DEFAULT '[]',
                error_message TEXT,
                failed_stage TEXT,
                retry_count INTEGER NOT NULL DEFAULT 0,
                assigned_worker_id TEXT,
                current_stage TEXT,
                progress INTEGER NOT NULL DEFAULT 0,
                queue_position INTEGER,
                estimated_wait_seconds INTEGER,
                estimated_finish_at TEXT,
                created_at TEXT NOT NULL,
                queued_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                updated_at TEXT NOT NULL,
                deleted_at TEXT,
                cleanup_done INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await self._ensure_task_column("model", "TEXT NOT NULL DEFAULT 'trellis'")
        await self._ensure_task_column("key_id", "TEXT")
        await self._ensure_task_column("deleted_at", "TEXT")
        await self._ensure_task_column("cleanup_done", "INTEGER NOT NULL DEFAULT 0")
        await self._db.execute(
            "UPDATE tasks SET model = 'trellis' WHERE model IS NULL OR TRIM(model) = ''"
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS task_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                event TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            )
            """
        )
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS stage_stats (
                model_name TEXT NOT NULL,
                stage_name TEXT NOT NULL,
                count INTEGER NOT NULL,
                mean_seconds REAL NOT NULL,
                m2_seconds REAL NOT NULL,
                PRIMARY KEY (model_name, stage_name)
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create_task(self, sequence: RequestSequence) -> None:
        db = self._require_db()
        async with self._lock:
            try:
                await db.execute(
                    """
                    INSERT INTO tasks (
                        id, status, type, model, input_url, options_json, idempotency_key, key_id,
                        callback_url, output_artifacts_json, error_message, failed_stage,
                        retry_count, assigned_worker_id, current_stage, progress,
                        queue_position, estimated_wait_seconds, estimated_finish_at,
                        created_at, queued_at, started_at, completed_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence.task_id,
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
                        _serialize_datetime(sequence.estimated_finish_at),
                        _serialize_datetime(sequence.created_at),
                        _serialize_datetime(sequence.queued_at),
                        _serialize_datetime(sequence.started_at),
                        _serialize_datetime(sequence.completed_at),
                        _serialize_datetime(sequence.updated_at),
                        _serialize_datetime(sequence.deleted_at),
                    ),
                )
            except aiosqlite.IntegrityError as exc:
                conflict_text = str(exc).lower()
                if not sequence.idempotency_key or "idempotency_key" not in conflict_text:
                    raise
                cursor = await db.execute(
                    "SELECT * FROM tasks WHERE idempotency_key = ?",
                    (sequence.idempotency_key,),
                )
                row = await cursor.fetchone()
                if row is None:
                    raise
                raise TaskIdempotencyConflictError(self._row_to_sequence(row)) from exc
            await self._insert_task_event(
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

    async def update_task(
        self,
        sequence: RequestSequence,
        *,
        event: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        db = self._require_db()
        async with self._lock:
            await db.execute(
                """
                UPDATE tasks SET
                    status = ?,
                    type = ?,
                    model = ?,
                    input_url = ?,
                    options_json = ?,
                    idempotency_key = ?,
                    key_id = ?,
                    callback_url = ?,
                    output_artifacts_json = ?,
                    error_message = ?,
                    failed_stage = ?,
                    retry_count = ?,
                    assigned_worker_id = ?,
                    current_stage = ?,
                    progress = ?,
                    queue_position = ?,
                    estimated_wait_seconds = ?,
                    estimated_finish_at = ?,
                    created_at = ?,
                    queued_at = ?,
                    started_at = ?,
                    completed_at = ?,
                    updated_at = ?,
                    deleted_at = ?
                WHERE id = ?
                """,
                (
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
                    _serialize_datetime(sequence.estimated_finish_at),
                    _serialize_datetime(sequence.created_at),
                    _serialize_datetime(sequence.queued_at),
                    _serialize_datetime(sequence.started_at),
                    _serialize_datetime(sequence.completed_at),
                    _serialize_datetime(sequence.updated_at),
                    _serialize_datetime(sequence.deleted_at),
                    sequence.task_id,
                ),
            )
            if event is not None:
                await self._insert_task_event(
                    db,
                    task_id=sequence.task_id,
                    event=event,
                    metadata=metadata or {},
                    created_at=sequence.updated_at,
                )
            await db.commit()

    async def append_task_event(
        self,
        task_id: str,
        *,
        event: str,
        metadata: dict[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> None:
        db = self._require_db()
        async with self._lock:
            await self._insert_task_event(
                db,
                task_id=task_id,
                event=event,
                metadata=metadata or {},
                created_at=created_at,
            )
            await db.commit()

    async def count_incomplete_tasks(self) -> int:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS c
            FROM tasks
            WHERE deleted_at IS NULL
              AND status NOT IN (?, ?, ?)
            """,
            (
                TaskStatus.SUCCEEDED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ),
        )
        row = await cursor.fetchone()
        return int(row["c"] if row else 0)

    async def count_queued_tasks(self) -> int:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT COUNT(*) AS c
            FROM tasks
            WHERE deleted_at IS NULL
              AND status = ?
              AND assigned_worker_id IS NULL
            """,
            (TaskStatus.QUEUED.value,),
        )
        row = await cursor.fetchone()
        return int(row["c"] if row else 0)

    async def claim_next_queued_task(self, worker_id: str) -> RequestSequence | None:
        db = self._require_db()
        while True:
            cursor = await db.execute(
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
            row = await cursor.fetchone()
            if row is None:
                return None

            now = _serialize_datetime(utcnow())
            async with self._lock:
                update_cursor = await db.execute(
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
                    (
                        worker_id,
                        now,
                        now,
                        row["id"],
                        TaskStatus.QUEUED.value,
                    ),
                )
                await db.commit()
                if update_cursor.rowcount == 0:
                    continue
            return await self.get_task(str(row["id"]))

    async def requeue_task(self, task_id: str) -> bool:
        db = self._require_db()
        async with self._lock:
            now = _serialize_datetime(utcnow())
            cursor = await db.execute(
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
            )
            await db.commit()
            return cursor.rowcount > 0

    async def delete_task(self, task_id: str) -> None:
        db = self._require_db()
        async with self._lock:
            await db.execute("DELETE FROM task_events WHERE task_id = ?", (task_id,))
            await db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            await db.commit()

    async def get_task(
        self,
        task_id: str,
        *,
        include_deleted: bool = False,
    ) -> RequestSequence | None:
        db = self._require_db()
        if include_deleted:
            cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        else:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE id = ? AND deleted_at IS NULL",
                (task_id,),
            )
        row = await cursor.fetchone()
        return self._row_to_sequence(row) if row is not None else None

    async def list_task_events(self, task_id: str) -> list[dict[str, Any]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT id, task_id, event, metadata_json, created_at
            FROM task_events
            WHERE task_id = ?
            ORDER BY id ASC
            """,
            (task_id,),
        )
        rows = await cursor.fetchall()
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
        self,
        idempotency_key: str,
        *,
        include_deleted: bool = False,
    ) -> RequestSequence | None:
        db = self._require_db()
        if include_deleted:
            cursor = await db.execute(
                "SELECT * FROM tasks WHERE idempotency_key = ?",
                (idempotency_key,),
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM tasks
                WHERE idempotency_key = ? AND deleted_at IS NULL
                """,
                (idempotency_key,),
            )
        row = await cursor.fetchone()
        return self._row_to_sequence(row) if row is not None else None

    async def list_incomplete_tasks(self) -> list[RequestSequence]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT * FROM tasks
            WHERE deleted_at IS NULL
              AND status NOT IN (?, ?, ?)
            ORDER BY created_at ASC, id ASC
            """,
            (
                TaskStatus.SUCCEEDED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_sequence(row) for row in rows]

    async def list_tasks(
        self,
        *,
        key_id: str | None,
        limit: int = 20,
        before: datetime | None = None,
    ) -> CursorPageResult[RequestSequence]:
        db = self._require_db()
        normalized_limit = normalize_cursor_page_limit(limit)
        where_parts = ["deleted_at IS NULL"]
        parameters: list[Any] = []
        if key_id is not None:
            where_parts.append("key_id = ?")
            parameters.append(key_id)
        if before is not None:
            where_parts.append("created_at < ?")
            parameters.append(_serialize_datetime(before))
        where_sql = " AND ".join(where_parts)
        cursor = await db.execute(
            f"""
            SELECT * FROM tasks
            WHERE {where_sql}
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (*parameters, normalized_limit + 1),
        )
        rows = await cursor.fetchall()
        page_rows = rows[:normalized_limit]
        items = [self._row_to_sequence(row) for row in page_rows]
        has_more = len(rows) > normalized_limit
        next_cursor = (
            _deserialize_datetime(page_rows[-1]["created_at"])
            if has_more and page_rows
            else None
        )
        return CursorPageResult(
            items=items,
            has_more=has_more,
            next_cursor=next_cursor,
        )

    async def get_queue_position(self, task_id: str) -> int:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT queued_at, id
            FROM tasks
            WHERE id = ?
              AND deleted_at IS NULL
              AND status = ?
              AND assigned_worker_id IS NULL
            """,
            (
                task_id,
                TaskStatus.QUEUED.value,
            ),
        )
        row = await cursor.fetchone()
        if row is None:
            return 0

        count_cursor = await db.execute(
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
            (
                TaskStatus.QUEUED.value,
                row["queued_at"],
                row["queued_at"],
                row["id"],
            ),
        )
        count_row = await count_cursor.fetchone()
        return int(count_row["c"] if count_row else 0)

    async def soft_delete_task(
        self,
        task_id: str,
        *,
        deleted_at: datetime | None = None,
    ) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE tasks
                SET deleted_at = ?, cleanup_done = 0, updated_at = ?
                WHERE id = ? AND deleted_at IS NULL
                """,
                (
                    _serialize_datetime(deleted_at or utcnow()),
                    _serialize_datetime(utcnow()),
                    task_id,
                ),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def update_stage_stats(
        self,
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
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                """
                SELECT count, mean_seconds, m2_seconds
                FROM stage_stats
                WHERE model_name = ? AND stage_name = ?
                """,
                (normalized_model, normalized_stage),
            )
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

    async def get_stage_stats(self, model: str) -> dict[str, dict[str, float | int]]:
        normalized_model = model.strip() or "trellis"
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT stage_name, count, mean_seconds, m2_seconds
            FROM stage_stats
            WHERE model_name = ?
            """,
            (normalized_model,),
        )
        rows = await cursor.fetchall()
        return {
            str(row["stage_name"]): {
                "count": int(row["count"]),
                "mean_seconds": float(row["mean_seconds"]),
                "m2_seconds": float(row["m2_seconds"]),
            }
            for row in rows
        }

    async def list_pending_cleanups(self, *, limit: int = 20) -> list[str]:
        db = self._require_db()
        normalized_limit = max(int(limit), 1)
        cursor = await db.execute(
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
        rows = await cursor.fetchall()
        return [str(row["id"]) for row in rows]

    async def mark_cleanup_done(self, task_id: str) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE tasks
                SET cleanup_done = 1, updated_at = ?
                WHERE id = ?
                  AND deleted_at IS NOT NULL
                  AND COALESCE(cleanup_done, 0) = 0
                """,
                (_serialize_datetime(utcnow()), task_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def count_tasks_by_status(self) -> dict[str, int]:
        db = self._require_db()
        result: dict[str, int] = {s.value: 0 for s in TaskStatus}
        cursor = await db.execute(
            """
            SELECT status, COUNT(*) AS cnt
            FROM tasks
            WHERE deleted_at IS NULL
            GROUP BY status
            """
        )
        rows = await cursor.fetchall()
        for row in rows:
            result[str(row["status"])] = int(row["cnt"])
        return result

    async def get_recent_tasks(self, limit: int = 10) -> list[dict]:
        db = self._require_db()
        clamped = max(1, min(limit, 50))
        cursor = await db.execute(
            """
            SELECT id, status, model, input_url, progress, current_stage,
                   created_at, started_at, completed_at, key_id, error_message
            FROM tasks
            WHERE deleted_at IS NULL
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (clamped,),
        )
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

    async def get_throughput_stats(self, hours: int = 1) -> dict:
        db = self._require_db()
        safe_hours = max(1, int(hours))
        from datetime import timedelta

        cutoff = _serialize_datetime(utcnow() - timedelta(hours=safe_hours))
        cursor = await db.execute(
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
        )
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

    async def get_active_task_count(self) -> int:
        db = self._require_db()
        terminal_values = tuple(s.value for s in TERMINAL_STATUSES)
        placeholders = ", ".join("?" for _ in terminal_values)
        cursor = await db.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM tasks
            WHERE deleted_at IS NULL
              AND status NOT IN ({placeholders})
            """,
            terminal_values,
        )
        row = await cursor.fetchone()
        return int(row["c"] if row else 0)

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("TaskStore is not initialized")
        return self._db

    async def _insert_task_event(
        self,
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
                _serialize_datetime(created_at or utcnow()),
            ),
        )

    async def _ensure_task_column(self, column_name: str, definition_sql: str) -> None:
        db = self._require_db()
        cursor = await db.execute("PRAGMA table_info(tasks)")
        rows = await cursor.fetchall()
        existing_columns = {str(row["name"]) for row in rows}
        if column_name in existing_columns:
            return
        await db.execute(
            f"ALTER TABLE tasks ADD COLUMN {column_name} {definition_sql}"
        )

    def _row_to_sequence(self, row: aiosqlite.Row) -> RequestSequence:
        return RequestSequence(
            task_id=row["id"],
            task_type=TaskType(row["type"]),
            model=(str(row["model"]).strip() if row["model"] else "trellis") or "trellis",
            input_url=row["input_url"],
            options=json.loads(row["options_json"]),
            callback_url=row["callback_url"],
            idempotency_key=row["idempotency_key"],
            key_id=row["key_id"],
            status=_deserialize_status(row["status"]),
            progress=int(row["progress"]),
            current_stage=row["current_stage"] or _deserialize_status(row["status"]).value,
            queue_position=row["queue_position"],
            estimated_wait_seconds=row["estimated_wait_seconds"],
            estimated_finish_at=_deserialize_datetime(row["estimated_finish_at"]),
            artifacts=json.loads(row["output_artifacts_json"]),
            error_message=row["error_message"],
            failed_stage=row["failed_stage"],
            retry_count=int(row["retry_count"]),
            assigned_worker_id=row["assigned_worker_id"],
            created_at=_deserialize_datetime(row["created_at"]) or utcnow(),
            queued_at=_deserialize_datetime(row["queued_at"]) or utcnow(),
            started_at=_deserialize_datetime(row["started_at"]),
            completed_at=_deserialize_datetime(row["completed_at"]),
            updated_at=_deserialize_datetime(row["updated_at"]) or utcnow(),
            deleted_at=_deserialize_datetime(row["deleted_at"]),
        )
