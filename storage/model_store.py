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
        "weight_vram_mb": 16000,
        "inference_vram_mb": 8000,
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
        "weight_vram_mb": 16000,
        "inference_vram_mb": 8000,
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
        "weight_vram_mb": 18000,
        "inference_vram_mb": 9000,
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
        "weight_vram_mb",
        "inference_vram_mb",
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
                weight_source TEXT NOT NULL DEFAULT 'huggingface',
                download_status TEXT NOT NULL DEFAULT 'done',
                download_progress INTEGER NOT NULL DEFAULT 100,
                download_speed_bps INTEGER NOT NULL DEFAULT 0,
                download_error TEXT,
                resolved_path TEXT,
                is_enabled INTEGER NOT NULL DEFAULT 1,
                is_default INTEGER NOT NULL DEFAULT 0,
                min_vram_mb INTEGER NOT NULL DEFAULT 24000,
                vram_gb REAL,
                weight_vram_mb INTEGER,
                inference_vram_mb INTEGER,
                config_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        await self._ensure_vram_gb_column()
        await self._ensure_vram_split_columns()
        await self._ensure_download_columns()
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
                         weight_source, download_status, download_progress,
                         resolved_path,
                         is_enabled, is_default, min_vram_mb, vram_gb,
                         weight_vram_mb, inference_vram_mb, config_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        seed["id"],
                        seed["provider_type"],
                        seed["display_name"],
                        seed["model_path"],
                        "huggingface",
                        "pending",
                        0,
                        None,
                        seed["is_enabled"],
                        seed["is_default"],
                        seed["min_vram_mb"],
                        seed["vram_gb"],
                        seed["weight_vram_mb"],
                        seed["inference_vram_mb"],
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

    async def list_models(
        self,
        *,
        include_pending: bool = False,
        extra_statuses: frozenset[str] = frozenset(),
    ) -> list[dict]:
        db = self._require_db()
        if include_pending:
            cursor = await db.execute(
                "SELECT * FROM model_definitions ORDER BY created_at"
            )
        elif extra_statuses:
            placeholders = ", ".join("?" * (1 + len(extra_statuses)))
            cursor = await db.execute(
                f"SELECT * FROM model_definitions WHERE download_status IN ({placeholders}) ORDER BY created_at",
                tuple(["done", *sorted(extra_statuses)]),
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM model_definitions
                WHERE download_status = 'done'
                ORDER BY created_at
                """
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

    async def get_enabled_models(
        self,
        *,
        include_pending: bool = False,
        extra_statuses: frozenset[str] = frozenset(),
    ) -> list[dict]:
        db = self._require_db()
        if include_pending:
            cursor = await db.execute(
                "SELECT * FROM model_definitions WHERE is_enabled = 1 ORDER BY created_at"
            )
        elif extra_statuses:
            placeholders = ", ".join("?" * (1 + len(extra_statuses)))
            cursor = await db.execute(
                f"SELECT * FROM model_definitions WHERE is_enabled = 1 AND download_status IN ({placeholders}) ORDER BY created_at",
                tuple(["done", *sorted(extra_statuses)]),
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM model_definitions
                WHERE is_enabled = 1 AND download_status = 'done'
                ORDER BY created_at
                """
            )
        rows = await cursor.fetchall()
        return [_row_to_dict(r) for r in rows]

    async def count_ready_models(self) -> int:
        db = self._require_db()
        cursor = await db.execute(
            "SELECT COUNT(*) AS cnt FROM model_definitions WHERE download_status = 'done'"
        )
        row = await cursor.fetchone()
        return int(row["cnt"])

    async def get_all_resolved_paths(self) -> list[str]:
        db = self._require_db()
        cursor = await db.execute(
            """
            SELECT resolved_path FROM model_definitions
            WHERE weight_source != 'local' AND resolved_path IS NOT NULL
            """
        )
        rows = await cursor.fetchall()
        return [str(row["resolved_path"]) for row in rows if row["resolved_path"]]

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
        weight_source: str = "huggingface",
        download_status: str = "done",
        download_progress: int = 100,
        download_speed_bps: int = 0,
        download_error: str | None = None,
        resolved_path: str | None = None,
        min_vram_mb: int = 24000,
        vram_gb: float | None = None,
        weight_vram_mb: int | None = None,
        inference_vram_mb: int | None = None,
        config: dict | None = None,
    ) -> dict:
        db = self._require_db()
        now = _utcnow_iso()
        config_json = json.dumps(config or {})
        normalized_vram_gb = _normalize_vram_gb(vram_gb)
        normalized_weight_vram_mb = _normalize_optional_vram_mb(weight_vram_mb)
        normalized_inference_vram_mb = _normalize_optional_vram_mb(inference_vram_mb)
        normalized_weight_source = _normalize_weight_source(weight_source)
        normalized_download_status = _normalize_download_status(download_status)
        normalized_download_progress = _normalize_download_progress(download_progress)
        normalized_download_speed_bps = _normalize_download_speed_bps(download_speed_bps)
        normalized_download_error = _normalize_optional_text(download_error)
        normalized_resolved_path = _normalize_optional_text(resolved_path)
        async with self._lock:
            try:
                await db.execute(
                    """
                    INSERT INTO model_definitions
                        (id, provider_type, display_name, model_path,
                         weight_source, download_status, download_progress,
                         download_speed_bps, download_error, resolved_path,
                         is_enabled, is_default, min_vram_mb, vram_gb,
                         weight_vram_mb, inference_vram_mb, config_json,
                         created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        id,
                        provider_type,
                        display_name,
                        model_path,
                        normalized_weight_source,
                        normalized_download_status,
                        normalized_download_progress,
                        normalized_download_speed_bps,
                        normalized_download_error,
                        normalized_resolved_path,
                        min_vram_mb,
                        normalized_vram_gb,
                        normalized_weight_vram_mb,
                        normalized_inference_vram_mb,
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
                elif key in {"weight_vram_mb", "inference_vram_mb"}:
                    set_clauses.append(f"{key} = ?")
                    params.append(_normalize_optional_vram_mb(value))
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

    async def update_download_progress(
        self,
        model_id: str,
        progress: int,
        speed_bps: int,
    ) -> dict | None:
        db = self._require_db()
        normalized_progress = _normalize_download_progress(progress)
        normalized_speed_bps = _normalize_download_speed_bps(speed_bps)
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE model_definitions
                SET
                    download_status = 'downloading',
                    download_progress = ?,
                    download_speed_bps = ?,
                    download_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_progress,
                    normalized_speed_bps,
                    _utcnow_iso(),
                    model_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get_model(model_id)

    async def update_download_done(
        self,
        model_id: str,
        resolved_path: str,
    ) -> dict | None:
        db = self._require_db()
        normalized_resolved_path = _normalize_optional_text(resolved_path)
        if normalized_resolved_path is None:
            raise ValueError("resolved_path is required when marking download as done")
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE model_definitions
                SET
                    download_status = 'done',
                    download_progress = 100,
                    download_speed_bps = 0,
                    download_error = NULL,
                    resolved_path = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_resolved_path,
                    _utcnow_iso(),
                    model_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get_model(model_id)

    async def update_download_error(
        self,
        model_id: str,
        error_message: str,
    ) -> dict | None:
        db = self._require_db()
        normalized_error = _normalize_optional_text(error_message) or "download failed"
        async with self._lock:
            cursor = await db.execute(
                """
                UPDATE model_definitions
                SET
                    download_status = 'error',
                    download_speed_bps = 0,
                    download_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    normalized_error,
                    _utcnow_iso(),
                    model_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            await db.commit()
        return await self.get_model(model_id)

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

    async def _ensure_vram_split_columns(self) -> None:
        db = self._require_db()
        cursor = await db.execute("PRAGMA table_info(model_definitions)")
        columns = {str(row["name"]) for row in await cursor.fetchall()}
        if "weight_vram_mb" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN weight_vram_mb INTEGER"
            )
        if "inference_vram_mb" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN inference_vram_mb INTEGER"
            )

        await db.execute(
            """
            UPDATE model_definitions
            SET weight_vram_mb = CAST(
                ROUND(
                    CASE
                        WHEN min_vram_mb > 0 THEN min_vram_mb * 0.75
                        WHEN vram_gb IS NOT NULL AND vram_gb > 0 THEN vram_gb * 1024.0 * 0.75
                        ELSE 0
                    END
                ) AS INTEGER
            )
            WHERE weight_vram_mb IS NULL
            """
        )
        await db.execute(
            """
            UPDATE model_definitions
            SET inference_vram_mb = MAX(
                COALESCE(
                    CAST(
                        ROUND(
                            CASE
                                WHEN min_vram_mb > 0 THEN min_vram_mb
                                WHEN vram_gb IS NOT NULL AND vram_gb > 0 THEN vram_gb * 1024.0
                                ELSE 0
                            END
                        ) AS INTEGER
                    ),
                    0
                ) - COALESCE(weight_vram_mb, 0),
                1
            )
            WHERE inference_vram_mb IS NULL
            """
        )

    async def _ensure_download_columns(self) -> None:
        db = self._require_db()
        cursor = await db.execute("PRAGMA table_info(model_definitions)")
        columns = {str(row["name"]) for row in await cursor.fetchall()}
        if "weight_source" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN weight_source TEXT NOT NULL DEFAULT 'huggingface'"
            )
        if "download_status" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN download_status TEXT NOT NULL DEFAULT 'done'"
            )
        if "download_progress" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN download_progress INTEGER NOT NULL DEFAULT 100"
            )
        if "download_speed_bps" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN download_speed_bps INTEGER NOT NULL DEFAULT 0"
            )
        if "download_error" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN download_error TEXT"
            )
        if "resolved_path" not in columns:
            await db.execute(
                "ALTER TABLE model_definitions ADD COLUMN resolved_path TEXT"
            )

        await db.execute(
            """
            UPDATE model_definitions
            SET weight_source = 'huggingface'
            WHERE weight_source IS NULL OR TRIM(weight_source) = ''
            """
        )
        await db.execute(
            """
            UPDATE model_definitions
            SET download_status = 'done'
            WHERE download_status IS NULL OR TRIM(download_status) = ''
            """
        )
        await db.execute(
            """
            UPDATE model_definitions
            SET download_progress = 100
            WHERE download_progress IS NULL
            """
        )
        await db.execute(
            """
            UPDATE model_definitions
            SET download_speed_bps = 0
            WHERE download_speed_bps IS NULL
            """
        )

    def _require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ModelStore.initialize() must be called first")
        return self._db


def _row_to_dict(row: aiosqlite.Row) -> dict:
    config = json.loads(row["config_json"]) if row["config_json"] else {}
    vram_gb = _normalize_vram_gb(row["vram_gb"])
    weight_vram_mb = _normalize_optional_vram_mb(row["weight_vram_mb"])
    inference_vram_mb = _normalize_optional_vram_mb(row["inference_vram_mb"])
    weight_source = _normalize_weight_source(row["weight_source"])
    download_status = _normalize_download_status(row["download_status"])
    download_progress = _normalize_download_progress(row["download_progress"])
    download_speed_bps = _normalize_download_speed_bps(row["download_speed_bps"])
    download_error = _normalize_optional_text(row["download_error"])
    resolved_path = _normalize_optional_text(row["resolved_path"])
    return {
        "id": str(row["id"]),
        "provider_type": str(row["provider_type"]),
        "display_name": str(row["display_name"]),
        "model_path": str(row["model_path"]),
        "weight_source": weight_source,
        "download_status": download_status,
        "download_progress": download_progress,
        "download_speed_bps": download_speed_bps,
        "download_error": download_error,
        "resolved_path": resolved_path,
        "is_enabled": bool(row["is_enabled"]),
        "is_default": bool(row["is_default"]),
        "min_vram_mb": int(row["min_vram_mb"]),
        "vram_gb": vram_gb,
        "weight_vram_mb": weight_vram_mb,
        "inference_vram_mb": inference_vram_mb,
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


def _normalize_optional_vram_mb(value: object) -> int | None:
    if value is None:
        return None
    try:
        normalized = int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if normalized <= 0:
        return None
    return normalized


def _normalize_weight_source(value: object) -> str:
    normalized = str(value or "huggingface").strip().lower()
    if normalized not in {"huggingface", "url", "local"}:
        return "huggingface"
    return normalized


def _normalize_download_status(value: object) -> str:
    normalized = str(value or "done").strip().lower()
    if normalized not in {"pending", "downloading", "done", "error"}:
        return "done"
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


def _normalize_optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None
