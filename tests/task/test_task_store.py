from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from cubie.model.store import ModelStore
from cubie.task.sequence import TaskStatus
from cubie.task.store import TaskStore, serialize_datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _make_store(db_path: Path) -> TaskStore:
    s = TaskStore(db_path)
    await s.initialize()
    return s


async def _make_model_store(db_path: Path) -> ModelStore:
    s = ModelStore(db_path)
    await s.initialize()
    return s


async def _insert_task(
    store: TaskStore,
    *,
    task_id: str,
    status: str,
    model: str = "trellis",
    created_at: datetime | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    deleted_at: datetime | None = None,
    key_id: str | None = None,
    error_message: str | None = None,
) -> None:
    now = created_at or _now()
    db = store.require_db()
    await db.execute(
        """
        INSERT INTO tasks (
            id, status, type, model, input_url, options_json,
            output_artifacts_json, progress, retry_count, cleanup_done,
            created_at, started_at, completed_at, updated_at, deleted_at,
            key_id, error_message
        ) VALUES (?, ?, 'image_to_3d', ?, 'https://example.com/img.png', '{}',
                  '[]', 0, 0, 0, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            task_id,
            status,
            model,
            serialize_datetime(now),
            serialize_datetime(started_at),
            serialize_datetime(completed_at),
            serialize_datetime(now),
            serialize_datetime(deleted_at),
            key_id,
            error_message,
        ),
    )
    await db.commit()


# ---------- count_tasks_by_status ----------


def test_count_tasks_by_status_empty() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            store = await _make_store(Path(tmp) / "test.db")
            try:
                result = await store.count_tasks_by_status()
                assert isinstance(result, dict)
                for s in TaskStatus:
                    assert result.get(s.value, -1) == 0
            finally:
                await store.close()

    asyncio.run(_run())


def test_count_tasks_by_status_with_data() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            store = await _make_store(Path(tmp) / "test.db")
            try:
                await _insert_task(store, task_id="t1", status="queued")
                await _insert_task(store, task_id="t2", status="queued")
                await _insert_task(store, task_id="t3", status="succeeded")
                await _insert_task(store, task_id="t4", status="failed")
                # Soft-deleted should not be counted
                await _insert_task(store, task_id="t5", status="queued", deleted_at=_now())

                result = await store.count_tasks_by_status()
                assert result["queued"] == 2
                assert result["succeeded"] == 1
                assert result["failed"] == 1
            finally:
                await store.close()

    asyncio.run(_run())


# ---------- get_recent_tasks ----------


def test_get_recent_tasks_ordering() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            store = await _make_store(Path(tmp) / "test.db")
            try:
                base = _now()
                for i in range(5):
                    await _insert_task(
                        store,
                        task_id=f"t{i}",
                        status="queued",
                        created_at=base + timedelta(seconds=i),
                    )
                # Soft-deleted should be excluded
                await _insert_task(
                    store,
                    task_id="t_deleted",
                    status="queued",
                    created_at=base + timedelta(seconds=100),
                    deleted_at=_now(),
                )

                tasks = await store.get_recent_tasks(limit=3)
                assert len(tasks) == 3
                # Most recent first
                assert tasks[0]["id"] == "t4"
                assert tasks[1]["id"] == "t3"
                assert tasks[2]["id"] == "t2"
                # Verify dict keys
                assert "status" in tasks[0]
                assert "model" in tasks[0]
                assert "error_message" in tasks[0]
            finally:
                await store.close()

    asyncio.run(_run())


# ---------- get_throughput_stats ----------


def test_get_throughput_stats() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            store = await _make_store(Path(tmp) / "test.db")
            try:
                now = _now()
                # Two succeeded tasks with known durations
                await _insert_task(
                    store,
                    task_id="s1",
                    status="succeeded",
                    started_at=now - timedelta(minutes=10),
                    completed_at=now - timedelta(minutes=5),
                )
                await _insert_task(
                    store,
                    task_id="s2",
                    status="succeeded",
                    started_at=now - timedelta(minutes=20),
                    completed_at=now - timedelta(minutes=10),
                )
                # One failed task
                await _insert_task(
                    store,
                    task_id="f1",
                    status="failed",
                    completed_at=now - timedelta(minutes=2),
                )
                # Old task outside 1-hour window
                await _insert_task(
                    store,
                    task_id="old",
                    status="succeeded",
                    started_at=now - timedelta(hours=3),
                    completed_at=now - timedelta(hours=2),
                )

                stats = await store.get_throughput_stats(hours=1)
                assert stats["completed_count"] == 2
                assert stats["failed_count"] == 1
                assert stats["avg_duration_seconds"] is not None
                # Both succeeded tasks had 5min and 10min durations -> avg ~450s
                assert 400 < stats["avg_duration_seconds"] < 500
            finally:
                await store.close()

    asyncio.run(_run())


# ---------- get_active_task_count ----------


def test_get_active_task_count() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            store = await _make_store(Path(tmp) / "test.db")
            try:
                await _insert_task(store, task_id="a1", status="queued")
                await _insert_task(store, task_id="a2", status="preprocessing")
                await _insert_task(store, task_id="a3", status="gpu_queued")
                # Terminal statuses should NOT be counted
                await _insert_task(store, task_id="a4", status="succeeded")
                await _insert_task(store, task_id="a5", status="failed")
                await _insert_task(store, task_id="a6", status="cancelled")
                # Soft-deleted should NOT be counted
                await _insert_task(store, task_id="a7", status="queued", deleted_at=_now())

                count = await store.get_active_task_count()
                assert count == 3
            finally:
                await store.close()

    asyncio.run(_run())


def test_get_oldest_queued_task_time_by_model() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            store = await _make_store(Path(tmp) / "test.db")
            try:
                base = _now()
                await _insert_task(
                    store,
                    task_id="q-a-1",
                    status="queued",
                    model="trellis2",
                    created_at=base + timedelta(seconds=20),
                )
                await _insert_task(
                    store,
                    task_id="q-a-0",
                    status="queued",
                    model="trellis2",
                    created_at=base + timedelta(seconds=10),
                )
                await _insert_task(
                    store,
                    task_id="q-b-0",
                    status="queued",
                    model="hunyuan3d",
                    created_at=base + timedelta(seconds=30),
                )
                await _insert_task(
                    store,
                    task_id="not-queued",
                    status="preprocessing",
                    model="step1x3d",
                    created_at=base,
                )
                await _insert_task(
                    store,
                    task_id="queued-deleted",
                    status="queued",
                    model="step1x3d",
                    created_at=base,
                    deleted_at=base + timedelta(seconds=1),
                )

                oldest = await store.get_oldest_queued_task_time_by_model()
                assert oldest["trellis2"] == serialize_datetime(base + timedelta(seconds=10))
                assert oldest["hunyuan3d"] == serialize_datetime(base + timedelta(seconds=30))
                assert "step1x3d" not in oldest
            finally:
                await store.close()

    asyncio.run(_run())


def test_claim_next_queued_task_with_model_store_concurrency_no_locked_error() -> None:
    async def _run() -> None:
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "shared.db"
            task_store = await _make_store(db_path)
            model_store = await _make_model_store(db_path)
            try:
                task_count = 120
                for i in range(task_count):
                    await _insert_task(
                        task_store,
                        task_id=f"queued-{i:03d}",
                        status=TaskStatus.QUEUED.value,
                        created_at=_now() + timedelta(milliseconds=i),
                    )

                async def _claim_worker(worker_id: str) -> list[str]:
                    claimed: list[str] = []
                    while True:
                        sequence = await task_store.claim_next_queued_task(worker_id)
                        if sequence is None:
                            return claimed
                        claimed.append(sequence.task_id)
                        await asyncio.sleep(0)

                async def _update_model_loop() -> int:
                    updates = 0
                    for i in range(240):
                        updated = await model_store.update_model(
                            "trellis2",
                            is_enabled=bool(i % 2),
                        )
                        assert updated is not None
                        updates += 1
                        await asyncio.sleep(0)
                    return updates

                results = await asyncio.gather(
                    _claim_worker("worker-a"),
                    _claim_worker("worker-b"),
                    _update_model_loop(),
                    return_exceptions=True,
                )
                errors = [result for result in results if isinstance(result, Exception)]
                assert not errors

                claimed_ids = [task_id for result in results[:2] for task_id in result]
                assert len(claimed_ids) == task_count
                assert len(set(claimed_ids)) == task_count
                assert await task_store.count_queued_tasks() == 0
            finally:
                await model_store.close()
                await task_store.close()

    asyncio.run(_run())
