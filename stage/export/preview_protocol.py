from __future__ import annotations

import json
import struct
from asyncio import StreamReader, StreamWriter
from typing import Any, BinaryIO

_HEADER_LENGTH_FORMAT = ">I"
_HEADER_LENGTH_SIZE = struct.calcsize(_HEADER_LENGTH_FORMAT)


def _encode_header(
    header: dict[str, Any],
    *,
    body_length: int,
) -> bytes:
    payload = dict(header)
    payload["body_length"] = body_length
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


async def write_message(
    writer: StreamWriter,
    header: dict[str, Any],
    body: bytes = b"",
) -> None:
    header_bytes = _encode_header(header, body_length=len(body))
    writer.write(struct.pack(_HEADER_LENGTH_FORMAT, len(header_bytes)))
    writer.write(header_bytes)
    if body:
        writer.write(body)
    await writer.drain()


async def read_message(
    reader: StreamReader,
) -> tuple[dict[str, Any], bytes]:
    header_length_bytes = await reader.readexactly(_HEADER_LENGTH_SIZE)
    header_length = struct.unpack(_HEADER_LENGTH_FORMAT, header_length_bytes)[0]
    header_bytes = await reader.readexactly(header_length)
    header = json.loads(header_bytes.decode("utf-8"))
    body_length = int(header.get("body_length") or 0)
    body = await reader.readexactly(body_length) if body_length > 0 else b""
    return header, body


def write_message_sync(
    writer: BinaryIO,
    header: dict[str, Any],
    body: bytes = b"",
) -> None:
    header_bytes = _encode_header(header, body_length=len(body))
    writer.write(struct.pack(_HEADER_LENGTH_FORMAT, len(header_bytes)))
    writer.write(header_bytes)
    if body:
        writer.write(body)
    writer.flush()


def read_message_sync(
    reader: BinaryIO,
) -> tuple[dict[str, Any], bytes]:
    header_length_bytes = _read_exact_sync(
        reader,
        _HEADER_LENGTH_SIZE,
        eof_message="unexpected EOF while reading preview renderer header length",
    )
    header_length = struct.unpack(_HEADER_LENGTH_FORMAT, header_length_bytes)[0]
    header_bytes = _read_exact_sync(
        reader,
        header_length,
        eof_message="unexpected EOF while reading preview renderer header",
    )
    header = json.loads(header_bytes.decode("utf-8"))
    body_length = int(header.get("body_length") or 0)
    body = (
        _read_exact_sync(
            reader,
            body_length,
            eof_message="unexpected EOF while reading preview renderer body",
        )
        if body_length > 0
        else b""
    )
    return header, body


def _read_exact_sync(
    reader: BinaryIO,
    length: int,
    *,
    eof_message: str,
) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining > 0:
        chunk = reader.read(remaining)
        if not chunk:
            raise EOFError(eof_message)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)
