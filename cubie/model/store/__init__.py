from __future__ import annotations

import asyncio
from pathlib import Path

import aiosqlite

from cubie.model.store.migrations import MigrationsMixin
from cubie.model.store.mutations import MutationsMixin
from cubie.model.store.normalize import (
    normalize_download_progress,
    normalize_download_speed_bps,
    normalize_download_status,
    normalize_optional_text,
    normalize_optional_vram_mb,
    normalize_vram_gb,
    normalize_weight_source,
    row_to_dict,
    utcnow_iso,
)
from cubie.model.store.queries import QueriesMixin

__all__ = (
    "ModelStore",
    "normalize_download_progress",
    "normalize_download_speed_bps",
    "normalize_download_status",
    "normalize_optional_text",
    "normalize_optional_vram_mb",
    "normalize_vram_gb",
    "normalize_weight_source",
    "row_to_dict",
    "utcnow_iso",
)


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


class ModelStore:
    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None
        self._lock = asyncio.Lock()
        self._queries = QueriesMixin(self)
        self._mutations = MutationsMixin(self)
        self._migrations = MigrationsMixin(self)

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
        await self.ensure_vram_gb_column()
        await self.ensure_vram_split_columns()
        await self.ensure_download_columns()
        await self.migrate_trellis2_weight_vram()
        await self._db.commit()

        async with self._db.execute(
            "SELECT COUNT(*) AS cnt FROM model_definitions"
        ) as cursor:
            row = await cursor.fetchone()
        if row["cnt"] == 0:
            now = utcnow_iso()
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

    async def list_models(
        self,
        *,
        include_pending: bool = False,
        extra_statuses: frozenset[str] = frozenset(),
    ) -> list[dict]:
        return await self._queries.list_models(
            include_pending=include_pending,
            extra_statuses=extra_statuses,
        )

    async def get_model(self, model_id: str) -> dict | None:
        return await self._queries.get_model(model_id)

    async def get_default_model(self) -> dict | None:
        return await self._queries.get_default_model()

    async def get_enabled_models(
        self,
        *,
        include_pending: bool = False,
        extra_statuses: frozenset[str] = frozenset(),
    ) -> list[dict]:
        return await self._queries.get_enabled_models(
            include_pending=include_pending,
            extra_statuses=extra_statuses,
        )

    async def count_ready_models(self) -> int:
        return await self._queries.count_ready_models()

    async def get_all_resolved_paths(self) -> list[str]:
        return await self._queries.get_all_resolved_paths()

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
        return await self._mutations.create_model(
            id=id,
            provider_type=provider_type,
            display_name=display_name,
            model_path=model_path,
            weight_source=weight_source,
            download_status=download_status,
            download_progress=download_progress,
            download_speed_bps=download_speed_bps,
            download_error=download_error,
            resolved_path=resolved_path,
            min_vram_mb=min_vram_mb,
            vram_gb=vram_gb,
            weight_vram_mb=weight_vram_mb,
            inference_vram_mb=inference_vram_mb,
            config=config,
        )

    async def update_model(self, model_id: str, **updates: object) -> dict | None:
        return await self._mutations.update_model(model_id, **updates)

    async def delete_model(self, model_id: str) -> bool:
        return await self._mutations.delete_model(model_id)

    async def update_download_progress(
        self,
        model_id: str,
        progress: int,
        speed_bps: int,
    ) -> dict | None:
        return await self._mutations.update_download_progress(
            model_id,
            progress,
            speed_bps,
        )

    async def update_download_done(
        self,
        model_id: str,
        resolved_path: str,
    ) -> dict | None:
        return await self._mutations.update_download_done(model_id, resolved_path)

    async def update_download_error(
        self,
        model_id: str,
        error_message: str,
    ) -> dict | None:
        return await self._mutations.update_download_error(model_id, error_message)

    async def ensure_vram_gb_column(self) -> None:
        await self._migrations.ensure_vram_gb_column()

    async def ensure_vram_split_columns(self) -> None:
        await self._migrations.ensure_vram_split_columns()

    async def ensure_download_columns(self) -> None:
        await self._migrations.ensure_download_columns()

    async def migrate_trellis2_weight_vram(self) -> None:
        await self._migrations.migrate_trellis2_weight_vram()

    def require_db(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("ModelStore.initialize() must be called first")
        return self._db
