from __future__ import annotations

import asyncio
import os
import sys
from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Protocol

import structlog

from cubie.stage.export.preview_protocol import read_message, write_message

PREVIEW_RENDERER_STARTUP_TIMEOUT_SECONDS = 60
PREVIEW_RENDERER_REQUEST_TIMEOUT_SECONDS = 30
PREVIEW_RENDERER_SHUTDOWN_TIMEOUT_SECONDS = 5
_PREVIEW_RENDERER_STDERR_BUFFER_LINES = 20


class PreviewRendererServiceProtocol(Protocol):
    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def render_preview_png(
        self,
        *,
        model_path: Path | None = None,
        model_bytes: bytes | None = None,
    ) -> bytes: ...


class PreviewRendererServiceError(RuntimeError):
    pass


class PreviewRendererTransportError(PreviewRendererServiceError):
    pass


class PreviewRendererService:
    def __init__(
        self,
        *,
        python_executable: str | None = None,
        module_name: str = "cubie.stage.export.preview_renderer",
        startup_timeout_seconds: int = PREVIEW_RENDERER_STARTUP_TIMEOUT_SECONDS,
        request_timeout_seconds: int = PREVIEW_RENDERER_REQUEST_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: int = PREVIEW_RENDERER_SHUTDOWN_TIMEOUT_SECONDS,
    ) -> None:
        self._python_executable = python_executable or sys.executable
        self._module_name = module_name
        self._startup_timeout_seconds = max(int(startup_timeout_seconds), 1)
        self._request_timeout_seconds = max(int(request_timeout_seconds), 1)
        self._shutdown_timeout_seconds = max(int(shutdown_timeout_seconds), 1)
        self._lock = asyncio.Lock()
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_lines: deque[str] = deque(maxlen=_PREVIEW_RENDERER_STDERR_BUFFER_LINES)
        self._warmed_up = False
        self._logger = structlog.get_logger(__name__)

    async def start(self) -> None:
        async with self._lock:
            try:
                await self.ensure_process_ready_locked(
                    timeout_seconds=self._startup_timeout_seconds,
                )
            except Exception as exc:
                self._logger.warning(
                    "preview_renderer.start_failed",
                    error=str(exc),
                )

    async def stop(self) -> None:
        async with self._lock:
            await self.stop_process_locked()

    async def render_preview_png(
        self,
        *,
        model_path: Path | None = None,
        model_bytes: bytes | None = None,
    ) -> bytes:
        if (model_path is None) == (model_bytes is None):
            raise ValueError("exactly one of model_path or model_bytes must be provided")

        request_header, request_body = self.build_render_request(model_path, model_bytes)

        async with self._lock:
            for attempt in range(2):
                await self.ensure_process_ready_locked(
                    timeout_seconds=self._startup_timeout_seconds,
                )
                try:
                    return await self.send_request_locked(
                        request_header,
                        request_body,
                        timeout_seconds=self._request_timeout_seconds,
                    )
                except PreviewRendererTransportError as exc:
                    await self.stop_process_locked()
                    if attempt == 0:
                        self._logger.warning(
                            "preview_renderer.request_retrying_after_crash",
                            error=str(exc),
                        )
                        continue
                    raise
        raise RuntimeError("preview renderer request retry loop exhausted")

    @staticmethod
    def build_render_request(
        model_path: Path | None,
        model_bytes: bytes | None,
    ) -> tuple[dict[str, object], bytes]:
        request_header: dict[str, object] = {"action": "render"}
        if model_path is not None:
            request_header.update(
                {
                    "input_type": "path",
                    "path": str(Path(model_path).resolve()),
                }
            )
            return request_header, b""
        request_header["input_type"] = "bytes"
        return request_header, bytes(model_bytes or b"")

    async def ensure_process_ready_locked(
        self,
        *,
        timeout_seconds: int,
    ) -> None:
        if self._process is not None and self._process.returncode is not None:
            await self.stop_process_locked()
        if self._process is not None and self._warmed_up:
            return

        await self.stop_process_locked()
        await self.spawn_process_locked()
        try:
            await self.send_request_locked(
                {"action": "warmup"},
                b"",
                timeout_seconds=timeout_seconds,
            )
            self._warmed_up = True
        except Exception:
            await self.stop_process_locked()
            raise

    async def spawn_process_locked(self) -> None:
        pythonpath_entries = [str(Path(__file__).resolve().parents[3])]
        existing_pythonpath = os.environ.get("PYTHONPATH")
        if existing_pythonpath:
            pythonpath_entries.append(existing_pythonpath)

        self._stderr_lines.clear()
        self._process = await asyncio.create_subprocess_exec(
            self._python_executable,
            "-m",
            self._module_name,
            "--serve",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                **os.environ,
                "PYTHONPATH": os.pathsep.join(pythonpath_entries),
            },
        )
        self._warmed_up = False
        if self._process.stderr is not None:
            self._stderr_task = asyncio.create_task(
                self.collect_stderr(self._process.stderr),
                name="preview-renderer-stderr",
            )

    async def send_request_locked(
        self,
        header: dict[str, object],
        body: bytes,
        *,
        timeout_seconds: int,
    ) -> bytes:
        process = self.validate_process_or_raise_locked()

        try:
            response_header, response_body = await asyncio.wait_for(
                self.exchange_messages_locked(process, header, body),
                timeout=timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            message = self.format_error_message(
                f"preview renderer timed out after {timeout_seconds} seconds",
            )
            await self.stop_process_locked()
            raise PreviewRendererServiceError(message) from exc
        except (
            asyncio.IncompleteReadError,
            BrokenPipeError,
            ConnectionResetError,
        ) as exc:
            raise PreviewRendererTransportError(
                self.format_error_message(
                    "preview renderer process exited unexpectedly",
                )
            ) from exc

        if response_header.get("status") != "ok":
            raise PreviewRendererServiceError(
                self.format_error_message(
                    str(response_header.get("error") or "preview renderer request failed"),
                )
            )
        return response_body

    def validate_process_or_raise_locked(self) -> asyncio.subprocess.Process:
        process = self._process
        if (
            process is None
            or process.stdin is None
            or process.stdout is None
            or process.returncode is not None
        ):
            raise PreviewRendererTransportError(
                self.format_error_message(
                    "preview renderer process is not running",
                )
            )
        return process

    async def exchange_messages_locked(
        self,
        process: asyncio.subprocess.Process,
        header: dict[str, object],
        body: bytes,
    ) -> tuple[dict[str, object], bytes]:
        assert process.stdin is not None
        assert process.stdout is not None
        await write_message(process.stdin, header, body)
        response_header, response_body = await read_message(process.stdout)
        return response_header, response_body

    async def stop_process_locked(self) -> None:
        process = self._process
        stderr_task = self._stderr_task
        self._process = None
        self._stderr_task = None
        self._warmed_up = False

        if process is not None:
            try:
                await self.try_graceful_shutdown_locked(process)
                await self.terminate_or_kill_locked(process)
            finally:
                if process.stdin is not None and not process.stdin.is_closing():
                    process.stdin.close()

        if stderr_task is not None:
            stderr_task.cancel()
            with suppress(asyncio.CancelledError):
                await stderr_task

    async def try_graceful_shutdown_locked(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        if (
            process.returncode is not None
            or process.stdin is None
            or process.stdout is None
        ):
            return
        try:
            await asyncio.wait_for(
                self.exchange_messages_locked(
                    process,
                    {"action": "shutdown"},
                    b"",
                ),
                timeout=self._shutdown_timeout_seconds,
            )
        except Exception:
            pass

    async def terminate_or_kill_locked(
        self,
        process: asyncio.subprocess.Process,
    ) -> None:
        if process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(
                process.wait(),
                timeout=self._shutdown_timeout_seconds,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()

    async def collect_stderr(
        self,
        stream: asyncio.StreamReader,
    ) -> None:
        while True:
            line = await stream.readline()
            if not line:
                return
            decoded = line.decode("utf-8", errors="replace").strip()
            if decoded:
                self._stderr_lines.append(decoded)

    def format_error_message(
        self,
        message: str,
    ) -> str:
        if not self._stderr_lines:
            return message
        stderr_summary = " | ".join(self._stderr_lines)
        return f"{message}: {stderr_summary}"
