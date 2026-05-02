from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite

MAX_LOADED_MODELS_KEY = "max_loaded_models"
MAX_TASKS_PER_SLOT_KEY = "max_tasks_per_slot"
GPU_DISABLED_DEVICES_KEY = "gpu_disabled_devices"
EXTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY = "external_vram_wait_timeout_seconds"
INTERNAL_VRAM_WAIT_TIMEOUT_SECONDS_KEY = "internal_vram_wait_timeout_seconds"


def utcnow_iso() -> str:
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
        db = self.require_db()
        async with db.execute("SELECT key, value FROM system_settings") as cursor:
            rows = await cursor.fetchall()
        return {str(row["key"]): json.loads(row["value"]) for row in rows}

    async def get(self, key: str) -> Any | None:
        db = self.require_db()
        async with db.execute(
            "SELECT value FROM system_settings WHERE key = ?", (key,)
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row["value"])

    async def set(self, key: str, value: Any) -> None:
        db = self.require_db()
        async with self._lock:
            await db.execute(
                """
                INSERT INTO system_settings (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, json.dumps(value), utcnow_iso()),
            )
            await db.commit()

    async def set_many(self, settings: dict[str, Any]) -> None:
        db = self.require_db()
        now = utcnow_iso()
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
        db = self.require_db()
        async with self._lock:
            async with db.execute(
                "DELETE FROM system_settings WHERE key = ?", (key,)
            ) as cursor:
                was_deleted = cursor.rowcount > 0
            await db.commit()
            return was_deleted

    def require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("SettingsStore.initialize() must be called first")
        return self._db
