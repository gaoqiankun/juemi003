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

from gen3d.model.base import (
    BaseModelProvider,
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    StageProgress,
)
from gen3d.model.hunyuan3d.provider import Hunyuan3DProvider
from gen3d.model.step1x3d.provider import Step1X3DProvider
from gen3d.model.trellis2.provider import MockTrellis2Provider, Trellis2Provider

ProgressCallback = Callable[[StageProgress], Awaitable[None] | None]
_RESPONSE_QUEUE_POLL_TIMEOUT_SECONDS = 1.0


class GPUWorkerHandle(Protocol):
    worker_id: str
    device_id: str

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
class _PendingRequest:
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
        process_config: WorkerProcessConfig,
    ) -> None:
        self.worker_id = worker_id
        self.device_id = device_id
        self._process_config = process_config
        self._ctx = mp.get_context("spawn")
        self._request_queue: mp.Queue[dict[str, Any]] = self._ctx.Queue()
        self._response_queue: mp.Queue[dict[str, Any]] = self._ctx.Queue()
        self._process: mp.Process | None = None
        self._response_task: asyncio.Task[None] | None = None
        self._startup_future: asyncio.Future[None] | None = None
        self._pending: dict[str, _PendingRequest] = {}

    async def start(self) -> None:
        if self._process is not None and self._process.is_alive():
            return
        loop = asyncio.get_running_loop()
        self._startup_future = loop.create_future()
        self._process = self._ctx.Process(
            target=_worker_process_main,
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
            self._pump_responses(),
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
        self._pending.clear()

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
        self._pending[request_id] = _PendingRequest(future=future, progress_cb=progress_cb)
        await asyncio.to_thread(
            self._request_queue.put,
            {
                "type": "run",
                "request_id": request_id,
                "prepared_inputs": _serialize_prepared_inputs(prepared_inputs),
                "options": options,
            },
        )
        try:
            return await future
        finally:
            self._pending.pop(request_id, None)

    async def _pump_responses(self) -> None:
        while True:
            try:
                message = await asyncio.to_thread(
                    self._response_queue.get,
                    timeout=_RESPONSE_QUEUE_POLL_TIMEOUT_SECONDS,
                )
            except queue.Empty:
                process = self._process
                if process is not None and not process.is_alive():
                    self._fail_startup_and_pending(
                        self._process_exit_message(),
                    )
                    return
                continue
            message_type = message.get("type")
            if message_type == "ready":
                if self._startup_future is not None and not self._startup_future.done():
                    self._startup_future.set_result(None)
                continue
            if message_type == "startup_error":
                error = message.get("error", "unknown worker startup error")
                if self._startup_future is not None and not self._startup_future.done():
                    self._startup_future.set_exception(
                        ModelProviderConfigurationError(error)
                    )
                return
            if message_type == "stopped":
                return

            request_id = message.get("request_id")
            pending = self._pending.get(request_id)
            if pending is None:
                continue

            if message_type == "progress":
                await _dispatch_progress(
                    pending.progress_cb,
                    StageProgress(
                        stage_name=str(message["stage_name"]),
                        step=int(message["step"]),
                        total_steps=int(message["total_steps"]),
                    ),
                )
                continue

            if message_type == "result":
                if not pending.future.done():
                    pending.future.set_result(message["results"])
                self._pending.pop(request_id, None)
                continue

            if message_type == "error":
                if not pending.future.done():
                    pending.future.set_exception(
                        ModelProviderExecutionError(
                            str(message.get("stage_name", "gpu_run")),
                            str(message.get("error", "worker execution failed")),
                        )
                    )
                self._pending.pop(request_id, None)

    def _fail_startup_and_pending(self, error_message: str) -> None:
        if self._startup_future is not None and not self._startup_future.done():
            self._startup_future.set_exception(
                ModelProviderExecutionError("gpu_run", error_message)
            )
        for pending in list(self._pending.values()):
            if pending.future.done():
                continue
            pending.future.set_exception(
                ModelProviderExecutionError("gpu_run", error_message)
            )
        self._pending.clear()

    def _process_exit_message(self) -> str:
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
            process_config=process_config,
        )
        for device_id in device_ids
    ]


async def _dispatch_progress(
    progress_cb: ProgressCallback | None,
    progress: StageProgress,
) -> None:
    if progress_cb is None:
        return
    callback_result = progress_cb(progress)
    if asyncio.isfuture(callback_result) or asyncio.iscoroutine(callback_result):
        await callback_result


def _worker_process_main(
    device_id: str,
    request_queue: mp.Queue[dict[str, Any]],
    response_queue: mp.Queue[dict[str, Any]],
    process_config: WorkerProcessConfig,
) -> None:
    os.environ["CUDA_VISIBLE_DEVICES"] = str(device_id)
    try:
        provider = _build_process_provider(process_config)
    except Exception as exc:  # pragma: no cover - real runtime only
        response_queue.put({"type": "startup_error", "error": str(exc)})
        return

    response_queue.put({"type": "ready"})
    while True:
        message = request_queue.get()
        message_type = message.get("type")
        if message_type == "shutdown":
            response_queue.put({"type": "stopped"})
            return
        if message_type != "run":
            continue

        request_id = str(message["request_id"])
        prepared_inputs = _deserialize_prepared_inputs(message["prepared_inputs"])
        options = dict(message["options"])

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

        try:
            results = asyncio.run(
                provider.run_batch(
                    images=prepared_inputs,
                    options=options,
                    progress_cb=progress_cb,
                )
            )
        except ModelProviderExecutionError as exc:  # pragma: no cover - real runtime only
            response_queue.put(
                {
                    "type": "error",
                    "request_id": request_id,
                    "stage_name": exc.stage_name,
                    "error": str(exc),
                }
            )
            continue
        except Exception as exc:  # pragma: no cover - real runtime only
            response_queue.put(
                {
                    "type": "error",
                    "request_id": request_id,
                    "stage_name": "gpu_run",
                    "error": str(exc),
                }
            )
            continue

        response_queue.put(
            {
                "type": "result",
                "request_id": request_id,
                "results": results,
            }
        )


def _build_process_provider(process_config: WorkerProcessConfig) -> BaseModelProvider:
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


def _serialize_prepared_inputs(prepared_inputs: list[object]) -> list[object]:
    return [_serialize_prepared_input(item) for item in prepared_inputs]


def _serialize_prepared_input(prepared_input: object) -> object:
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


def _deserialize_prepared_inputs(prepared_inputs: list[object]) -> list[object]:
    return [_deserialize_prepared_input(item) for item in prepared_inputs]


def _deserialize_prepared_input(prepared_input: object) -> object:
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
