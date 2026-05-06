from __future__ import annotations

from pathlib import Path

import aiosqlite

_DEP_INSTANCES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS dep_instances (
    id                 TEXT PRIMARY KEY,
    dep_type           TEXT NOT NULL,
    hf_repo_id         TEXT NOT NULL,
    display_name       TEXT NOT NULL,
    weight_source      TEXT NOT NULL DEFAULT 'huggingface',
    dep_model_path     TEXT,
    resolved_path      TEXT,
    download_status    TEXT NOT NULL DEFAULT 'pending',
    download_progress  INTEGER NOT NULL DEFAULT 0,
    download_speed_bps INTEGER NOT NULL DEFAULT 0,
    download_error     TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
)
"""

_MODEL_DEP_REQUIREMENTS_SCHEMA_SQL = """
CREATE TABLE model_dep_requirements (
    model_id        TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE,
    dep_type        TEXT NOT NULL,
    dep_instance_id TEXT NOT NULL REFERENCES dep_instances(id),
    PRIMARY KEY (model_id, dep_type)
)
"""


async def initialize_db(db_path: Path) -> aiosqlite.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await ensure_schema(db)
    await db.commit()
    return db


async def table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    async with db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    ) as cursor:
        row = await cursor.fetchone()
    return row is not None


async def table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
    async with db.execute(f"PRAGMA table_info({table_name})") as cursor:
        rows = await cursor.fetchall()
    return {str(row["name"]) for row in rows}


async def migrate_legacy_dep_cache(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        INSERT OR IGNORE INTO dep_instances
            (id, dep_type, hf_repo_id, display_name, weight_source,
             resolved_path, download_status, download_progress,
             download_speed_bps, download_error)
        SELECT dep_id, dep_id, hf_repo_id, dep_id, 'huggingface',
               resolved_path, download_status, download_progress,
               download_speed_bps, download_error
        FROM dep_cache
        """
    )


async def ensure_model_dep_requirements_schema(db: aiosqlite.Connection) -> None:
    if not await table_exists(db, "model_dep_requirements"):
        await db.execute(_MODEL_DEP_REQUIREMENTS_SCHEMA_SQL)
        return

    columns = await table_columns(db, "model_dep_requirements")
    if {"model_id", "dep_type", "dep_instance_id"}.issubset(columns):
        return

    await db.execute("DROP TABLE IF EXISTS _model_dep_requirements_old")
    await db.execute("ALTER TABLE model_dep_requirements RENAME TO _model_dep_requirements_old")
    await db.execute(_MODEL_DEP_REQUIREMENTS_SCHEMA_SQL)

    if "dep_id" in columns:
        await db.execute(
            """
            INSERT OR IGNORE INTO model_dep_requirements (model_id, dep_type, dep_instance_id)
            SELECT model_id, dep_id, dep_id
            FROM _model_dep_requirements_old
            WHERE TRIM(COALESCE(dep_id, '')) <> ''
              AND dep_id IN (SELECT id FROM dep_instances)
            """
        )
    elif {"dep_type", "dep_instance_id"}.issubset(columns):
        await db.execute(
            """
            INSERT OR IGNORE INTO model_dep_requirements (model_id, dep_type, dep_instance_id)
            SELECT model_id, dep_type, dep_instance_id
            FROM _model_dep_requirements_old
            WHERE TRIM(COALESCE(dep_type, '')) <> ''
              AND TRIM(COALESCE(dep_instance_id, '')) <> ''
              AND dep_instance_id IN (SELECT id FROM dep_instances)
            """
        )

    await db.execute("DROP TABLE _model_dep_requirements_old")


async def ensure_schema(db: aiosqlite.Connection) -> None:
    has_dep_cache = await table_exists(db, "dep_cache")
    await db.execute(_DEP_INSTANCES_SCHEMA_SQL)
    if has_dep_cache:
        await migrate_legacy_dep_cache(db)
    await ensure_model_dep_requirements_schema(db)
    if has_dep_cache:
        await db.execute("DROP TABLE IF EXISTS dep_cache")
