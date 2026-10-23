"""Extract slicer thumbnails embedded in G-code files and 3MF archives."""

from __future__ import annotations

import base64
import binascii
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO


@dataclass(frozen=True)
class GcodeThumbnail:
    """Decoded thumbnail and its advertised dimensions."""

    data: bytes
    width: int
    height: int
    media_type: str


_BEGIN_RE = re.compile(
    rb"(?:^|\n)[ \t]*;[ \t]*thumbnail[ \t]+begin[ \t]+(\d+)x(\d+)(?:[ \t]+\d+)?[ \t]*\r?\n",
    re.IGNORECASE,
)
_END_RE = re.compile(rb"(?:^|\n)[ \t]*;[ \t]*thumbnail[ \t]+end[ \t]*\r?\n", re.IGNORECASE)


def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def extract_gcode_thumbnail(source: bytes, *, max_scan_bytes: int = 8 * 1024 * 1024) -> GcodeThumbnail | None:
    """Return the largest valid embedded thumbnail from a G-code payload.

    Slicers place thumbnails near the file header. Limiting the scan prevents a
    large print file from causing an unbounded text/base64 allocation while
    still covering normal Klipper exports.
    """
    if not source:
        return None
    payload = source[:max_scan_bytes]
    candidates: list[GcodeThumbnail] = []
    for begin in _BEGIN_RE.finditer(payload):
        end = _END_RE.search(payload, begin.end())
        if end is None:
            continue
        encoded = re.sub(rb"[^A-Za-z0-9+/=]", b"", payload[begin.end() : end.start()])
        if not encoded:
            continue
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            continue
        media_type = _image_type(decoded)
        if media_type is None:
            continue
        width, height = int(begin.group(1)), int(begin.group(2))
        if width <= 0 or height <= 0 or width > 4096 or height > 4096:
            continue
        candidates.append(GcodeThumbnail(decoded, width, height, media_type))
    return max(candidates, key=lambda item: (item.width * item.height, len(item.data)), default=None)


def extract_3mf_thumbnail(source: bytes, *, plate_index: int | None = None) -> GcodeThumbnail | None:
    """Return a preview image embedded in a slicer 3MF archive."""
    if not source:
        return None
    try:
        with zipfile.ZipFile(BytesIO(source)) as archive:
            names = set(archive.namelist())
            candidates = []
            if plate_index is not None:
                candidates.extend((f"Metadata/plate_{plate_index}.png", f"Metadata/plate_{plate_index}_small.png"))
            candidates.extend(
                (
                    "Metadata/plate_1.png",
                    "Metadata/thumbnail.png",
                    "Metadata/plate_1_small.png",
                    "Auxiliaries/.thumbnails/thumbnail_middle.png",
                    "Auxiliaries/.thumbnails/thumbnail_small.png",
                    "Auxiliaries/.thumbnails/thumbnail_3mf.png",
                    "Thumbnails/thumbnail.png",
                    "thumbnail.png",
                )
            )
            candidates.extend(
                name
                for name in archive.namelist()
                if name.startswith("Metadata/") and name.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            )
            for name in dict.fromkeys(candidates):
                if name not in names:
                    continue
                image = archive.read(name)
                media_type = _image_type(image)
                if media_type:
                    return GcodeThumbnail(image, 0, 0, media_type)
    except (OSError, zipfile.BadZipFile, RuntimeError):
        return None
    return None
