from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from gen3d.engine.sequence import RequestSequence, TaskStatus, TaskType, utcnow


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
                updated_at TEXT NOT NULL
            )
            """
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
                        id, status, type, input_url, options_json, idempotency_key,
                        callback_url, output_artifacts_json, error_message, failed_stage,
                        retry_count, assigned_worker_id, current_stage, progress,
                        queue_position, estimated_wait_seconds, estimated_finish_at,
                        created_at, queued_at, started_at, completed_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        sequence.task_id,
                        sequence.status.value,
                        sequence.task_type.value,
                        sequence.input_url,
                        json.dumps(sequence.options),
                        sequence.idempotency_key,
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
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    sequence.status.value,
                    sequence.task_type.value,
                    sequence.input_url,
                    json.dumps(sequence.options),
                    sequence.idempotency_key,
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

    async def get_task(self, task_id: str) -> RequestSequence | None:
        db = self._require_db()
        cursor = await db.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
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
    ) -> RequestSequence | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE idempotency_key = ?",
            (idempotency_key,),
        )
        row = await cursor.fetchone()
        return self._row_to_sequence(row) if row is not None else None

    async def list_incomplete_tasks(self) -> list[RequestSequence]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT * FROM tasks
            WHERE status NOT IN (?, ?, ?)
            ORDER BY created_at ASC
            """,
            (
                TaskStatus.SUCCEEDED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            ),
        )
        rows = await cursor.fetchall()
        return [self._row_to_sequence(row) for row in rows]

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

    def _row_to_sequence(self, row: aiosqlite.Row) -> RequestSequence:
        return RequestSequence(
            task_id=row["id"],
            task_type=TaskType(row["type"]),
            input_url=row["input_url"],
            options=json.loads(row["options_json"]),
            callback_url=row["callback_url"],
            idempotency_key=row["idempotency_key"],
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
        )
