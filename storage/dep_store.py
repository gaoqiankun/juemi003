from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

_DEP_STATUSES = frozenset({"pending", "downloading", "done", "error"})
_WEIGHT_SOURCES = frozenset({"huggingface", "local", "url"})

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


def _normalize_required_text(value: object, *, field: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    return normalized


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_dep_status(value: object) -> str:
    normalized = str(value or "pending").strip().lower()
    if normalized not in _DEP_STATUSES:
        return "pending"
    return normalized


def _normalize_weight_source(value: object) -> str:
    normalized = str(value or "huggingface").strip().lower()
    if normalized not in _WEIGHT_SOURCES:
        return "huggingface"
    return normalized


def _normalize_weight_source_strict(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in _WEIGHT_SOURCES:
        raise ValueError("weight_source must be one of: huggingface, local, url")
    return normalized


def _normalize_download_progress(value: object) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, normalized))


def _normalize_download_speed_bps(value: object) -> int:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0
    return max(0, normalized)


def _row_to_dep_instance(row: aiosqlite.Row) -> dict:
    return {
        "id": str(row["id"]),
        "dep_type": str(row["dep_type"]),
        "hf_repo_id": str(row["hf_repo_id"]),
        "display_name": str(row["display_name"]),
        "weight_source": _normalize_weight_source(row["weight_source"]),
        "dep_model_path": _normalize_optional_text(row["dep_model_path"]),
        "resolved_path": _normalize_optional_text(row["resolved_path"]),
        "download_status": _normalize_dep_status(row["download_status"]),
        "download_progress": _normalize_download_progress(row["download_progress"]),
        "download_speed_bps": _normalize_download_speed_bps(row["download_speed_bps"]),
        "download_error": _normalize_optional_text(row["download_error"]),
        "created_at": _normalize_optional_text(row["created_at"]),
    }


async def _initialize_db(db_path: Path) -> aiosqlite.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA busy_timeout=5000")
    await db.execute("PRAGMA foreign_keys=ON")
    await _ensure_schema(db)
    await db.commit()
    return db


async def _table_exists(db: aiosqlite.Connection, table_name: str) -> bool:
    cursor = await db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ? LIMIT 1",
        (table_name,),
    )
    row = await cursor.fetchone()
    return row is not None


async def _table_columns(db: aiosqlite.Connection, table_name: str) -> set[str]:
    cursor = await db.execute(f"PRAGMA table_info({table_name})")
    rows = await cursor.fetchall()
    return {str(row["name"]) for row in rows}


async def _migrate_legacy_dep_cache(db: aiosqlite.Connection) -> None:
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


async def _ensure_model_dep_requirements_schema(db: aiosqlite.Connection) -> None:
    if not await _table_exists(db, "model_dep_requirements"):
        await db.execute(_MODEL_DEP_REQUIREMENTS_SCHEMA_SQL)
        return

    columns = await _table_columns(db, "model_dep_requirements")
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


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    has_dep_cache = await _table_exists(db, "dep_cache")
    await db.execute(_DEP_INSTANCES_SCHEMA_SQL)
    if has_dep_cache:
        await _migrate_legacy_dep_cache(db)
    await _ensure_model_dep_requirements_schema(db)
    if has_dep_cache:
        await db.execute("DROP TABLE IF EXISTS dep_cache")


class _SQLiteStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._db = await _initialize_db(self._db_path)

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError(f"{self.__class__.__name__}.initialize() must be called first")
        return self._db


class DepInstanceStore(_SQLiteStore):
    async def list_all(self) -> list[dict]:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM dep_instances ORDER BY dep_type, created_at, id"
        )
        rows = await cursor.fetchall()
        return [_row_to_dep_instance(row) for row in rows]

    async def list_by_dep_type(self, dep_type: str) -> list[dict]:
        db = self._require_db()
        normalized_dep_type = _normalize_required_text(dep_type, field="dep_type")
        cursor = await db.execute(
            "SELECT * FROM dep_instances WHERE dep_type = ? ORDER BY created_at, id",
            (normalized_dep_type,),
        )
        rows = await cursor.fetchall()
        return [_row_to_dep_instance(row) for row in rows]

    async def get(self, instance_id: str) -> dict | None:
        db = self._require_db()
        normalized_instance_id = _normalize_required_text(instance_id, field="instance_id")
        cursor = await db.execute(
            "SELECT * FROM dep_instances WHERE id = ?",
            (normalized_instance_id,),
        )
        row = await cursor.fetchone()
        return _row_to_dep_instance(row) if row else None

    async def find_duplicate_source(
        self,
        dep_type: str,
        weight_source: str,
        dep_model_path: str,
    ) -> dict | None:
        """Return an existing instance with the same dep_type + weight_source + dep_model_path, or None."""
        db = self._require_db()
        normalized_dep_type = _normalize_required_text(dep_type, field="dep_type")
        normalized_source = _normalize_weight_source(weight_source)
        normalized_path = _normalize_required_text(dep_model_path, field="dep_model_path")
        cursor = await db.execute(
            """
            SELECT * FROM dep_instances
            WHERE dep_type = ? AND weight_source = ? AND dep_model_path = ?
            ORDER BY created_at, id
            LIMIT 1
            """,
            (normalized_dep_type, normalized_source, normalized_path),
        )
        row = await cursor.fetchone()
        return _row_to_dep_instance(row) if row else None

    async def create(
        self,
        instance_id: str,
        dep_type: str,
        hf_repo_id: str,
        display_name: str,
        *,
        weight_source: str = "huggingface",
        dep_model_path: str | None = None,
    ) -> dict:
        db = self._require_db()
        normalized_instance_id = _normalize_required_text(instance_id, field="instance_id")
        normalized_dep_type = _normalize_required_text(dep_type, field="dep_type")
        normalized_hf_repo_id = _normalize_required_text(hf_repo_id, field="hf_repo_id")
        normalized_display_name = _normalize_required_text(display_name, field="display_name")
        normalized_weight_source = _normalize_weight_source_strict(weight_source)
        normalized_dep_model_path = _normalize_optional_text(dep_model_path)
        async with self._lock:
            await db.execute(
                """
                INSERT OR IGNORE INTO dep_instances
                    (id, dep_type, hf_repo_id, display_name, weight_source, dep_model_path)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    normalized_instance_id,
                    normalized_dep_type,
                    normalized_hf_repo_id,
                    normalized_display_name,
                    normalized_weight_source,
                    normalized_dep_model_path,
                ),
            )
            await db.commit()
        created = await self.get(normalized_instance_id)
        if created is None:
            raise RuntimeError(f"failed to create dep_instances row: {normalized_instance_id}")
        return created

    async def update_status(self, instance_id: str, status: str) -> dict | None:
        db = self._require_db()
        normalized_instance_id = _normalize_required_text(instance_id, field="instance_id")
        normalized_status = _normalize_dep_status(status)
        async with self._lock:
            cursor = await db.execute(
                "UPDATE dep_instances SET download_status = ? WHERE id = ?",
                (normalized_status, normalized_instance_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_instance_id)

    async def update_progress(self, instance_id: str, progress: int, speed_bps: int) -> dict | None:
        db = self._require_db()
        normalized_instance_id = _normalize_required_text(instance_id, field="instance_id")
        normalized_progress = _normalize_download_progress(progress)
        normalized_speed_bps = _normalize_download_speed_bps(speed_bps)
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE dep_instances
                SET
                    download_status = 'downloading',
                    download_progress = ?,
                    download_speed_bps = ?,
                    download_error = NULL
                WHERE id = ?
                """,
                (normalized_progress, normalized_speed_bps, normalized_instance_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_instance_id)

    async def update_done(self, instance_id: str, resolved_path: str) -> dict | None:
        db = self._require_db()
        normalized_instance_id = _normalize_required_text(instance_id, field="instance_id")
        normalized_resolved_path = _normalize_optional_text(resolved_path)
        if normalized_resolved_path is None:
            raise ValueError("resolved_path is required when dependency download is done")
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE dep_instances
                SET
                    resolved_path = ?,
                    download_status = 'done',
                    download_progress = 100,
                    download_speed_bps = 0,
                    download_error = NULL
                WHERE id = ?
                """,
                (normalized_resolved_path, normalized_instance_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_instance_id)

    async def update_error(self, instance_id: str, error: str) -> dict | None:
        db = self._require_db()
        normalized_instance_id = _normalize_required_text(instance_id, field="instance_id")
        normalized_error = _normalize_optional_text(error) or "dependency download failed"
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE dep_instances
                SET
                    download_status = 'error',
                    download_speed_bps = 0,
                    download_error = ?
                WHERE id = ?
                """,
                (normalized_error, normalized_instance_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_instance_id)

    async def get_all_for_model(self, model_id: str) -> list[dict]:
        db = self._require_db()
        normalized_model_id = _normalize_required_text(model_id, field="model_id")
        cursor = await db.execute(
            """
            SELECT d.*, m.dep_type AS required_dep_type, m.dep_instance_id
            FROM model_dep_requirements AS m
            JOIN dep_instances AS d ON d.id = m.dep_instance_id
            WHERE m.model_id = ?
            ORDER BY m.dep_type, d.created_at, d.id
            """,
            (normalized_model_id,),
        )
        rows = await cursor.fetchall()
        results: list[dict] = []
        for row in rows:
            item = _row_to_dep_instance(row)
            item["dep_type"] = str(row["required_dep_type"] or item["dep_type"])
            item["instance_id"] = str(row["dep_instance_id"] or item["id"])
            results.append(item)
        return results


class ModelDepRequirementsStore(_SQLiteStore):
    async def assign(self, model_id: str, dep_type: str, dep_instance_id: str) -> None:
        db = self._require_db()
        normalized_model_id = _normalize_required_text(model_id, field="model_id")
        normalized_dep_type = _normalize_required_text(dep_type, field="dep_type")
        normalized_dep_instance_id = _normalize_required_text(
            dep_instance_id,
            field="dep_instance_id",
        )
        async with self._lock:
            await db.execute(
                """
                INSERT OR REPLACE INTO model_dep_requirements (model_id, dep_type, dep_instance_id)
                VALUES (?, ?, ?)
                """,
                (normalized_model_id, normalized_dep_type, normalized_dep_instance_id),
            )
            await db.commit()

    async def get_assignments_for_model(self, model_id: str) -> list[dict]:
        db = self._require_db()
        normalized_model_id = _normalize_required_text(model_id, field="model_id")
        cursor = await db.execute(
            """
            SELECT dep_type, dep_instance_id
            FROM model_dep_requirements
            WHERE model_id = ?
            ORDER BY dep_type
            """,
            (normalized_model_id,),
        )
        rows = await cursor.fetchall()
        return [
            {
                "dep_type": str(row["dep_type"]),
                "dep_instance_id": str(row["dep_instance_id"]),
            }
            for row in rows
        ]
