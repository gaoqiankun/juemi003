# ruff: noqa: E402

from __future__ import annotations

import asyncio

from cubie.model.base import ModelProviderExecutionError
from cubie.model.gpu import (
    PendingRequest,
    ProcessGPUWorker,
    WorkerProcessConfig,
)


class FakeProcess:
    def __init__(self, *, alive: bool, exitcode: int | None = 0) -> None:
        self.alive = alive
        self.exitcode = exitcode
        self.join_calls: list[float | None] = []
        self.kill_calls = 0

    def is_alive(self) -> bool:
        return self.alive

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)

    def kill(self) -> None:
        self.kill_calls += 1
        self.alive = False


class FakeRequestQueue:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    def put(
        self,
        message: dict[str, object],
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        _ = block
        _ = timeout
        self.messages.append(message)


def build_worker() -> ProcessGPUWorker:
    return ProcessGPUWorker(
        worker_id="gpu-worker-test",
        device_id="0",
        process_config=WorkerProcessConfig(
            provider_name="trellis2",
            model_path="microsoft/TRELLIS.2-4B",
        ),
    )


def test_process_gpu_worker_stop_fails_pending_futures() -> None:
    async def scenario() -> None:
        worker = build_worker()
        request_queue = FakeRequestQueue()
        process = FakeProcess(alive=False, exitcode=0)
        worker._request_queue = request_queue
        worker._process = process

        loop = asyncio.get_running_loop()
        pending_future = loop.create_future()
        worker._pending["req-1"] = PendingRequest(
            future=pending_future,
            progress_cb=None,
        )

        await worker.stop()

        assert request_queue.messages == [{"type": "shutdown"}]
        assert process.join_calls == [1.0]
        assert process.kill_calls == 0
        assert pending_future.done()

        pending_error = pending_future.exception()
        assert isinstance(pending_error, ModelProviderExecutionError)
        assert pending_error.stage_name == "gpu_run"
        assert "worker stopped" in str(pending_error)
        assert worker._pending == {}

    asyncio.run(scenario())
