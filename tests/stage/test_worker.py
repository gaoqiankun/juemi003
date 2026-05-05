# ruff: noqa: E402

from __future__ import annotations

import asyncio
import queue

from cubie.model.base import ModelProviderExecutionError
from cubie.model.gpu import (
    AsyncGPUWorker,
    PendingRequest,
    ProcessGPUWorker,
    WorkerProcessConfig,
)


class FakeProcess:
    def __init__(self, *, alive: bool, exitcode: int | None = None) -> None:
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


class EmptyResponseQueue:
    def __init__(self) -> None:
        self.timeouts: list[float | None] = []

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> dict[str, object]:
        self.timeouts.append(timeout)
        raise queue.Empty


class ShutdownRequestQueue:
    def __init__(
        self,
        *,
        response_queue: queue.Queue[dict[str, object]],
        process: FakeProcess,
    ) -> None:
        self.messages: list[dict[str, object]] = []
        self._response_queue = response_queue
        self._process = process

    def put(
        self,
        message: dict[str, object],
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        self.messages.append(message)
        if message.get("type") == "shutdown":
            self._process.alive = False
            self._response_queue.put({"type": "stopped"})


def build_worker() -> ProcessGPUWorker:
    return ProcessGPUWorker(
        worker_id="gpu-worker-test",
        device_id="0",
        process_config=WorkerProcessConfig(
            provider_name="trellis2",
            model_path="microsoft/TRELLIS.2-4B",
        ),
    )


def test_process_gpu_worker_rejects_pending_futures_when_child_process_dies() -> None:
    async def scenario() -> None:
        worker = build_worker()
        worker._process = FakeProcess(alive=False, exitcode=137)
        worker._response_queue = EmptyResponseQueue()

        loop = asyncio.get_running_loop()
        worker._startup_future = loop.create_future()
        pending_future = loop.create_future()
        worker._pending["req-1"] = PendingRequest(
            future=pending_future,
            progress_cb=None,
        )

        pump_task = asyncio.create_task(worker.pump_responses())
        await asyncio.wait_for(pump_task, timeout=0.5)

        assert worker._response_queue.timeouts == [1.0]
        assert worker._pending == {}
        assert pump_task.done()
        assert pump_task.cancelled() is False

        startup_error = worker._startup_future.exception()
        assert isinstance(startup_error, ModelProviderExecutionError)
        assert startup_error.stage_name == "gpu_run"
        assert str(startup_error) == (
            "GPU worker process gpu-worker-test exited unexpectedly (exitcode=137)"
        )

        pending_error = pending_future.exception()
        assert isinstance(pending_error, ModelProviderExecutionError)
        assert pending_error.stage_name == "gpu_run"
        assert str(pending_error) == str(startup_error)

    asyncio.run(scenario())


def test_process_gpu_worker_stop_waits_for_clean_shutdown() -> None:
    async def scenario() -> None:
        worker = build_worker()
        response_queue: queue.Queue[dict[str, object]] = queue.Queue()
        process = FakeProcess(alive=True, exitcode=0)
        request_queue = ShutdownRequestQueue(
            response_queue=response_queue,
            process=process,
        )

        worker._process = process
        worker._request_queue = request_queue
        worker._response_queue = response_queue
        startup_future = asyncio.get_running_loop().create_future()
        startup_future.set_result(None)
        worker._startup_future = startup_future

        response_task = asyncio.create_task(worker.pump_responses())
        worker._response_task = response_task

        await worker.stop()

        assert request_queue.messages == [{"type": "shutdown"}]
        assert process.join_calls == [1.0]
        assert process.kill_calls == 0
        assert response_task.done()
        assert response_task.cancelled() is False
        assert worker._process is None
        assert worker._response_task is None
        assert worker._startup_future is None
        assert worker._pending == {}

    asyncio.run(scenario())


def test_async_gpu_worker_startup_weight_mb_is_none() -> None:
    class FakeProvider:
        async def run_batch(self, images, options, progress_cb):  # noqa: ANN001
            _ = images
            _ = options
            _ = progress_cb
            return []

    worker = AsyncGPUWorker(
        worker_id="gpu-worker-test",
        device_id="0",
        provider=FakeProvider(),  # type: ignore[arg-type]
    )
    assert worker.startup_weight_mb is None
