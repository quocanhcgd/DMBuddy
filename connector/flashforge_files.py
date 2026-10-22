"""Read-only FlashForge file listing for the standalone Connector."""

from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

from connector.discovery import validate_private_endpoint
from connector_protocol import ConnectorPrinterFileEntry, ConnectorPrinterFilesRequest

_MAX_FILES = 256
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_EXTENSIONS = (".gcode", ".gx", ".g", ".3mf")


def _parse_m661(value: str) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        candidate = raw.replace("\x00", "").strip()
        candidate = re.sub(r"^/data/", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^0:/user/", "", candidate, flags=re.IGNORECASE)
        candidate = candidate.rsplit("/", 1)[-1].strip()
        if candidate and candidate.lower().endswith(_EXTENSIONS) and candidate not in seen and len(names) < _MAX_FILES:
            seen.add(candidate)
            names.append(candidate)

    for segment in value.split("::"):
        index = segment.find("/data/")
        if index >= 0:
            add(re.split(r"[\r\n\x00]", segment[index:], maxsplit=1)[0])
    for line in value.splitlines():
        line = line.strip()
        if not line or "::" in line or line.lower() == "ok" or re.match(r"^info_list\.size\s*:", line, re.I):
            continue
        if re.fullmatch(r"CMD\s+M661\s+Received\.?", line, re.I):
            continue
        add(line)
    return names


async def _read_quiet(reader: asyncio.StreamReader, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    chunks = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if chunks:
                return bytes(chunks)
            raise TimeoutError("FlashForge TCP response timed out")
        try:
            chunk = await asyncio.wait_for(reader.read(min(65536, _MAX_RESPONSE_BYTES + 1 - len(chunks))), min(1.4, remaining))
        except asyncio.TimeoutError:
            if chunks:
                return bytes(chunks)
            continue
        if not chunk:
            return bytes(chunks)
        chunks.extend(chunk)
        if len(chunks) > _MAX_RESPONSE_BYTES:
            raise ValueError("FlashForge response exceeded size limit")


async def _ad5m_tcp(request: ConnectorPrinterFilesRequest) -> list[str]:
    port = request.tcp_port or 8899
    validate_private_endpoint(request.ip_address, port)
    reader, writer = await asyncio.wait_for(asyncio.open_connection(request.ip_address, port), request.timeout_ms / 1000)
    try:
        writer.write(b"~M601 S1\n")
        await asyncio.wait_for(writer.drain(), request.timeout_ms / 1000)
        acquired = (await _read_quiet(reader, request.timeout_ms / 1000)).decode("utf-8", "ignore").lower()
        if "control success" not in acquired and not re.search(r"(?:^|\n)ok(?:\r?\n|$)", acquired, re.I):
            raise RuntimeError("FlashForge TCP control session was not accepted")
        writer.write(b"~M661\n")
        await asyncio.wait_for(writer.drain(), request.timeout_ms / 1000)
        return _parse_m661((await _read_quiet(reader, request.timeout_ms / 1000)).decode("utf-8", "replace"))
    finally:
        try:
            writer.write(b"~M602\n")
            await asyncio.wait_for(writer.drain(), 1.0)
        except (OSError, asyncio.TimeoutError, RuntimeError):
            pass
        writer.close()
        try:
            await writer.wait_closed()
        except OSError:
            pass


def _recent_names(payload: dict[str, Any]) -> list[str]:
    values = payload.get("gcodeList")
    if not isinstance(values, list):
        values = payload.get("gcodeListDetail")
        values = [row.get("gcodeFileName") for row in values if isinstance(row, dict)] if isinstance(values, list) else []
    names: list[str] = []
    seen: set[str] = set()
    for value in values:
        name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if name and name.lower().endswith(_EXTENSIONS) and name not in seen and len(names) < _MAX_FILES:
            seen.add(name)
            names.append(name)
    return names


async def _http_recent(request: ConnectorPrinterFilesRequest) -> list[str]:
    validate_private_endpoint(request.ip_address, request.http_port)
    if not request.serial_number or not request.access_code:
        raise ValueError("serial number and check code are required")
    async with httpx.AsyncClient(timeout=request.timeout_ms / 1000, follow_redirects=False, trust_env=False) as client:
        response = await client.post(
            f"http://{request.ip_address}:{request.http_port}/gcodeList",
            json={"serialNumber": request.serial_number, "checkCode": request.access_code},
        )
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError("FlashForge HTTP endpoint unavailable")
    content = getattr(response, "content", b"")
    if isinstance(content, (bytes, bytearray)) and len(content) > _MAX_RESPONSE_BYTES:
        raise ValueError("FlashForge response exceeded size limit")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError("FlashForge credentials rejected")
    return _recent_names(payload)


async def list_flashforge_files(request: ConnectorPrinterFilesRequest) -> tuple[list[ConnectorPrinterFileEntry], str, str]:
    """Return sanitized entries, completeness and source."""
    if request.path not in {"", "/"}:
        raise ValueError("FlashForge only supports the printer root directory")
    provider = request.provider.lower().strip()
    if provider == "flashforge_ad5m":
        try:
            names = await _ad5m_tcp(request)
            source, completeness = "tcp-m661", "complete"
        except Exception:
            names = await _http_recent(request)
            source, completeness = "http-recent", "recent_only"
    elif provider == "flashforge_creator5":
        names = await _http_recent(request)
        source, completeness = "http-recent", "recent_only"
    else:
        raise ValueError("Connector file listing is unavailable for this provider")
    return [ConnectorPrinterFileEntry(name=name, path=f"/{name}") for name in names], completeness, source
