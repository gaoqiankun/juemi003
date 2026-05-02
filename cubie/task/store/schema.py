from __future__ import annotations

from pathlib import Path

import aiosqlite


async def initialize_task_store(database_path: Path) -> aiosqlite.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(database_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA synchronous=NORMAL")
    await db.execute("PRAGMA temp_store=MEMORY")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute(
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
    await ensure_task_column(db, "model", "TEXT NOT NULL DEFAULT 'trellis'")
    await ensure_task_column(db, "key_id", "TEXT")
    await ensure_task_column(db, "deleted_at", "TEXT")
    await ensure_task_column(db, "cleanup_done", "INTEGER NOT NULL DEFAULT 0")
    await db.execute(
        "UPDATE tasks SET model = 'trellis' WHERE model IS NULL OR TRIM(model) = ''"
    )
    await db.execute(
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
    await db.execute(
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
    await db.commit()
    return db


async def ensure_task_column(
    db: aiosqlite.Connection,
    column_name: str,
    definition_sql: str,
) -> None:
    async with db.execute("PRAGMA table_info(tasks)") as cursor:
        rows = await cursor.fetchall()
    existing_columns = {str(row["name"]) for row in rows}
    if column_name in existing_columns:
        return
    await db.execute(f"ALTER TABLE tasks ADD COLUMN {column_name} {definition_sql}")
