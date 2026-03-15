from __future__ import annotations

import asyncio
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


class ApiKeyStore:
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
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create_key(self, label: str) -> dict[str, str]:
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("label is required")

        db = self._require_db()
        async with self._lock:
            for _ in range(5):
                created_at = _utcnow_iso()
                payload = {
                    "key_id": uuid.uuid4().hex,
                    "token": secrets.token_urlsafe(32),
                    "label": normalized_label,
                    "created_at": created_at,
                }
                try:
                    await db.execute(
                        """
                        INSERT INTO api_keys (
                            key_id,
                            token,
                            label,
                            created_at,
                            is_active
                        ) VALUES (?, ?, ?, ?, 1)
                        """,
                        (
                            payload["key_id"],
                            payload["token"],
                            payload["label"],
                            payload["created_at"],
                        ),
                    )
                except aiosqlite.IntegrityError:
                    continue
                await db.commit()
                return payload
        raise RuntimeError("failed to generate a unique API key")

    async def list_keys(self) -> list[dict[str, str | bool]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT key_id, label, created_at, is_active
            FROM api_keys
            ORDER BY created_at DESC, key_id DESC
            """
        )
        rows = await cursor.fetchall()
        return [self._serialize_row(row) for row in rows]

    async def set_active(self, key_id: str, is_active: bool) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "UPDATE api_keys SET is_active = ? WHERE key_id = ?",
                (1 if is_active else 0, key_id),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_key(self, key_id: str) -> dict[str, str | bool] | None:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT key_id, label, created_at, is_active
            FROM api_keys
            WHERE key_id = ?
            """,
            (key_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._serialize_row(row)

    async def validate_token(self, token: str) -> bool:
        normalized_token = token.strip()
        if not normalized_token:
            return False

        db = self._require_db()
        cursor = await db.execute(
            "SELECT token FROM api_keys WHERE is_active = 1"
        )
        rows = await cursor.fetchall()
        return any(
            secrets.compare_digest(normalized_token, str(row["token"]))
            for row in rows
        )

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ApiKeyStore.initialize() must be called first")
        return self._db

    @staticmethod
    def _serialize_row(row: aiosqlite.Row) -> dict[str, str | bool]:
        return {
            "key_id": str(row["key_id"]),
            "label": str(row["label"]),
            "created_at": str(row["created_at"]),
            "is_active": bool(row["is_active"]),
        }
