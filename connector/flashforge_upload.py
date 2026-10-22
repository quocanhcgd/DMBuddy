"""Bounded chunk receiver and FlashForge multipart uploader for Connector."""

from __future__ import annotations

import base64
import tempfile
import time
from pathlib import Path

from connector.discovery import validate_private_endpoint
from connector.flashforge_files import _EXTENSIONS
from connector_protocol import ConnectorPrinterUploadRequest

MAX_UPLOAD_BYTES = 512 * 1024 * 1024
MAX_UPLOAD_STAGING_BYTES = MAX_UPLOAD_BYTES
MAX_CHUNK_BYTES = 128 * 1024
UPLOAD_SESSION_TTL_SECONDS = 15 * 60
MAX_ACTIVE_UPLOAD_SESSIONS = 4


class UploadSession:
    def __init__(self, request: ConnectorPrinterUploadRequest) -> None:
        if request.provider.lower().strip() not in {"flashforge_ad5m", "flashforge_creator5"}:
            raise ValueError("Connector upload is unavailable for this provider")
        safe_filename = request.filename.replace("\\", "/").rsplit("/", 1)[-1]
        if not safe_filename or safe_filename in {".", ".."} or safe_filename != request.filename:
            raise ValueError("FlashForge upload filename must be a basename")
        if not safe_filename.lower().endswith(_EXTENSIONS):
            raise ValueError("Unsupported FlashForge print file extension")
        if request.size > MAX_UPLOAD_BYTES:
            raise ValueError("FlashForge upload exceeds size limit")
        self.request = request
        self.temp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - session owns the handle until finish/abort
            prefix="printbuddy-ff-", suffix=".upload", delete=False
        )
        self.path = Path(self.temp.name)
        self.received = 0
        self.next_index = 0
        self.last_activity = time.monotonic()

    def is_expired(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return current - self.last_activity >= UPLOAD_SESSION_TTL_SECONDS

    def accept_chunk(self, request: ConnectorPrinterUploadRequest) -> int:
        if request.upload_id != self.request.upload_id or request.phase != "chunk":
            raise ValueError("Invalid upload session")
        if request.chunk_index != self.next_index or not request.data_b64:
            raise ValueError("Unexpected upload chunk")
        try:
            data = base64.b64decode(request.data_b64, validate=True)
        except (ValueError, base64.binascii.Error) as exc:
            raise ValueError("Invalid upload chunk encoding") from exc
        if not data or len(data) > MAX_CHUNK_BYTES:
            raise ValueError("Invalid upload chunk size")
        if self.received + len(data) > self.request.size or self.received + len(data) > MAX_UPLOAD_BYTES:
            raise ValueError("Upload size exceeds declared size")
        self.temp.write(data)
        self.temp.flush()
        self.received += len(data)
        self.next_index += 1
        self.last_activity = time.monotonic()
        return self.received

    def finish(self, request: ConnectorPrinterUploadRequest) -> Path:
        if request.upload_id != self.request.upload_id or request.phase != "finish":
            raise ValueError("Invalid upload session")
        if self.received != self.request.size:
            raise ValueError("Upload size does not match declared size")
        self.temp.close()
        return self.path

    def close(self) -> None:
        try:
            self.temp.close()
        finally:
            self.path.unlink(missing_ok=True)


async def upload_to_flashforge(request: ConnectorPrinterUploadRequest, path: Path) -> None:
    """Upload through the provider HTTP API without exposing response bodies."""
    import httpx

    validate_private_endpoint(request.ip_address, request.http_port)
    if not request.serial_number or not request.access_code:
        raise ValueError("serial number and check code are required")
    headers = {
        "serialNumber": request.serial_number,
        "checkCode": request.access_code,
        "fileSize": str(request.size),
        "printNow": "false",
        "levelingBeforePrint": "false",
    }
    if request.provider.lower().strip() == "flashforge_creator5":
        headers.update({"useMatlStation": "true", "gcodeToolCnt": str(request.tool_count), "flowCalibration": "false", "timeLapseVideo": "false"})
    timeout = request.timeout_ms / 1000
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        with path.open("rb") as stream:
            response = await client.post(
                f"http://{request.ip_address}:{request.http_port}/uploadGcode",
                headers=headers,
                files={"gcodeFile": (request.filename, stream, "application/octet-stream")},
            )
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError("FlashForge upload endpoint unavailable")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError("FlashForge returned malformed upload response") from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError("FlashForge rejected the upload")
