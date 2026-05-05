from __future__ import annotations

import asyncio
import queue
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

import structlog

from cubie.model.base import (
    GenerationResult,
    ModelProviderConfigurationError,
    ModelProviderExecutionError,
    StageProgress,
)
from cubie.model.gpu.messaging import serialize_prepared_inputs
from cubie.model.gpu.worker_main import worker_process_main

ProgressCallback = Callable[[StageProgress], Awaitable[None] | None]
_RESPONSE_QUEUE_POLL_TIMEOUT_SECONDS = 1.0
_logger = structlog.get_logger(__name__)


@dataclass(slots=True)
class PendingRequest:
    future: asyncio.Future[list[GenerationResult]]
    progress_cb: ProgressCallback | None


class ProcessGPUWorkerLifecycleMixin:
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
        future: asyncio.Future[list[GenerationResult]] = (
            asyncio.get_running_loop().create_future()
        )
        self._pending[request_id] = PendingRequest(
            future=future,
            progress_cb=progress_cb,
        )
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


async def dispatch_progress(
    progress_cb: ProgressCallback | None,
    progress: StageProgress,
) -> None:
    if progress_cb is None:
        return
    callback_result = progress_cb(progress)
    if asyncio.isfuture(callback_result) or asyncio.iscoroutine(callback_result):
        await callback_result
