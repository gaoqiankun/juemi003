# ruff: noqa: E402

from __future__ import annotations

import asyncio
import queue
import sys
import threading
import types
from pathlib import Path

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from gen3d.stages.gpu import worker as worker_module
from gen3d.stages.gpu.worker import (
    PendingRequest,
    ProcessGPUWorker,
    WorkerProcessConfig,
    worker_process_main,
)


class FakeProcess:
    def __init__(self) -> None:
        self.alive = True
        self.exitcode = 0

    def is_alive(self) -> bool:
        return self.alive


def _build_worker(
    *,
    measurement_callback=None,
) -> ProcessGPUWorker:
    return ProcessGPUWorker(
        worker_id="gpu-worker-test",
        device_id="0",
        model_name="trellis2",
        process_config=WorkerProcessConfig(
            provider_name="trellis2",
            model_path="microsoft/TRELLIS.2-4B",
        ),
        measurement_callback=measurement_callback,
    )


def test_worker_process_main_reports_inference_peak_mb(
    monkeypatch,
) -> None:
    class FakeProvider:
        async def run_batch(self, images, options, progress_cb):  # noqa: ANN001
            _ = images
            _ = options
            _ = progress_cb
            return ["ok"]

    class FakeCuda:
        @staticmethod
        def is_available() -> bool:
            return True

        @staticmethod
        def memory_reserved(device):  # noqa: ANN001
            _ = device
            return 6144 * 1024 * 1024

        @staticmethod
        def memory_allocated(device):  # noqa: ANN001
            _ = device
            return 4096 * 1024 * 1024

        @staticmethod
        def reset_peak_memory_stats(device):  # noqa: ANN001
            _ = device

        @staticmethod
        def max_memory_allocated(device):  # noqa: ANN001
            _ = device
            return 7168 * 1024 * 1024

    fake_torch = types.SimpleNamespace(
        cuda=FakeCuda(),
        device=lambda value: value,
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        worker_module,
        "build_process_provider",
        lambda _config: FakeProvider(),
    )

    request_queue: queue.Queue[dict[str, object]] = queue.Queue()
    response_queue: queue.Queue[dict[str, object]] = queue.Queue()
    process_thread = threading.Thread(
        target=worker_process_main,
        args=(
            "0",
            request_queue,
            response_queue,
            WorkerProcessConfig(
                provider_name="trellis2",
                model_path="microsoft/TRELLIS.2-4B",
            ),
        ),
        daemon=True,
    )
    process_thread.start()

    ready_message = response_queue.get(timeout=1.0)
    assert ready_message["type"] == "ready"
    assert ready_message["weight_allocated_mb"] == 6144

    request_queue.put(
        {
            "type": "run",
            "request_id": "req-1",
            "prepared_inputs": [],
            "options": {},
        }
    )
    result_message = response_queue.get(timeout=1.0)
    assert result_message["type"] == "result"
    assert result_message["request_id"] == "req-1"
    assert result_message["results"] == ["ok"]
    assert result_message["inference_peak_mb"] == 3072

    request_queue.put({"type": "shutdown"})
    stopped_message = response_queue.get(timeout=1.0)
    assert stopped_message["type"] == "stopped"
    process_thread.join(timeout=1.0)
    assert process_thread.is_alive() is False


def test_process_gpu_worker_pump_responses_forwards_measurement_callback() -> None:
    async def scenario() -> None:
        callback_calls: list[tuple[str, str, int]] = []
        worker = _build_worker(
            measurement_callback=lambda model_name, device_id, measured_mb: callback_calls.append(
                (model_name, device_id, measured_mb)
            )
        )
        worker._process = FakeProcess()
        worker._response_queue = queue.Queue()
        startup_future = asyncio.get_running_loop().create_future()
        startup_future.set_result(None)
        worker._startup_future = startup_future

        request_with_peak = asyncio.get_running_loop().create_future()
        request_without_peak = asyncio.get_running_loop().create_future()
        worker._pending["req-1"] = PendingRequest(
            future=request_with_peak,
            progress_cb=None,
        )
        worker._pending["req-2"] = PendingRequest(
            future=request_without_peak,
            progress_cb=None,
        )

        worker._response_queue.put(
            {
                "type": "result",
                "request_id": "req-1",
                "results": ["with-peak"],
                "inference_peak_mb": 2048,
            }
        )
        worker._response_queue.put(
            {
                "type": "result",
                "request_id": "req-2",
                "results": ["without-peak"],
            }
        )
        worker._response_queue.put({"type": "stopped"})

        await asyncio.wait_for(worker.pump_responses(), timeout=1.0)

        assert request_with_peak.result() == ["with-peak"]
        assert request_without_peak.result() == ["without-peak"]
        assert callback_calls == [("trellis2", "0", 2048)]

    asyncio.run(scenario())


def test_process_gpu_worker_captures_startup_weight_from_ready_message() -> None:
    async def scenario() -> None:
        worker = _build_worker()
        worker._process = FakeProcess()
        worker._response_queue = queue.Queue()
        worker._startup_future = asyncio.get_running_loop().create_future()

        worker._response_queue.put(
            {
                "type": "ready",
                "weight_allocated_mb": 0,
            }
        )
        worker._response_queue.put({"type": "stopped"})

        await asyncio.wait_for(worker.pump_responses(), timeout=1.0)

        assert worker._startup_future.done()
        assert worker._startup_future.exception() is None
        assert worker.startup_weight_mb == 0

    asyncio.run(scenario())
