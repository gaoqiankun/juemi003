from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path

from cubie.auth.api_key_store import ApiKeyStore
from cubie.model.dep_store import DepInstanceStore
from cubie.model.store import ModelStore
from cubie.task.sequence import RequestSequence, utcnow
from cubie.task.store import TaskStore

ROUND_COUNT = 240


def test_cross_store_parallel_updates_do_not_lock_shared_sqlite_db(
    tmp_path: Path,
) -> None:
    async def _run() -> None:
        db_path = tmp_path / "shared.db"
        task_store = TaskStore(db_path)
        model_store = ModelStore(db_path)
        dep_store = DepInstanceStore(db_path)
        api_key_store = ApiKeyStore(db_path)

        await task_store.initialize()
        await model_store.initialize()
        await dep_store.initialize()
        await api_key_store.initialize()
        try:
            sequence = RequestSequence.new_task(
                model="trellis2",
                input_url="https://example.com/input.png",
                options={},
            )
            await task_store.create_task(sequence)
            await dep_store.create(
                "texture-dep",
                "texture",
                "owner/texture-dep",
                "Texture Dep",
            )
            api_key = await api_key_store.create_user_key("cross-store")
            key_id = str(api_key["key_id"])

            async def _update_task_loop() -> int:
                updates = 0
                for i in range(ROUND_COUNT):
                    sequence.progress = i % 101
                    sequence.updated_at = utcnow()
                    await task_store.update_task(sequence)
                    updates += 1
                    await asyncio.sleep(0)
                return updates

            async def _update_model_loop() -> int:
                updates = 0
                for i in range(ROUND_COUNT):
                    updated = await model_store.update_model(
                        "trellis2",
                        is_enabled=bool(i % 2),
                    )
                    assert updated is not None
                    updates += 1
                    await asyncio.sleep(0)
                return updates

            async def _update_dep_loop() -> int:
                updates = 0
                for i in range(ROUND_COUNT):
                    updated = await dep_store.update_progress(
                        "texture-dep",
                        i % 101,
                        i,
                    )
                    assert updated is not None
                    updates += 1
                    await asyncio.sleep(0)
                return updates

            async def _update_api_key_loop() -> int:
                updates = 0
                for i in range(ROUND_COUNT):
                    updated = await api_key_store.set_active(key_id, bool(i % 2))
                    assert updated is True
                    updates += 1
                    await asyncio.sleep(0)
                return updates

            results = await asyncio.gather(
                _update_task_loop(),
                _update_model_loop(),
                _update_dep_loop(),
                _update_api_key_loop(),
                return_exceptions=True,
            )
            errors = [result for result in results if isinstance(result, Exception)]
            operational_errors = [
                error for error in errors if isinstance(error, sqlite3.OperationalError)
            ]
            assert not operational_errors
            assert not errors
            assert results == [ROUND_COUNT, ROUND_COUNT, ROUND_COUNT, ROUND_COUNT]
        finally:
            await api_key_store.close()
            await dep_store.close()
            await model_store.close()
            await task_store.close()

    asyncio.run(_run())
