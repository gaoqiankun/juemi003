from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

_DEP_STATUSES = frozenset({"pending", "downloading", "done", "error"})


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


def _row_to_dep(row: aiosqlite.Row) -> dict:
    return {
        "dep_id": str(row["dep_id"]),
        "hf_repo_id": str(row["hf_repo_id"]),
        "resolved_path": _normalize_optional_text(row["resolved_path"]),
        "download_status": _normalize_dep_status(row["download_status"]),
        "download_progress": _normalize_download_progress(row["download_progress"]),
        "download_speed_bps": _normalize_download_speed_bps(row["download_speed_bps"]),
        "download_error": _normalize_optional_text(row["download_error"]),
        "revision": _normalize_optional_text(row["revision"]),
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


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS dep_cache (
            dep_id TEXT PRIMARY KEY,
            hf_repo_id TEXT NOT NULL,
            resolved_path TEXT,
            download_status TEXT NOT NULL DEFAULT 'pending',
            download_progress INTEGER NOT NULL DEFAULT 0,
            download_speed_bps INTEGER NOT NULL DEFAULT 0,
            download_error TEXT,
            revision TEXT DEFAULT NULL
        )
        """
    )
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS model_dep_requirements (
            model_id TEXT NOT NULL REFERENCES model_definitions(id) ON DELETE CASCADE,
            dep_id TEXT NOT NULL REFERENCES dep_cache(dep_id),
            PRIMARY KEY (model_id, dep_id)
        )
        """
    )


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


class DepCacheStore(_SQLiteStore):
    async def list_all(self) -> list[dict]:
        db = self._require_db()
        cursor = await db.execute("SELECT * FROM dep_cache ORDER BY dep_id")
        rows = await cursor.fetchall()
        return [_row_to_dep(row) for row in rows]

    async def get(self, dep_id: str) -> dict | None:
        db = self._require_db()
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        cursor = await db.execute("SELECT * FROM dep_cache WHERE dep_id = ?", (normalized_dep_id,))
        row = await cursor.fetchone()
        return _row_to_dep(row) if row else None

    async def get_or_create(
        self,
        dep_id: str,
        hf_repo_id: str,
        *,
        revision: str | None = None,
    ) -> dict:
        db = self._require_db()
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        normalized_hf_repo_id = _normalize_required_text(hf_repo_id, field="hf_repo_id")
        normalized_revision = _normalize_optional_text(revision)
        async with self._lock:
            await db.execute(
                "INSERT OR IGNORE INTO dep_cache (dep_id, hf_repo_id, revision) VALUES (?, ?, ?)",
                (normalized_dep_id, normalized_hf_repo_id, normalized_revision),
            )
            await db.execute(
                """
                UPDATE dep_cache
                SET hf_repo_id = ?, revision = COALESCE(revision, ?)
                WHERE dep_id = ?
                """,
                (normalized_hf_repo_id, normalized_revision, normalized_dep_id),
            )
            await db.commit()
        created = await self.get(normalized_dep_id)
        if created is None:
            raise RuntimeError(f"failed to create dep_cache row: {normalized_dep_id}")
        return created

    async def update_status(self, dep_id: str, status: str) -> dict | None:
        db = self._require_db()
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        normalized_status = _normalize_dep_status(status)
        async with self._lock:
            cursor = await db.execute(
                "UPDATE dep_cache SET download_status = ? WHERE dep_id = ?",
                (normalized_status, normalized_dep_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_dep_id)

    async def update_progress(self, dep_id: str, progress: int, speed_bps: int) -> dict | None:
        db = self._require_db()
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        normalized_progress = _normalize_download_progress(progress)
        normalized_speed_bps = _normalize_download_speed_bps(speed_bps)
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE dep_cache
                SET
                    download_status = 'downloading',
                    download_progress = ?,
                    download_speed_bps = ?,
                    download_error = NULL
                WHERE dep_id = ?
                """,
                (normalized_progress, normalized_speed_bps, normalized_dep_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_dep_id)

    async def update_done(self, dep_id: str, resolved_path: str) -> dict | None:
        db = self._require_db()
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        normalized_resolved_path = _normalize_optional_text(resolved_path)
        if normalized_resolved_path is None:
            raise ValueError("resolved_path is required when dependency download is done")
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE dep_cache
                SET
                    resolved_path = ?,
                    download_status = 'done',
                    download_progress = 100,
                    download_speed_bps = 0,
                    download_error = NULL
                WHERE dep_id = ?
                """,
                (normalized_resolved_path, normalized_dep_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_dep_id)

    async def update_error(self, dep_id: str, error: str) -> dict | None:
        db = self._require_db()
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        normalized_error = _normalize_optional_text(error) or "dependency download failed"
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE dep_cache
                SET
                    download_status = 'error',
                    download_speed_bps = 0,
                    download_error = ?
                WHERE dep_id = ?
                """,
                (normalized_error, normalized_dep_id),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get(normalized_dep_id)

    async def get_all_for_model(self, model_id: str) -> list[dict]:
        db = self._require_db()
        normalized_model_id = _normalize_required_text(model_id, field="model_id")
        cursor = await db.execute(
            """
            SELECT d.*
            FROM model_dep_requirements AS m
            JOIN dep_cache AS d ON d.dep_id = m.dep_id
            WHERE m.model_id = ?
            ORDER BY d.dep_id
            """,
            (normalized_model_id,),
        )
        rows = await cursor.fetchall()
        return [_row_to_dep(row) for row in rows]


class ModelDepRequirementsStore(_SQLiteStore):
    async def link(self, model_id: str, dep_id: str) -> None:
        db = self._require_db()
        normalized_model_id = _normalize_required_text(model_id, field="model_id")
        normalized_dep_id = _normalize_required_text(dep_id, field="dep_id")
        async with self._lock:
            await db.execute(
                "INSERT OR IGNORE INTO model_dep_requirements (model_id, dep_id) VALUES (?, ?)",
                (normalized_model_id, normalized_dep_id),
            )
            await db.commit()

    async def get_dep_ids_for_model(self, model_id: str) -> list[str]:
        db = self._require_db()
        normalized_model_id = _normalize_required_text(model_id, field="model_id")
        cursor = await db.execute(
            "SELECT dep_id FROM model_dep_requirements WHERE model_id = ? ORDER BY dep_id",
            (normalized_model_id,),
        )
        rows = await cursor.fetchall()
        return [str(row["dep_id"]) for row in rows]
