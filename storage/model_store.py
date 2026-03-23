from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite


def _utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


_SEED_MODELS = [
    {
        "id": "trellis2",
        "provider_type": "trellis2",
        "display_name": "TRELLIS2",
        "model_path": "microsoft/TRELLIS.2-4B",
        "is_enabled": 1,
        "is_default": 1,
        "min_vram_mb": 24000,
        "vram_gb": 24.0,
        "config_json": "{}",
    },
    {
        "id": "hunyuan3d",
        "provider_type": "hunyuan3d",
        "display_name": "HunYuan3D-2",
        "model_path": "tencent/Hunyuan3D-2",
        "is_enabled": 0,
        "is_default": 0,
        "min_vram_mb": 24000,
        "vram_gb": 24.0,
        "config_json": "{}",
    },
    {
        "id": "step1x3d",
        "provider_type": "step1x3d",
        "display_name": "Step1X-3D",
        "model_path": "stepfun-ai/Step1X-3D",
        "is_enabled": 0,
        "is_default": 0,
        "min_vram_mb": 27000,
        "vram_gb": 27.0,
        "config_json": "{}",
    },
]

_UPDATABLE_FIELDS = frozenset(
    {
        "is_enabled",
        "is_default",
        "display_name",
        "model_path",
        "min_vram_mb",
        "vram_gb",
        "config",
    }
)


class ModelStore:
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
            CREATE TABLE IF NOT EXISTS model_definitions (
                id TEXT PRIMARY KEY,
                provider_type TEXT NOT NULL,
                display_name TEXT NOT NULL,
                model_path TEXT NOT NULL,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                min_vram_mb INTEGER NOT NULL DEFAULT 24000,
                vram_gb REAL,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._ensure_vram_gb_column()
        await self._db.commit()

        # Seed defaults if table is empty.
        cursor = await self._db.execute(
            "SELECT COUNT(*) AS cnt FROM model_definitions"
        )
        row = await cursor.fetchone()
        if row["cnt"] == 0:
            now = _utcnow_iso()
            for seed in _SEED_MODELS:
                await self._db.execute(
                    """
                    INSERT INTO model_definitions
                        (id, provider_type, display_name, model_path,
                         is_enabled, is_default, min_vram_mb, vram_gb, config_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seed["id"],
                        seed["provider_type"],
                        seed["display_name"],
                        seed["model_path"],
                        seed["is_enabled"],
                        seed["is_default"],
                        seed["min_vram_mb"],
                        seed["vram_gb"],
                        seed["config_json"],
                        now,
                        now,
                    ),
                )
            await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def list_models(self) -> list[dict]:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM model_definitions ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def get_model(self, model_id: str) -> dict | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM model_definitions WHERE id = ?", (model_id,)
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def get_default_model(self) -> dict | None:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM model_definitions WHERE is_default = 1 LIMIT 1"
        )
        row = await cursor.fetchone()
        return _row_to_dict(row) if row else None

    async def get_enabled_models(self) -> list[dict]:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT * FROM model_definitions WHERE is_enabled = 1 ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    async def create_model(
        self,
        *,
        id: str,
        provider_type: str,
        display_name: str,
        model_path: str,
        min_vram_mb: int = 24000,
        vram_gb: float | None = None,
        config: dict | None = None,
    ) -> dict:
        db = self._require_db()
        now = _utcnow_iso()
        config_json = json.dumps(config or {})
        normalized_vram_gb = _normalize_vram_gb(vram_gb)
        async with self._lock:
            try:
                await db.execute(
                    """
                    INSERT INTO model_definitions
                        (id, provider_type, display_name, model_path,
                         is_enabled, is_default, min_vram_mb, vram_gb, config_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?)
                    """,
                    (
                        id,
                        provider_type,
                        display_name,
                        model_path,
                        min_vram_mb,
                        normalized_vram_gb,
                        config_json,
                        now,
                        now,
                    ),
                )
            except aiosqlite.IntegrityError:
                raise ValueError(f"model with id '{id}' already exists")
            await db.commit()
        return (await self.get_model(id))  # type: ignore[return-value]

    async def update_model(self, model_id: str, **updates: object) -> dict | None:
        invalid = set(updates) - _UPDATABLE_FIELDS
        if invalid:
            raise ValueError(f"invalid update fields: {invalid}")
        if not updates:
            return await self.get_model(model_id)

        db = self._require_db()
        async with self._lock:
            # If setting is_default=True, clear other defaults first.
            if updates.get("is_default") is True:
                await db.execute(
                    "UPDATE model_definitions SET is_default = 0 WHERE is_default = 1"
                )

            set_clauses: list[str] = []
            params: list[object] = []
            for key, value in updates.items():
                if key == "config":
                    set_clauses.append("config_json = ?")
                    params.append(json.dumps(value or {}))
                elif key == "vram_gb":
                    set_clauses.append("vram_gb = ?")
                    params.append(_normalize_vram_gb(value))
                elif key in ("is_enabled", "is_default"):
                    set_clauses.append(f"{key} = ?")
                    params.append(1 if value else 0)
                else:
                    set_clauses.append(f"{key} = ?")
                    params.append(value)

            set_clauses.append("updated_at = ?")
            params.append(_utcnow_iso())
            params.append(model_id)

            cursor = await db.execute(
                f"UPDATE model_definitions SET {', '.join(set_clauses)} WHERE id = ?",
                params,
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get_model(model_id)

    async def delete_model(self, model_id: str) -> bool:
        db = self._require_db()
        async with self._lock:
            cursor = await db.execute(
                "DELETE FROM model_definitions WHERE id = ?", (model_id,)
            )
            await db.commit()
            return cursor.rowcount > 0

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    async def _ensure_vram_gb_column(self) -> None:
        db = self._require_db()
        cursor = await db.execute("PRAGMA table_info(model_definitions)")
        columns = {str(row["name"]) for row in await cursor.fetchall()}
        if "vram_gb" not in columns:
            await db.execute("ALTER TABLE model_definitions ADD COLUMN vram_gb REAL")
            await db.execute(
                """
                UPDATE model_definitions
                SET vram_gb = ROUND(CAST(min_vram_mb AS REAL) / 1024.0, 3)
                WHERE vram_gb IS NULL AND min_vram_mb > 0
                """
            )

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ModelStore.initialize() must be called first")
        return self._db


def _row_to_dict(row: aiosqlite.Row) -> dict:
    config = json.loads(row["config_json"]) if row["config_json"] else {}
    vram_gb = _normalize_vram_gb(row["vram_gb"])
    return {
        "id": str(row["id"]),
        "provider_type": str(row["provider_type"]),
        "display_name": str(row["display_name"]),
        "model_path": str(row["model_path"]),
        "is_enabled": bool(row["is_enabled"]),
        "is_default": bool(row["is_default"]),
        "min_vram_mb": int(row["min_vram_mb"]),
        "vram_gb": vram_gb,
        "config": config,
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _normalize_vram_gb(value: object) -> float | None:
    if value is None:
        return None
    try:
        normalized = float(value)
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return round(normalized, 3)
