from __future__ import annotations

import asyncio
import uuid
from email.parser import BytesParser
from email.policy import default as default_email_policy
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Request, status

from cubie.api.helpers.auth import build_require_bearer_token
from cubie.api.schemas import UploadImageResponse

if TYPE_CHECKING:
    from cubie.api.server import AppContainer


ALLOWED_UPLOAD_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


async def extract_uploaded_file(request: Request) -> tuple[str, str, bytes]:
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type.lower():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="content-type must be multipart/form-data",
        )

    body = await request.body()
    message = BytesParser(policy=default_email_policy).parsebytes(
        (
            f"Content-Type: {content_type}\r\n"
            "MIME-Version: 1.0\r\n\r\n"
        ).encode("utf-8")
        + body
    )
    if not message.is_multipart():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="invalid multipart form payload",
        )

    for part in message.iter_parts():
        if part.get_param("name", header="content-disposition") != "file":
            continue
        filename = part.get_filename() or "upload"
        part_content_type = part.get_content_type()
        payload = part.get_payload(decode=True) or b""
        return filename, part_content_type, payload

    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="multipart form must include a file field",
    )


def build_upload_router(container: AppContainer) -> APIRouter:
    router = APIRouter()
    require_bearer_token = build_require_bearer_token(container)

    @router.post(
        "/v1/upload",
        response_model=UploadImageResponse,
        status_code=status.HTTP_201_CREATED,
    )
    async def upload_image(
        request: Request,
        key_id: str = Depends(require_bearer_token),
    ) -> UploadImageResponse:
        del key_id
        _, content_type, payload = await extract_uploaded_file(request)
        content_type = content_type.strip().lower()
        extension = ALLOWED_UPLOAD_CONTENT_TYPES.get(content_type)
        if extension is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "unsupported file type; allowed content types: "
                    "image/jpeg, image/png, image/webp, image/gif"
                ),
            )

        if len(payload) > container.config.preprocess_max_image_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "uploaded file exceeds max size of "
                    f"{container.config.preprocess_max_image_bytes} bytes"
                ),
            )

        upload_id = uuid.uuid4().hex
        destination = container.config.uploads_dir / f"{upload_id}{extension}"
        await asyncio.to_thread(destination.write_bytes, payload)
        return UploadImageResponse(
            upload_id=upload_id,
            url=f"upload://{upload_id}",
        )

    return router
