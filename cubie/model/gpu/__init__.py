from __future__ import annotations

import asyncio
import multiprocessing as mp
from typing import Any, Callable, Protocol

from cubie.model.base import BaseModelProvider, GenerationResult
from cubie.model.gpu.lifecycle import (
    PendingRequest,
    ProcessGPUWorkerLifecycleMixin,
    ProgressCallback,
    dispatch_progress,
)
from cubie.model.gpu.messaging import (
    deserialize_prepared_input,
    deserialize_prepared_inputs,
    make_progress_publisher,
    send_error_response,
    serialize_prepared_input,
    serialize_prepared_inputs,
)
from cubie.model.gpu.worker_main import (
    WorkerProcessConfig,
    build_process_provider,
    capture_cuda_baseline_mb,
    measure_cuda_peak_mb,
    process_run_message,
    release_cuda_after_run,
    reset_cuda_peak,
    worker_process_main,
)
from cubie.model.providers.trellis2.provider import MockTrellis2Provider

MeasurementCallback = Callable[[str, str, int], None]

__all__ = (
    "AsyncGPUWorker",
    "GPUWorkerHandle",
    "MeasurementCallback",
    "PendingRequest",
    "ProcessGPUWorker",
    "ProgressCallback",
    "WorkerProcessConfig",
    "build_gpu_workers",
    "build_process_provider",
    "capture_cuda_baseline_mb",
    "deserialize_prepared_input",
    "deserialize_prepared_inputs",
    "dispatch_progress",
    "make_progress_publisher",
    "measure_cuda_peak_mb",
    "process_run_message",
    "release_cuda_after_run",
    "reset_cuda_peak",
    "send_error_response",
    "serialize_prepared_input",
    "serialize_prepared_inputs",
    "worker_process_main",
)


class GPUWorkerHandle(Protocol):
    worker_id: str
    device_id: str

    @property
    def startup_weight_mb(self) -> int | None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb: ProgressCallback | None = None,
    ) -> list[GenerationResult]: ...


class AsyncGPUWorker:
    def __init__(
        self,
        *,
        worker_id: str,
        device_id: str,
        provider: BaseModelProvider,
    ) -> None:
        self.worker_id = worker_id
        self.device_id = device_id
        self._provider = provider

    @property
    def startup_weight_mb(self) -> int | None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb: ProgressCallback | None = None,
    ) -> list[GenerationResult]:
        return await self._provider.run_batch(
            images=prepared_inputs,
            options=options,
            progress_cb=progress_cb,
        )


class ProcessGPUWorker(ProcessGPUWorkerLifecycleMixin):
    def __init__(
        self,
        *,
        worker_id: str,
        device_id: str,
        model_name: str | None = None,
        process_config: WorkerProcessConfig,
        measurement_callback: MeasurementCallback | None = None,
    ) -> None:
        self.worker_id = worker_id
        self.device_id = device_id
        normalized_model_name = str(model_name or "").strip().lower()
        if not normalized_model_name:
            normalized_model_name = str(process_config.provider_name).strip().lower()
        self._model_name = normalized_model_name
        self._process_config = process_config
        self._measurement_callback = measurement_callback
        self._ctx = mp.get_context("spawn")
        self._request_queue: mp.Queue[dict[str, Any]] = self._ctx.Queue()
        self._response_queue: mp.Queue[dict[str, Any]] = self._ctx.Queue()
        self._process: mp.Process | None = None
        self._response_task: asyncio.Task[None] | None = None
        self._startup_future: asyncio.Future[None] | None = None
        self._startup_weight_mb: int | None = None
        self._pending: dict[str, PendingRequest] = {}

    @property
    def startup_weight_mb(self) -> int | None:
        return self._startup_weight_mb


def build_gpu_workers(
    *,
    provider: BaseModelProvider,
    provider_mode: str,
    provider_name: str,
    model_path: str,
    device_ids: tuple[str, ...],
    dep_paths: dict[str, str] | None = None,
    model_name: str | None = None,
    measurement_callback: MeasurementCallback | None = None,
) -> list[GPUWorkerHandle]:
    normalized_mode = provider_mode.strip().lower()
    if normalized_mode == "mock" or isinstance(provider, MockTrellis2Provider):
        return [
            AsyncGPUWorker(
                worker_id=f"gpu-worker-{device_id}",
                device_id=device_id,
                provider=provider,
            )
            for device_id in device_ids
        ]

    process_config = WorkerProcessConfig(
        provider_name=provider_name.strip().lower(),
        model_path=model_path,
        dep_paths=dict(dep_paths or {}),
    )
    return [
        ProcessGPUWorker(
            worker_id=f"gpu-worker-{device_id}",
            device_id=device_id,
            model_name=(model_name or provider_name),
            process_config=process_config,
            measurement_callback=measurement_callback,
        )
        for device_id in device_ids
    ]
