"""Checks that uploaded bytes are a real PNG, JPEG or WebP image and reads its size.

The public website shows images that staff upload (``CenterMedia``, ADR 0029 H). The type is
decided by the bytes, never by the file name or the browser's content type, and the structure is
walked to its end: a PNG's chunks (lengths and CRCs) through ``IEND``, a JPEG's segments
through a frame header and the end marker, a WebP's RIFF length and its frame header. SVG and
anything else is refused (an SVG can carry script). Pure: no Django, no imaging library.

Error codes: ``MEDIA_INVALID_IMAGE``, ``MEDIA_IMAGE_TOO_BIG`` (pixel dimensions).
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from domain.errors import DomainError

__all__ = ["MAX_SIDE", "ImageInfo", "inspect_image"]

#: Largest width or height accepted, in pixels (a 2 MB file can still claim huge dimensions).
MAX_SIDE = 8000

_PNG = b"\x89PNG\r\n\x1a\n"


@dataclass(frozen=True, slots=True)
class ImageInfo:
    ext: str
    content_type: str
    width: int
    height: int


def _bad(message: str = "The file is not a PNG, JPEG or WebP image") -> DomainError:
    return DomainError("MEDIA_INVALID_IMAGE", message)


def _png(data: bytes) -> tuple[int, int]:
    pos = len(_PNG)
    size: tuple[int, int] | None = None
    first = True
    while True:
        if pos + 12 > len(data):
            raise _bad("The PNG image is cut short")
        (length,) = struct.unpack(">I", data[pos : pos + 4])
        kind = data[pos + 4 : pos + 8]
        end = pos + 8 + length
        if length > 0x7FFFFFFF or end + 4 > len(data):
            raise _bad("The PNG image is cut short")
        body = data[pos + 8 : end]
        (crc,) = struct.unpack(">I", data[end : end + 4])
        if zlib.crc32(kind + body) & 0xFFFFFFFF != crc:
            raise _bad("The PNG image is damaged")
        if first:
            if kind != b"IHDR" or length != 13:
                raise _bad("The PNG image has no header")
            size = struct.unpack(">II", body[:8])
            first = False
        pos = end + 4
        if kind == b"IEND":
            break
    if size is None:  # pragma: no cover - the first chunk is always read
        raise _bad("The PNG image has no header")
    return size


_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def _jpeg(data: bytes) -> tuple[int, int]:
    # Some cameras append data after the end marker, so it is looked for near the end only.
    if b"\xff\xd9" not in data[-4096:]:
        raise _bad("The JPEG image is cut short")
    pos = 2
    size: tuple[int, int] | None = None
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            raise _bad("The JPEG image is damaged")
        marker = data[pos + 1]
        if marker == 0xFF:  # fill byte
            pos += 1
            continue
        if marker in (0x01, *range(0xD0, 0xD8)):  # markers without a length
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2 : pos + 4])
        if length < 2 or pos + 2 + length > len(data):
            raise _bad("The JPEG image is cut short")
        if marker in _SOF:
            if length < 7:
                raise _bad("The JPEG image is damaged")
            height, width = struct.unpack(">HH", data[pos + 5 : pos + 9])
            size = (width, height)
        if marker == 0xDA:  # start of scan: the compressed data follows
            break
        pos += 2 + length
    if size is None:
        raise _bad("The JPEG image has no frame header")
    return size


def _webp(data: bytes) -> tuple[int, int]:
    (riff_size,) = struct.unpack("<I", data[4:8])
    if riff_size + 8 != len(data) or len(data) < 30:
        raise _bad("The WebP image is cut short")
    chunk = data[12:16]
    body = data[20:]
    if chunk == b"VP8 ":
        if body[3:6] != b"\x9d\x01\x2a":
            raise _bad("The WebP image is damaged")
        width, height = struct.unpack("<HH", body[6:10])
        return width & 0x3FFF, height & 0x3FFF
    if chunk == b"VP8L":
        if body[0] != 0x2F:
            raise _bad("The WebP image is damaged")
        bits = int.from_bytes(body[1:5], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8X":
        width = int.from_bytes(body[4:7], "little") + 1
        height = int.from_bytes(body[7:10], "little") + 1
        return width, height
    raise _bad("The WebP image is damaged")


def inspect_image(data: bytes) -> ImageInfo:
    """The type and pixel size of a PNG, JPEG or WebP image, judged by its bytes.

    Raises:
        DomainError: ``MEDIA_INVALID_IMAGE`` (another type, or a damaged or cut file),
            ``MEDIA_IMAGE_TOO_BIG`` (a side over ``MAX_SIDE`` pixels).
    """
    try:
        if data.startswith(_PNG):
            ext, content_type = "png", "image/png"
            width, height = _png(data)
        elif data.startswith(b"\xff\xd8\xff"):
            ext, content_type = "jpg", "image/jpeg"
            width, height = _jpeg(data)
        elif len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            ext, content_type = "webp", "image/webp"
            width, height = _webp(data)
        else:
            raise _bad()
    except (struct.error, IndexError):
        raise _bad("The image is damaged") from None
    if width < 1 or height < 1:
        raise _bad("The image has no pixels")
    if width > MAX_SIDE or height > MAX_SIDE:
        raise DomainError(
            "MEDIA_IMAGE_TOO_BIG",
            f"The image may be at most {MAX_SIDE} pixels on each side",
            max_side=MAX_SIDE,
        )
    return ImageInfo(ext, content_type, width, height)
