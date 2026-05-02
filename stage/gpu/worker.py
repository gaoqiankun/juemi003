from __future__ import annotations

import asyncio
import io
import multiprocessing as mp
import os
import queue
import uuid
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

import structlog
from gen3d.model.base import (
    BaseModelProvider,
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    StageProgress,
)
from gen3d.model.providers.hunyuan3d.provider import Hunyuan3DProvider
from gen3d.model.providers.step1x3d.provider import Step1X3DProvider
from gen3d.model.providers.trellis2.provider import (
    MockTrellis2Provider,
    Trellis2Provider,
)

ProgressCallback = Callable[[StageProgress], Awaitable[None] | None]
MeasurementCallback = Callable[[str, str, int], None]
_RESPONSE_QUEUE_POLL_TIMEOUT_SECONDS = 1.0
_logger = structlog.get_logger(__name__)


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


@dataclass(slots=True)
class WorkerProcessConfig:
    provider_name: str
    model_path: str
    dep_paths: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class PendingRequest:
    future: asyncio.Future[list[GenerationResult]]
    progress_cb: ProgressCallback | None


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


class ProcessGPUWorker:
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

    async def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        loop = asyncio.get_running_loop()
        self._startup_future = loop.create_future()
        self._startup_weight_mb = None
        self._process = self._ctx.Process(
            target=worker_process_main,
            args=(
                self.device_id,
                self._request_queue,
                self._response_queue,
                self._process_config,
            ),
            name=self.worker_id,
        )
        self._process.start()
        self._response_task = asyncio.create_task(
            self.pump_responses(),
            name=f"{self.worker_id}-responses",
        )
        await self._startup_future

    async def stop(self) -> None:
        if self._process is None:
            return
        await asyncio.to_thread(
            self._request_queue.put,
            {"type": "shutdown"},
        )
        if self._response_task is not None:
            try:
                await asyncio.wait_for(self._response_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._response_task.cancel()
                with suppress(asyncio.CancelledError):
                    await self._response_task
        await asyncio.to_thread(self._process.join, 1.0)
        if self._process.is_alive():
            self._process.kill()
            await asyncio.to_thread(self._process.join, 1.0)
        self._process = None
        self._response_task = None
        self._startup_future = None
        self.fail_pending("worker stopped")

    async def run_batch(
        self,
        prepared_inputs: list[object],
        options: dict,
        progress_cb: ProgressCallback | None = None,
    ) -> list[GenerationResult]:
        if self._process is None:
            raise RuntimeError("GPU worker process is not running")
        request_id = uuid.uuid4().hex
        future: asyncio.Future[list[GenerationResult]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = PendingRequest(future=future, progress_cb=progress_cb)
        await asyncio.to_thread(
            self._request_queue.put,
            {
                "type": "run",
                "request_id": request_id,
                "prepared_inputs": serialize_prepared_inputs(prepared_inputs),
                "options": options,
            },
        )
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def pump_responses(self) -> None:
        while True:
            message = await self.poll_next_response()
            if message is None:
                if self.detect_process_exit():
                    return
                continue
            message_type = message.get("type")
            if message_type == "startup_error":
                self.on_startup_error(message)
                return
            if message_type == "stopped":
                return
            if message_type == "ready":
                self.on_ready(message)
                continue
            await self.handle_request_response(message)

    def detect_process_exit(self) -> bool:
        if self._process is None or self._process.is_alive():
            return False
        self.fail_startup_and_pending(self.process_exit_message())
        return True

    async def handle_request_response(self, message: dict[str, Any]) -> None:
        request_id = message.get("request_id")
        pending = self._pending.get(request_id)
        if pending is None:
            return
        message_type = message.get("type")
        if message_type == "progress":
            await self.dispatch_progress_event(pending, message)
        elif message_type == "result":
            self.on_result(request_id, pending, message)
        elif message_type == "error":
            self.on_error(request_id, pending, message)

    async def poll_next_response(self) -> dict[str, Any] | None:
        try:
            return await asyncio.to_thread(
                self._response_queue.get,
                timeout=_RESPONSE_QUEUE_POLL_TIMEOUT_SECONDS,
            )
        except queue.Empty:
            return None

    def on_ready(self, message: dict[str, Any]) -> None:
        weight_allocated_mb = message.get("weight_allocated_mb")
        self._startup_weight_mb = (
            int(weight_allocated_mb)
            if weight_allocated_mb is not None
            else None
        )
        if self._startup_future is not None and not self._startup_future.done():
            self._startup_future.set_result(None)

    def on_startup_error(self, message: dict[str, Any]) -> None:
        error = message.get("error", "unknown worker startup error")
        if self._startup_future is not None and not self._startup_future.done():
            self._startup_future.set_exception(
                ModelProviderConfigurationError(error)
            )

    async def dispatch_progress_event(
        self,
        pending: PendingRequest,
        message: dict[str, Any],
    ) -> None:
        await dispatch_progress(
            pending.progress_cb,
            StageProgress(
                stage_name=str(message["stage_name"]),
                step=int(message["step"]),
                total_steps=int(message["total_steps"]),
            ),
        )

    def on_result(
        self,
        request_id: str,
        pending: PendingRequest,
        message: dict[str, Any],
    ) -> None:
        inference_peak_mb = message.get("inference_peak_mb")
        if inference_peak_mb is not None:
            self.record_inference_measurement(int(inference_peak_mb))
        if not pending.future.done():
            pending.future.set_result(message["results"])
        self._pending.pop(request_id, None)

    def on_error(
        self,
        request_id: str,
        pending: PendingRequest,
        message: dict[str, Any],
    ) -> None:
        if not pending.future.done():
            pending.future.set_exception(
                ModelProviderExecutionError(
                    str(message.get("stage_name", "gpu_run")),
                    str(message.get("error", "worker execution failed")),
                )
            )
        self._pending.pop(request_id, None)

    def record_inference_measurement(self, peak_mb: int) -> None:
        if self._measurement_callback is None:
            return
        try:
            self._measurement_callback(self._model_name, self.device_id, peak_mb)
        except Exception as exc:
            _logger.warning(
                "inference_measure.callback_failed",
                model_name=self._model_name,
                device_id=self.device_id,
                error=str(exc),
            )

    def fail_startup_and_pending(self, error_message: str) -> None:
        if self._startup_future is not None and not self._startup_future.done():
            self._startup_future.set_exception(
                ModelProviderExecutionError("gpu_run", error_message)
            )
        self.fail_pending(error_message)

    def fail_pending(self, error_message: str) -> None:
        for pending in list(self._pending.values()):
            if pending.future.done():
                continue
            pending.future.set_exception(
                ModelProviderExecutionError("gpu_run", error_message)
            )
        self._pending.clear()

    def process_exit_message(self) -> str:
        if self._process is None or self._process.exitcode is None:
            return f"GPU worker process {self.worker_id} exited unexpectedly"
        return (
            f"GPU worker process {self.worker_id} exited unexpectedly "
            f"(exitcode={self._process.exitcode})"
        )


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


async def dispatch_progress(
    progress_cb: ProgressCallback | None,
    progress: StageProgress,
) -> None:
    if progress_cb is None:
        return
    callback_result = progress_cb(progress)
    if asyncio.isfuture(callback_result) or asyncio.iscoroutine(callback_result):
        await callback_result


def worker_process_main(
    device_id: str,
    request_queue: mp.Queue[dict[str, Any]],
    response_queue: mp.Queue[dict[str, Any]],
    process_config: WorkerProcessConfig,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(device_id)
    try:
        provider = build_process_provider(process_config)
    except Exception as exc:  # pragma: no cover - real runtime only
        response_queue.put({"type": "startup_error", "error": str(exc)})
        return

    torch_module, torch_device, weight_mb, inference_baseline_mb = capture_cuda_baseline_mb()
    response_queue.put({"type": "ready", "weight_allocated_mb": weight_mb})

    while True:
        message = request_queue.get()
        message_type = message.get("type")
        if message_type == "shutdown":
            response_queue.put({"type": "stopped"})
            return
        if message_type != "run":
            continue
        process_run_message(
            provider,
            response_queue,
            message,
            torch_module=torch_module,
            torch_device=torch_device,
            inference_baseline_mb=inference_baseline_mb,
        )


def process_run_message(
    provider: BaseModelProvider,
    response_queue: mp.Queue[dict[str, Any]],
    message: dict[str, Any],
    *,
    torch_module: Any | None,
    torch_device: Any | None,
    inference_baseline_mb: int | None,
) -> None:
    request_id = str(message["request_id"])
    prepared_inputs = deserialize_prepared_inputs(message["prepared_inputs"])
    options = dict(message["options"])
    progress_cb = make_progress_publisher(response_queue, request_id)

    if torch_module is not None and torch_device is not None and inference_baseline_mb is not None:
        reset_cuda_peak(torch_module, torch_device)

    try:
        results = asyncio.run(
            provider.run_batch(
                images=prepared_inputs,
                options=options,
                progress_cb=progress_cb,
            )
        )
    except ModelProviderExecutionError as exc:  # pragma: no cover - real runtime only
        send_error_response(response_queue, request_id, exc.stage_name, str(exc))
        return
    except Exception as exc:  # pragma: no cover - real runtime only
        send_error_response(response_queue, request_id, "gpu_run", str(exc))
        return

    response_queue.put(
        {
            "type": "result",
            "request_id": request_id,
            "results": results,
            "inference_peak_mb": measure_cuda_peak_mb(
                torch_module, torch_device, inference_baseline_mb
            ),
        }
    )

    del results
    prepared_inputs = []
    release_cuda_after_run(torch_module)


def make_progress_publisher(
    response_queue: mp.Queue[dict[str, Any]],
    request_id: str,
) -> Callable[[StageProgress], Awaitable[None]]:
    async def progress_cb(progress: StageProgress) -> None:
        response_queue.put(
            {
                "type": "progress",
                "request_id": request_id,
                "stage_name": progress.stage_name,
                "step": progress.step,
                "total_steps": progress.total_steps,
            }
        )

    return progress_cb


def reset_cuda_peak(torch_module: Any, torch_device: Any) -> None:
    try:
        torch_module.cuda.reset_peak_memory_stats(torch_device)
    except Exception:
        pass


def measure_cuda_peak_mb(
    torch_module: Any | None,
    torch_device: Any | None,
    baseline_mb: int | None,
) -> int | None:
    if torch_module is None or torch_device is None or baseline_mb is None:
        return None
    try:
        peak_mb = int(
            torch_module.cuda.max_memory_allocated(torch_device) / (1024 * 1024)
        )
        return max(0, peak_mb - baseline_mb)
    except Exception:
        return None


def release_cuda_after_run(torch_module: Any | None) -> None:
    import gc
    gc.collect()
    if torch_module is None:
        return
    try:
        torch_module.cuda.empty_cache()
    except Exception:
        pass


def send_error_response(
    response_queue: mp.Queue[dict[str, Any]],
    request_id: str,
    stage_name: str,
    error: str,
) -> None:
    response_queue.put(
        {
            "type": "error",
            "request_id": request_id,
            "stage_name": stage_name,
            "error": error,
        }
    )


def capture_cuda_baseline_mb() -> tuple[Any | None, Any | None, int | None, int | None]:
    try:
        import torch  # type: ignore[import-not-found]
    except Exception:
        return None, None, None, None

    try:
        if not torch.cuda.is_available():
            return torch, None, None, None
        device = torch.device("cuda")
        weight_reserved_mb = int(torch.cuda.memory_reserved(device) / (1024 * 1024))
        inference_baseline_allocated_mb = int(
            torch.cuda.memory_allocated(device) / (1024 * 1024)
        )
    except Exception:
        return torch, None, None, None
    return torch, device, weight_reserved_mb, inference_baseline_allocated_mb


def build_process_provider(process_config: WorkerProcessConfig) -> BaseModelProvider:
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if process_config.provider_name == "trellis2":
        return Trellis2Provider.from_pretrained(
            process_config.model_path,
            dep_paths=process_config.dep_paths,
        )
    if process_config.provider_name == "hunyuan3d":
        return Hunyuan3DProvider.from_pretrained(
            process_config.model_path,
            dep_paths=process_config.dep_paths,
        )
    if process_config.provider_name == "step1x3d":
        return Step1X3DProvider.from_pretrained(
            process_config.model_path,
            dep_paths=process_config.dep_paths,
        )
    raise ModelProviderConfigurationError(
        f"unsupported MODEL_PROVIDER in GPU worker: {process_config.provider_name}"
    )


def serialize_prepared_inputs(prepared_inputs: list[object]) -> list[object]:
    return [serialize_prepared_input(item) for item in prepared_inputs]


def serialize_prepared_input(prepared_input: object) -> object:
    if not isinstance(prepared_input, dict):
        return prepared_input
    serialized = dict(prepared_input)
    image = serialized.pop("image", None)
    if image is None:
        return serialized
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    serialized["image_bytes"] = buffer.getvalue()
    return serialized


def deserialize_prepared_inputs(prepared_inputs: list[object]) -> list[object]:
    return [deserialize_prepared_input(item) for item in prepared_inputs]


def deserialize_prepared_input(prepared_input: object) -> object:
    if not isinstance(prepared_input, dict) or "image_bytes" not in prepared_input:
        return prepared_input
    item = dict(prepared_input)
    image_bytes = item.pop("image_bytes")
    try:
        from PIL import Image
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency installation
        raise ModelProviderConfigurationError(
            "GPU worker image deserialization requires the Pillow package"
        ) from exc
    with Image.open(io.BytesIO(image_bytes)) as image:
        item["image"] = image.copy()
    return item
