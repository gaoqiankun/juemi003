from __future__ import annotations

import asyncio
import base64
import binascii
import io
import time
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse

import httpx
import structlog
from structlog.contextvars import bound_contextvars

from gen3d.engine.sequence import RequestSequence, TaskStatus
from gen3d.observability.metrics import observe_stage_duration
from gen3d.security import TaskSubmissionValidationError, validate_image_url
from gen3d.stages.base import BaseStage, StageExecutionError, StageUpdateHandler
from gen3d.storage.artifact_store import ArtifactStore, ArtifactStoreOperationError


class PreprocessStage(BaseStage):
    name = "preprocess"

    def __init__(
        self,
        delay_ms: int = 0,
        *,
        download_timeout_seconds: float = 15.0,
        max_image_bytes: int = 10 * 1024 * 1024,
        allow_local_inputs: bool = True,
        uploads_dir: Path = Path("./data/uploads"),
        artifact_store: ArtifactStore | None = None,
        task_store=None,
    ) -> None:
        self._delay_seconds = max(delay_ms, 0) / 1000
        self._download_timeout_seconds = max(download_timeout_seconds, 1.0)
        self._max_image_bytes = max(max_image_bytes, 1)
        self._allow_local_inputs = allow_local_inputs
        self._uploads_dir = Path(uploads_dir)
        self._artifact_store = artifact_store
        self._task_store = task_store
        self._logger = structlog.get_logger(__name__)

    async def run(
        self,
        sequence: RequestSequence,
        on_update: StageUpdateHandler | None = None,
    ) -> RequestSequence:
        started_at = time.perf_counter()
        with bound_contextvars(task_id=sequence.task_id):
            self._logger.info("stage.started", stage=self.name)
            try:
                sequence.transition_to(
                    TaskStatus.PREPROCESSING,
                    current_stage=TaskStatus.PREPROCESSING.value,
                )
                await self._emit_update(sequence, on_update)

                if self._delay_seconds:
                    await asyncio.sleep(self._delay_seconds)

                image_bytes = await self._read_input_bytes(sequence.input_url)
                input_content_type = await asyncio.to_thread(
                    self._detect_image_content_type,
                    image_bytes,
                )
                input_artifact = await self._persist_input_artifact(
                    sequence.task_id,
                    image_bytes,
                    input_content_type,
                )
                if input_artifact is not None:
                    sequence.artifacts = [input_artifact]

                if sequence.options.get("mock_failure_stage") == TaskStatus.PREPROCESSING.value:
                    raise StageExecutionError(
                        stage_name=TaskStatus.PREPROCESSING.value,
                        message="mock failure injected at preprocessing",
                    )

                normalized_image = await asyncio.to_thread(
                    self._decode_and_normalize_image,
                    image_bytes,
                )
                sequence.prepared_input = {
                    "image": normalized_image,
                    "image_url": sequence.input_url,
                    "normalized": True,
                    "resolution": sequence.options.get("resolution", 1024),
                    "width": normalized_image.width,
                    "height": normalized_image.height,
                    "mode": normalized_image.mode,
                }
                duration_seconds = time.perf_counter() - started_at
                self._logger.info(
                    "stage.completed",
                    stage=self.name,
                    duration_seconds=round(duration_seconds, 6),
                    width=normalized_image.width,
                    height=normalized_image.height,
                )
                if self._task_store is not None:
                    await self._task_store.update_stage_stats(
                        model=sequence.model,
                        stage=TaskStatus.PREPROCESSING.value,
                        duration_seconds=duration_seconds,
                    )
                return sequence
            except Exception as exc:
                duration_seconds = time.perf_counter() - started_at
                self._logger.warning(
                    "stage.failed",
                    stage=self.name,
                    duration_seconds=round(duration_seconds, 6),
                    error=str(exc),
                )
                raise
            finally:
                observe_stage_duration(
                    stage=self.name,
                    duration_seconds=time.perf_counter() - started_at,
                )

    async def _read_input_bytes(self, input_url: str) -> bytes:
        try:
            normalized_input_url = validate_image_url(
                input_url,
                allow_local_inputs=self._allow_local_inputs,
            )
        except TaskSubmissionValidationError as exc:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=str(exc),
            ) from exc

        input_url = normalized_input_url
        parsed = urlparse(input_url)
        if parsed.scheme in {"http", "https"}:
            return await self._download_http_image(input_url)
        if parsed.scheme == "upload":
            return await self._read_uploaded_file(parsed)
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
                "unsupported input_url; expected http(s), upload://, file://, data:, "
                "or an existing local file path"
            ),
        )

    async def _read_uploaded_file(self, parsed_input_url) -> bytes:
        upload_id = (parsed_input_url.netloc or parsed_input_url.path.lstrip("/")).strip()
        if not upload_id:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message="upload URL is missing upload_id",
            )

        matches = sorted(self._uploads_dir.glob(f"{upload_id}.*"))
        if not matches:
            raise StageExecutionError(
                stage_name=TaskStatus.PREPROCESSING.value,
                message=f"uploaded input image not found: {upload_id}",
            )
        return await self._read_local_file(str(matches[0]))

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

    async def _persist_input_artifact(
        self,
        task_id: str,
        image_bytes: bytes,
        content_type: str | None,
    ) -> dict | None:
        if self._artifact_store is None:
            return None

        async with self._artifact_store.create_staging_path(task_id, "input.png") as staging_path:
            await asyncio.to_thread(staging_path.write_bytes, image_bytes)
            try:
                return await self._artifact_store.publish_artifact(
                    task_id=task_id,
                    artifact_type="input",
                    file_name="input.png",
                    staging_path=staging_path,
                    content_type=content_type,
                )
            except ArtifactStoreOperationError as exc:
                raise StageExecutionError(exc.stage_name, str(exc)) from exc

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

    @staticmethod
    def _detect_image_content_type(image_bytes: bytes) -> str | None:
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return None
