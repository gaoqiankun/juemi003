from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cubie.stage.export.preview_renderer_service import (
    PREVIEW_RENDERER_REQUEST_TIMEOUT_SECONDS,
    PREVIEW_RENDERER_STARTUP_TIMEOUT_SECONDS,
    PreviewRendererService,
    PreviewRendererTransportError,
)


def test_preview_renderer_service_restarts_after_transport_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service = PreviewRendererService()
        ensure_calls: list[int] = []
        send_calls: list[tuple[dict[str, object], bytes, int]] = []
        stop_calls = 0

        async def fake_ensure_process_ready_locked(*, timeout_seconds: int) -> None:
            ensure_calls.append(timeout_seconds)

        async def fake_send_request_locked(
            header: dict[str, object],
            body: bytes,
            *,
            timeout_seconds: int,
        ) -> bytes:
            send_calls.append((dict(header), body, timeout_seconds))
            if len(send_calls) == 1:
                raise PreviewRendererTransportError("renderer crashed")
            return b"png-bytes"

        async def fake_stop_process_locked() -> None:
            nonlocal stop_calls
            stop_calls += 1

        monkeypatch.setattr(
            service,
            "ensure_process_ready_locked",
            fake_ensure_process_ready_locked,
        )
        monkeypatch.setattr(
            service,
            "send_request_locked",
            fake_send_request_locked,
        )
        monkeypatch.setattr(
            service,
            "stop_process_locked",
            fake_stop_process_locked,
        )

        result = await service.render_preview_png(model_path=Path("/tmp/model.glb"))

        assert result == b"png-bytes"
        assert ensure_calls == [
            PREVIEW_RENDERER_STARTUP_TIMEOUT_SECONDS,
            PREVIEW_RENDERER_STARTUP_TIMEOUT_SECONDS,
        ]
        assert stop_calls == 1
        assert [call[0]["action"] for call in send_calls] == ["render", "render"]
        assert [call[0]["input_type"] for call in send_calls] == ["path", "path"]
        assert [call[2] for call in send_calls] == [
            PREVIEW_RENDERER_REQUEST_TIMEOUT_SECONDS,
            PREVIEW_RENDERER_REQUEST_TIMEOUT_SECONDS,
        ]

    asyncio.run(scenario())


def test_preview_renderer_service_start_logs_warning_on_warmup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def scenario() -> None:
        service = PreviewRendererService()
        warnings: list[tuple[str, dict[str, object]]] = []

        async def fake_ensure_process_ready_locked(*, timeout_seconds: int) -> None:
            assert timeout_seconds == PREVIEW_RENDERER_STARTUP_TIMEOUT_SECONDS
            raise RuntimeError("warmup failed")

        class FakeLogger:
            def warning(self, event: str, **kwargs) -> None:
                warnings.append((event, kwargs))

        monkeypatch.setattr(
            service,
            "ensure_process_ready_locked",
            fake_ensure_process_ready_locked,
        )
        monkeypatch.setattr(service, "_logger", FakeLogger())

        await service.start()

        assert warnings == [
            (
                "preview_renderer.start_failed",
                {"error": "warmup failed"},
            )
        ]

    asyncio.run(scenario())
