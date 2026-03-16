from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from gen3d.engine.sequence import RequestSequence, TaskStatus, TaskType, utcnow
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


class TaskStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._database_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'image_to_3d',
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
                deleted_at TEXT
            )
            """
        )
        await self._ensure_task_column("key_id", "TEXT")
        await self._ensure_task_column("deleted_at", "TEXT")
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
                        id, status, type, input_url, options_json, idempotency_key, key_id,
                        callback_url, output_artifacts_json, error_message, failed_stage,
                        retry_count, assigned_worker_id, current_stage, progress,
                        queue_position, estimated_wait_seconds, estimated_finish_at,
                        created_at, queued_at, started_at, completed_at, updated_at, deleted_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence.task_id,
                        sequence.status.value,
                        sequence.task_type.value,
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
                SET deleted_at = ?, updated_at = ?
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
            input_url=row["input_url"],
            options=json.loads(row["options_json"]),
            callback_url=row["callback_url"],
            idempotency_key=row["idempotency_key"],
            key_id=row["key_id"],
            status=TaskStatus(row["status"]),
            progress=row["progress"],
            current_stage=row["current_stage"] or row["status"],
            queue_position=row["queue_position"],
            estimated_wait_seconds=row["estimated_wait_seconds"],
            estimated_finish_at=_deserialize_datetime(row["estimated_finish_at"]),
            artifacts=json.loads(row["output_artifacts_json"]),
            error_message=row["error_message"],
            failed_stage=row["failed_stage"],
            retry_count=row["retry_count"],
            assigned_worker_id=row["assigned_worker_id"],
            created_at=_deserialize_datetime(row["created_at"]) or datetime.utcnow(),
            queued_at=_deserialize_datetime(row["queued_at"]) or datetime.utcnow(),
            started_at=_deserialize_datetime(row["started_at"]),
            completed_at=_deserialize_datetime(row["completed_at"]),
            updated_at=_deserialize_datetime(row["updated_at"]) or datetime.utcnow(),
            deleted_at=_deserialize_datetime(row["deleted_at"]),
        )
