"""Shared on-disk thumbnail cache used by archives and the file library."""

from __future__ import annotations

from pathlib import Path

from backend.app.core.config import settings


def get_thumbnail_cache_dir() -> Path:
    """Return the persistent thumbnail directory shared by file views."""
    path = settings.archive_dir / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def media_extension(media_type: str) -> str:
    return {"image/jpeg": ".jpg", "image/webp": ".webp", "image/gif": ".gif"}.get(media_type, ".png")


def cache_thumbnail(key: str, data: bytes, media_type: str) -> Path:
    """Write a thumbnail atomically and return its path."""
    target = get_thumbnail_cache_dir() / f"{key}{media_extension(media_type)}"
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(target)
    return target
