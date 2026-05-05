from __future__ import annotations

import io
import multiprocessing as mp
from typing import Any, Awaitable, Callable

from cubie.model.base import ModelProviderConfigurationError, StageProgress


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
