from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class SettingsStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(self._db_path)
        self._db.row_factory = aiosqlite.Row
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS system_settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def get_all(self) -> dict[str, Any]:
        db = self._require_db()
        cursor = await db.execute("SELECT key, value FROM system_settings")
        rows = await cursor.fetchall()
        return {str(row["key"]): json.loads(row["value"]) for row in rows}

    async def get(self, key: str) -> Any | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT value FROM system_settings WHERE key = ?", (key,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    async def set(self, key: str, value: Any) -> None:
        db = self._require_db()
        async with self._lock:
            await db.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), _utcnow_iso()),
            )
            await db.commit()

    async def set_many(self, settings: dict[str, Any]) -> None:
        db = self._require_db()
        now = _utcnow_iso()
        async with self._lock:
            for key, value in settings.items():
                await db.execute(
                    """
                    INSERT INTO system_settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                    """,
                    (key, json.dumps(value), now),
                )
            await db.commit()

    async def delete(self, key: str) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM system_settings WHERE key = ?", (key,)
            )
            await db.commit()
            return cursor.rowcount > 0

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SettingsStore.initialize() must be called first")
        return self._db
