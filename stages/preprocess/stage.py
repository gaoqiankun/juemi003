from __future__ import annotations

import asyncio
import base64
import binascii
import io
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse

import httpx

from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.stages.base import BaseStage, StageExecutionError, StageUpdateHandler


class PreprocessStage(BaseStage):
    name = "preprocess"

    def __init__(
        self,
        delay_ms: int = 0,
        *,
        download_timeout_seconds: float = 15.0,
        max_image_bytes: int = 10 * 1024 * 1024,
    ) -> None:
        self._delay_seconds = max(delay_ms, 0) / 1000
        self._download_timeout_seconds = max(download_timeout_seconds, 1.0)
        self._max_image_bytes = max(max_image_bytes, 1)

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        sequence.transition_to(
            TaskStatus.PREPROCESSING,
            current_stage=TaskStatus.PREPROCESSING.value,
        )
        await self._emit_update(sequence, on_update)

        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)

        if sequence.options.get("mock_failure_stage") == TaskStatus.PREPROCESSING.value:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message="mock failure injected at preprocessing",
            )

        image_bytes = await self._read_input_bytes(sequence.input_url)
        normalized_image = await asyncio.to_thread(self._decode_and_normalize_image, image_bytes)
        sequence.prepared_input = {
            "image": normalized_image,
            "image_url": sequence.input_url,
            "normalized": True,
            "resolution": sequence.options.get("resolution", 1024),
            "width": normalized_image.width,
            "height": normalized_image.height,
            "mode": normalized_image.mode,
        }
        return sequence

    async def _read_input_bytes(self, input_url: str) -> bytes:
        parsed = urlparse(input_url)
        if parsed.scheme in {"http", "https"}:
            return await self._download_http_image(input_url)
        if parsed.scheme == "file":
            return await self._read_local_file(parsed.path)
        if parsed.scheme == "data":
            return self._decode_data_url(input_url)

        local_path = Path(input_url)
        if local_path.exists():
            return await self._read_local_file(str(local_path))

        raise StageExecutionError(
            stage_name=TaskStatus.PREPROCESSING.value,
            message=(
                "unsupported input_url; expected http(s), file://, data:, "
                "or an existing local file path"
            ),
        )

    async def _download_http_image(self, input_url: str) -> bytes:
        try:
            async with httpx.AsyncClient(
                timeout=self._download_timeout_seconds,
                follow_redirects=True,
            ) as client:
                response = await client.get(input_url)
        except httpx.HTTPError as exc:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"failed to download input image: {exc}",
            ) from exc

        if response.status_code >= 400:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"image download returned HTTP {response.status_code}",
            )

        content_type = response.headers.get("content-type", "")
        if content_type and not content_type.startswith("image/"):
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"downloaded content is not an image: {content_type}",
            )

        content = response.content
        if len(content) > self._max_image_bytes:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"input image exceeds max size of {self._max_image_bytes} bytes",
            )
        return content

    async def _read_local_file(self, path: str) -> bytes:
        try:
            content = await asyncio.to_thread(Path(path).read_bytes)
        except OSError as exc:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"failed to read local input image: {exc}",
            ) from exc

        if len(content) > self._max_image_bytes:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"input image exceeds max size of {self._max_image_bytes} bytes",
            )
        return content

    def _decode_data_url(self, input_url: str) -> bytes:
        header, _, data = input_url.partition(",")
        if not data:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message="invalid data URL for input image",
            )
        try:
            if ";base64" in header:
                content = base64.b64decode(data, validate=True)
            else:
                content = unquote_to_bytes(data)
        except (binascii.Error, ValueError) as exc:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"failed to decode data URL image: {exc}",
            ) from exc

        if len(content) > self._max_image_bytes:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"input image exceeds max size of {self._max_image_bytes} bytes",
            )
        return content

    @staticmethod
    def _decode_and_normalize_image(image_bytes: bytes):
        try:
            from PIL import Image, ImageOps
        except ModuleNotFoundError as exc:  # pragma: no cover - dependency installation
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message="preprocessing requires the Pillow package",
            ) from exc

        try:
            with Image.open(io.BytesIO(image_bytes)) as source_image:
                image = ImageOps.exif_transpose(source_image)
                image.load()
        except Exception as exc:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"failed to decode input image: {exc}",
            ) from exc

        if image.mode not in {"RGB", "RGBA"}:
            image = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        if image.mode == "RGBA":
            background = Image.new("RGBA", image.size, (255, 255, 255, 255))
            image = Image.alpha_composite(background, image).convert("RGB")
        else:
            image = image.convert("RGB")

        if image.width <= 0 or image.height <= 0:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message="decoded image has invalid dimensions",
            )
        return image
