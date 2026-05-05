from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cubie.model.store import ModelStore


class MigrationsMixin:
    def __init__(self, store: ModelStore) -> None:
        self._store = store

    async def ensure_vram_gb_column(self) -> None:
        db = self._store.require_db()
        columns = await self._columns()
        if "vram_gb" not in columns:
            await db.execute("ALTER TABLE model_definitions ADD COLUMN vram_gb REAL")
            await db.execute(
                """
                UPDATE model_definitions
                SET vram_gb = ROUND(CAST(min_vram_mb AS REAL) / 1024.0, 3)
                WHERE vram_gb IS NULL AND min_vram_mb > 0
                """
            )

    async def ensure_vram_split_columns(self) -> None:
        db = self._store.require_db()
        columns = await self._columns()
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

    async def ensure_download_columns(self) -> None:
        db = self._store.require_db()
        columns = await self._columns()
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
            await db.execute("ALTER TABLE model_definitions ADD COLUMN resolved_path TEXT")

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

    async def migrate_trellis2_weight_vram(self) -> None:
        """Fix Trellis2 weight_vram_mb=0 written by the short-lived low_vram seed."""
        db = self._store.require_db()
        await db.execute(
            """
            UPDATE model_definitions
            SET weight_vram_mb = 16000
            WHERE id = 'trellis2' AND weight_vram_mb = 0
            """
        )

    async def _columns(self) -> set[str]:
        db = self._store.require_db()
        async with db.execute("PRAGMA table_info(model_definitions)") as cursor:
            return {str(row["name"]) for row in await cursor.fetchall()}
