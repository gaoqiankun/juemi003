from __future__ import annotations

import asyncio
import json
import secrets
import uuid
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite

USER_KEY_SCOPE = "user"
KEY_MANAGER_SCOPE = "key_manager"
TASK_VIEWER_SCOPE = "task_viewer"
METRICS_SCOPE = "metrics"
PRIVILEGED_KEY_SCOPES = (
    KEY_MANAGER_SCOPE,
    TASK_VIEWER_SCOPE,
    METRICS_SCOPE,
)
VALID_API_KEY_SCOPES = (USER_KEY_SCOPE, *PRIVILEGED_KEY_SCOPES)


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
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute("PRAGMA busy_timeout=5000")
        await self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS api_keys (
                key_id TEXT PRIMARY KEY,
                token TEXT UNIQUE NOT NULL,
                label TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'user',
                allowed_ips TEXT,
                created_at TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1
            )
            """
        )
        await self._ensure_column(
            "scope",
            f"TEXT NOT NULL DEFAULT '{USER_KEY_SCOPE}'",
        )
        await self._ensure_column("allowed_ips", "TEXT")
        for col_sql in [
            "ALTER TABLE api_keys ADD COLUMN last_used_at TEXT",
            "ALTER TABLE api_keys ADD COLUMN request_count INTEGER NOT NULL DEFAULT 0",
        ]:
            try:
                await self._db.execute(col_sql)
            except Exception:
                pass  # column already exists
        await self._db.execute(
            "UPDATE api_keys SET scope = ? WHERE scope IS NULL OR TRIM(scope) = ''",
            (USER_KEY_SCOPE,),
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    async def create_key(self, label: str) -> dict[str, str | bool | list[str] | None]:
        return await self.create_user_key(label)

    async def create_user_key(
        self,
        label: str,
    ) -> dict[str, str | bool | list[str] | None]:
        return await self._create_key(
            label=label,
            scope=USER_KEY_SCOPE,
            allowed_ips=None,
        )

    async def create_privileged_key(
        self,
        *,
        label: str,
        scope: str,
        allowed_ips: list[str] | None = None,
    ) -> dict[str, str | bool | list[str] | None]:
        normalized_scope = _normalize_scope(scope)
        if normalized_scope not in PRIVILEGED_KEY_SCOPES:
            raise ValueError("scope must be one of: key_manager, task_viewer, metrics")
        return await self._create_key(
            label=label,
            scope=normalized_scope,
            allowed_ips=allowed_ips,
        )

    async def _create_key(
        self,
        *,
        label: str,
        scope: str,
        allowed_ips: list[str] | None,
    ) -> dict[str, str | bool | list[str] | None]:
        normalized_label = label.strip()
        if not normalized_label:
            raise ValueError("label is required")
        normalized_scope = _normalize_scope(scope)
        normalized_allowed_ips = _normalize_allowed_ips(allowed_ips)

        db = self._require_db()
        async with self._lock:
            for _ in range(5):
                created_at = _utcnow_iso()
                payload = {
                    "key_id": uuid.uuid4().hex,
                    "token": secrets.token_urlsafe(32),
                    "label": normalized_label,
                    "scope": normalized_scope,
                    "allowed_ips": normalized_allowed_ips,
                    "created_at": created_at,
                    "is_active": True,
                }
                try:
                    await db.execute(
                        """
                        INSERT INTO api_keys (
                            key_id,
                            token,
                            label,
                            scope,
                            allowed_ips,
                            created_at,
                            is_active
                        ) VALUES (?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            payload["key_id"],
                            payload["token"],
                            payload["label"],
                            payload["scope"],
                            (
                                json.dumps(payload["allowed_ips"])
                                if payload["allowed_ips"] is not None
                                else None
                            ),
                            payload["created_at"],
                        ),
                    )
                except aiosqlite.IntegrityError:
                    continue
                await db.commit()
                return payload
        raise RuntimeError("failed to generate a unique API key")

    async def list_keys(self) -> list[dict[str, str | bool | list[str] | None]]:
        return await self.list_user_keys()

    async def list_user_keys(self) -> list[dict[str, str | bool | list[str] | None]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT key_id, label, scope, allowed_ips, created_at, is_active, last_used_at, request_count
            FROM api_keys
            WHERE scope = ?
            ORDER BY created_at DESC, key_id DESC
            """,
            (USER_KEY_SCOPE,),
        )
        rows = await cursor.fetchall()
        return [self._serialize_row(row) for row in rows]

    async def list_privileged_keys(
        self,
    ) -> list[dict[str, str | bool | list[str] | None]]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT key_id, label, scope, allowed_ips, created_at, is_active, last_used_at, request_count
            FROM api_keys
            WHERE scope != ?
            ORDER BY created_at DESC, key_id DESC
            """,
            (USER_KEY_SCOPE,),
        )
        rows = await cursor.fetchall()
        return [self._serialize_row(row) for row in rows]

    async def set_active(self, key_id: str, is_active: bool) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE api_keys
                SET is_active = ?
                WHERE key_id = ? AND scope = ?
                """,
                (1 if is_active else 0, key_id, USER_KEY_SCOPE),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def revoke_privileged_key(self, key_id: str) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM api_keys WHERE key_id = ? AND scope != ?",
                (key_id, USER_KEY_SCOPE),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def revoke_user_key(self, key_id: str) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM api_keys WHERE key_id = ? AND scope = ?",
                (key_id, USER_KEY_SCOPE),
            )
            await db.commit()
            return cursor.rowcount > 0

    async def get_key(
        self,
        key_id: str,
    ) -> dict[str, str | bool | list[str] | None] | None:
        return await self.get_user_key(key_id)

    async def get_user_key(
        self,
        key_id: str,
    ) -> dict[str, str | bool | list[str] | None] | None:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT key_id, label, scope, allowed_ips, created_at, is_active, last_used_at, request_count
            FROM api_keys
            WHERE key_id = ? AND scope = ?
            """,
            (key_id, USER_KEY_SCOPE),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return self._serialize_row(row)

    async def validate_token(
        self,
        token: str | None,
        *,
        required_scope: str | None = None,
    ) -> dict[str, str | bool | list[str] | None] | None:
        if token is None:
            return None
        normalized_token = token.strip()
        if not normalized_token:
            return None

        db = self._require_db()
        query = (
            "SELECT key_id, token, label, scope, allowed_ips, created_at, is_active, last_used_at, request_count "
            "FROM api_keys WHERE is_active = 1"
        )
        parameters: tuple[str, ...] = ()
        if required_scope is not None:
            query += " AND scope = ?"
            parameters = (_normalize_scope(required_scope),)
        cursor = await db.execute(query, parameters)
        rows = await cursor.fetchall()
        for row in rows:
            if secrets.compare_digest(normalized_token, str(row["token"])):
                return self._serialize_row(row)
        return None

    async def record_usage(self, key_id: str) -> None:
        db = self._require_db()
        async with self._lock:
            await db.execute(
                "UPDATE api_keys SET request_count = request_count + 1, last_used_at = ? WHERE key_id = ?",
                (_utcnow_iso(), key_id),
            )
            await db.commit()

    async def get_usage_stats(self) -> dict:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT
                COUNT(*) AS total_keys,
                COUNT(CASE WHEN is_active = 1 THEN 1 END) AS active_keys,
                COALESCE(SUM(request_count), 0) AS total_requests
            FROM api_keys
            """
        )
        row = await cursor.fetchone()
        return {
            "total_keys": row["total_keys"],
            "active_keys": row["active_keys"],
            "total_requests": row["total_requests"],
        }

    async def _ensure_column(self, column_name: str, ddl: str) -> None:
        db = self._require_db()
        cursor = await db.execute("PRAGMA table_info(api_keys)")
        columns = {str(row["name"]) for row in await cursor.fetchall()}
        if column_name in columns:
            return
        await db.execute(f"ALTER TABLE api_keys ADD COLUMN {column_name} {ddl}")

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ApiKeyStore.initialize() must be called first")
        return self._db

    @staticmethod
    def _serialize_row(
        row: aiosqlite.Row,
    ) -> dict[str, str | bool | int | list[str] | None]:
        allowed_ips = _deserialize_allowed_ips(row["allowed_ips"])
        result: dict[str, str | bool | int | list[str] | None] = {
            "key_id": str(row["key_id"]),
            "label": str(row["label"]),
            "scope": str(row["scope"]),
            "allowed_ips": allowed_ips,
            "created_at": str(row["created_at"]),
            "is_active": bool(row["is_active"]),
        }
        # Include usage fields when present in the row
        try:
            result["last_used_at"] = row["last_used_at"]
            result["request_count"] = int(row["request_count"])
        except (IndexError, KeyError):
            pass
        return result


def _normalize_scope(raw: str) -> str:
    normalized = raw.strip().lower()
    if normalized not in VALID_API_KEY_SCOPES:
        raise ValueError(
            "scope must be one of: user, key_manager, task_viewer, metrics"
        )
    return normalized


def _normalize_allowed_ips(raw: list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    normalized: list[str] = []
    for item in raw:
        value = str(item).strip()
        if not value:
            raise ValueError("allowed_ips must not contain empty values")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _deserialize_allowed_ips(raw: object) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return None
    else:
        decoded = raw
    if not isinstance(decoded, list):
        return None
    return [str(item) for item in decoded]
