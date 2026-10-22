"""Standalone Printbuddy Connector agent."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import platform
import secrets
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets
from pydantic import ValidationError

from connector.discovery import discover_lan
from connector.flashforge_control import execute_control
from connector.flashforge_files import list_flashforge_files
from connector.flashforge_temperature import execute_temperature
from connector.flashforge_upload import (
    MAX_ACTIVE_UPLOAD_SESSIONS,
    MAX_UPLOAD_STAGING_BYTES,
    UPLOAD_SESSION_TTL_SECONDS,
    UploadSession,
    upload_to_flashforge,
)
from connector.provider_verification import get_provider_status, verify_provider
from connector_protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    ConnectorDiscoveryRequest,
    ConnectorDiscoveryResult,
    ConnectorMessage,
    ConnectorPrinterControlRequest,
    ConnectorPrinterControlResult,
    ConnectorPrinterFilesRequest,
    ConnectorPrinterFilesResult,
    ConnectorPrinterStatusRequest,
    ConnectorPrinterStatusResult,
    ConnectorPrinterTemperatureRequest,
    ConnectorPrinterTemperatureResult,
    ConnectorPrinterUploadRequest,
    ConnectorPrinterUploadResult,
    ConnectorPrinterVerifyRequest,
    ConnectorPrinterVerifyResult,
)

logger = logging.getLogger("printbuddy.connector")


def _server_http_url(server_url: str) -> str:
    value = server_url.rstrip("/")
    if value.startswith("wss://"):
        return "https://" + value[6:]
    if value.startswith("ws://"):
        return "http://" + value[5:]
    return value


def _server_ws_url(server_url: str) -> str:
    value = server_url.rstrip("/")
    if value.startswith("https://"):
        return "wss://" + value[8:]
    if value.startswith("http://"):
        return "ws://" + value[7:]
    return value


class ConnectorAgent:
    def __init__(
        self,
        server_url: str,
        state_path: Path,
        enrollment_code: str | None = None,
        stop_event: threading.Event | None = None,
    ) -> None:
        self.server_url = server_url
        self.state_path = state_path
        self.enrollment_code = enrollment_code
        self.connector_id: str | None = None
        self.credential: str | None = None
        self.stop_event = stop_event or threading.Event()
        self._load_state()
        self._uploads: dict[str, UploadSession] = {}

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        data = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.connector_id = data.get("connector_id")
        self.credential = data.get("credential")

    def _save_state(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps({"connector_id": self.connector_id, "credential": self.credential}, indent=2),
            encoding="utf-8",
        )
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        temp_path.replace(self.state_path)

    async def enroll(self) -> None:
        if self.connector_id and self.credential:
            return
        if not self.enrollment_code:
            raise RuntimeError("PRINTBUDDY_ENROLLMENT_CODE is required for first enrollment")
        payload = {
            "enrollment_code": self.enrollment_code,
            "version": os.getenv("PRINTBUDDY_CONNECTOR_VERSION", "0.1.0"),
            "platform": f"{sys.platform}/{platform.machine()}",
            "protocol_version": PROTOCOL_VERSION,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{_server_http_url(self.server_url)}/api/v1/connectors/enroll", json=payload)
            response.raise_for_status()
            data = response.json()
        self.connector_id = data["connector_id"]
        self.credential = data["credential"]
        self.enrollment_code = None
        self._save_state()
        logger.info("Connector enrolled: %s", self.connector_id)

    async def run(self) -> None:
        await self.enroll()
        assert self.connector_id and self.credential
        ws_url = f"{_server_ws_url(self.server_url)}/api/v1/connectors/ws"
        backoff = 1.0
        while not self.stop_event.is_set():
            try:
                connect_options = {
                    "max_size": MAX_FRAME_BYTES,
                    "ping_interval": 20,
                    "ping_timeout": 20,
                }
                header_option = (
                    "additional_headers"
                    if "additional_headers" in inspect.signature(websockets.connect).parameters
                    else "extra_headers"
                )
                connect_options[header_option] = {"Authorization": f"Bearer {self.credential}"}
                async with websockets.connect(ws_url, **connect_options) as websocket:
                    backoff = 1.0
                    accepted = await websocket.recv()
                    logger.info("Connector session accepted")
                    _ = accepted  # Do not log server payloads or credentials.
                    send_lock = asyncio.Lock()
                    heartbeat_task = asyncio.create_task(self._heartbeat_loop(websocket, send_lock))
                    receive_task = asyncio.create_task(self._receive_loop(websocket, send_lock))
                    upload_cleanup_task = asyncio.create_task(self._upload_cleanup_loop())
                    stop_task = asyncio.create_task(asyncio.to_thread(self.stop_event.wait))
                    session_tasks = {heartbeat_task, receive_task, upload_cleanup_task, stop_task}
                    try:
                        done, pending = await asyncio.wait(
                            session_tasks,
                            return_when=asyncio.FIRST_COMPLETED,
                        )
                        for task in pending:
                            task.cancel()
                        await asyncio.gather(*pending, return_exceptions=True)
                        for task in done:
                            if task is not stop_task:
                                task.result()
                        if stop_task in done:
                            return
                    finally:
                        for task in session_tasks:
                            if not task.done():
                                task.cancel()
                        await asyncio.gather(*session_tasks, return_exceptions=True)
                        self._close_uploads()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Connector connection unavailable; retrying in %.1fs (%s)", backoff, type(exc).__name__)
                try:
                    await asyncio.wait_for(
                        asyncio.to_thread(self.stop_event.wait),
                        timeout=backoff + secrets.randbelow(500) / 1000,
                    )
                except asyncio.TimeoutError:
                    pass
                backoff = min(backoff * 2, 60.0)

    async def _heartbeat_loop(self, websocket: object, send_lock: asyncio.Lock) -> None:
        assert self.connector_id
        while not self.stop_event.is_set():
            heartbeat = ConnectorMessage(
                connector_id=self.connector_id,
                type="heartbeat",
                payload={
                    "version": os.getenv("PRINTBUDDY_CONNECTOR_VERSION", "0.1.0"),
                    "platform": f"{sys.platform}/{platform.machine()}",
                    "health": "ok",
                },
                sent_at=datetime.now(timezone.utc),
            )
            async with send_lock:
                await websocket.send(heartbeat.model_dump_json())
            try:
                await asyncio.wait_for(asyncio.to_thread(self.stop_event.wait), timeout=15)
            except asyncio.TimeoutError:
                pass

    def _close_uploads(self) -> None:
        sessions, self._uploads = self._uploads, {}
        for session in sessions.values():
            session.close()

    def _cleanup_expired_uploads(self, now: float | None = None) -> int:
        expired_ids = [upload_id for upload_id, session in self._uploads.items() if session.is_expired(now)]
        for upload_id in expired_ids:
            self._uploads.pop(upload_id).close()
        return len(expired_ids)

    async def _upload_cleanup_loop(self) -> None:
        while not self.stop_event.is_set():
            self._cleanup_expired_uploads()
            await asyncio.sleep(min(30, UPLOAD_SESSION_TTL_SECONDS / 2))

    async def _receive_loop(self, websocket: object, send_lock: asyncio.Lock) -> None:
        assert self.connector_id
        while not self.stop_event.is_set():
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=1)
            except asyncio.TimeoutError:
                continue
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8")
            message = ConnectorMessage.model_validate_json(raw)
            if message.connector_id != self.connector_id:
                raise RuntimeError("Connector ID mismatch in server message")
            if message.type not in {"discovery.request", "printer.verify.request", "printer.status.request", "printer.files.request", "printer.upload.request", "printer.control.request", "printer.temperature.request"}:
                continue
            request_id = str(message.payload.get("request_id", ""))
            temperature_heater = message.payload.get("heater")
            if temperature_heater not in {"nozzle", "bed", "chamber"}:
                temperature_heater = "unknown"
            temperature_target = message.payload.get("target")
            if isinstance(temperature_target, bool) or not isinstance(temperature_target, int) or not 0 <= temperature_target <= 320:
                temperature_target = 0
            safe_validation_error = "invalid Connector request"
            try:
                if message.type == "discovery.request":
                    request = ConnectorDiscoveryRequest.model_validate(message.payload)
                    entries = await discover_lan(request)
                    result = ConnectorDiscoveryResult(
                        request_id=request.request_id,
                        status="completed",
                        results=entries,
                    )
                elif message.type == "printer.verify.request":
                    request = ConnectorPrinterVerifyRequest.model_validate(message.payload)
                    verification = await verify_provider(request)
                    result = ConnectorPrinterVerifyResult(
                        request_id=request.request_id,
                        status="completed",
                        reachable=verification.reachable,
                        provider=request.provider,
                        protocol=verification.protocol,
                        service=verification.service,
                        model=verification.model,
                        error=verification.error,
                    )
                elif message.type == "printer.status.request":
                    request = ConnectorPrinterStatusRequest.model_validate(message.payload)
                    status = await get_provider_status(request)
                    result = ConnectorPrinterStatusResult(
                        request_id=request.request_id,
                        status="completed",
                        connected=status.connected,
                        state=status.state if status.state in {"reachable", "unreachable", "unknown"} else status.state,
                        telemetry=status.telemetry,
                        error=status.error,
                    )
                elif message.type == "printer.files.request":
                    request = ConnectorPrinterFilesRequest.model_validate(message.payload)
                    files, completeness, source = await list_flashforge_files(request)
                    result = ConnectorPrinterFilesResult(
                        request_id=request.request_id,
                        status="completed",
                        path=request.path,
                        files=files,
                        completeness=completeness,
                        source=source,
                    )
                elif message.type == "printer.upload.request":
                    request = ConnectorPrinterUploadRequest.model_validate(message.payload)
                    self._cleanup_expired_uploads()
                    if request.phase == "begin":
                        if request.upload_id in self._uploads:
                            raise ValueError("Upload ID is already active")
                        if len(self._uploads) >= MAX_ACTIVE_UPLOAD_SESSIONS:
                            raise ValueError("Too many active upload sessions")
                        staged_bytes = sum(item.request.size for item in self._uploads.values())
                        if staged_bytes + request.size > MAX_UPLOAD_STAGING_BYTES:
                            raise ValueError("Upload staging size limit exceeded")
                        self._uploads[request.upload_id] = UploadSession(request)
                        result = ConnectorPrinterUploadResult(
                            request_id=request.request_id, upload_id=request.upload_id, status="accepted"
                        )
                    elif request.phase == "abort":
                        session = self._uploads.pop(request.upload_id, None)
                        if session:
                            session.close()
                        result = ConnectorPrinterUploadResult(
                            request_id=request.request_id, upload_id=request.upload_id, status="aborted"
                        )
                    else:
                        session = self._uploads.get(request.upload_id)
                        if session is None:
                            raise ValueError("Upload session was not found")
                        if request.phase == "chunk":
                            received = session.accept_chunk(request)
                            result = ConnectorPrinterUploadResult(
                                request_id=request.request_id,
                                upload_id=request.upload_id,
                                status="accepted",
                                received_bytes=received,
                            )
                        else:
                            path = session.finish(request)
                            try:
                                await upload_to_flashforge(session.request, path)
                            finally:
                                session.close()
                                self._uploads.pop(request.upload_id, None)
                            result = ConnectorPrinterUploadResult(
                                request_id=request.request_id,
                                upload_id=request.upload_id,
                                status="completed",
                                received_bytes=session.received,
                            )
                else:
                    if message.type == "printer.control.request":
                        request = ConnectorPrinterControlRequest.model_validate(message.payload)
                        before, after, filename = await execute_control(request)
                        result = ConnectorPrinterControlResult(
                            request_id=request.request_id, status="completed", action=request.action,
                            state_before=before, state_after=after, filename=filename,
                        )
                    else:
                        request = ConnectorPrinterTemperatureRequest.model_validate(message.payload)
                        observed = await execute_temperature(request)
                        result = ConnectorPrinterTemperatureResult(
                            request_id=request.request_id, status="completed", heater=request.heater,
                            target=request.target, observed=observed,
                        )
            except ValueError as exc:
                error_message = safe_validation_error if isinstance(exc, ValidationError) else str(exc)
                if message.type == "discovery.request":
                    result = ConnectorDiscoveryResult(request_id=request_id, status="failed", error=error_message)
                elif message.type == "printer.verify.request":
                    result = ConnectorPrinterVerifyResult(
                        request_id=request_id,
                        status="failed",
                        provider=str(message.payload.get("provider", "unknown")),
                        protocol="tcp",
                        service="printer-endpoint",
                        error=error_message,
                    )
                elif message.type == "printer.status.request":
                    result = ConnectorPrinterStatusResult(request_id=request_id, status="failed", error=error_message)
                elif message.type == "printer.upload.request":
                    upload_id = str(message.payload.get("upload_id", ""))
                    if message.payload.get("phase") in {"chunk", "finish"}:
                        session = self._uploads.pop(upload_id, None)
                        if session:
                            session.close()
                    result = ConnectorPrinterUploadResult(
                        request_id=request_id,
                        upload_id=upload_id or "unknown",
                        status="failed",
                        error=error_message,
                    )
                elif message.type == "printer.control.request":
                    result = ConnectorPrinterControlResult(
                        request_id=request_id,
                        status="failed",
                        action=str(message.payload.get("action", "unknown")),
                        error=error_message,
                    )
                elif message.type == "printer.temperature.request":
                    result = ConnectorPrinterTemperatureResult(
                        request_id=request_id, status="failed",
                        heater=temperature_heater, target=temperature_target, error=error_message,
                    )
                else:
                    result = ConnectorPrinterFilesResult(request_id=request_id, status="failed", error=error_message)
            except Exception as exc:
                logger.warning("Connector printer operation failed (%s)", type(exc).__name__)
                if message.type == "discovery.request":
                    result = ConnectorDiscoveryResult(request_id=request_id, status="failed", error="operation failed")
                elif message.type == "printer.verify.request":
                    result = ConnectorPrinterVerifyResult(
                        request_id=request_id,
                        status="failed",
                        provider=str(message.payload.get("provider", "unknown")),
                        protocol="tcp",
                        service="printer-endpoint",
                        error="operation failed",
                    )
                elif message.type == "printer.status.request":
                    result = ConnectorPrinterStatusResult(
                        request_id=request_id,
                        status="failed",
                        error="operation failed",
                    )
                elif message.type == "printer.upload.request":
                    upload_id = str(message.payload.get("upload_id", ""))
                    if message.payload.get("phase") in {"chunk", "finish"}:
                        session = self._uploads.pop(upload_id, None)
                        if session:
                            session.close()
                    result = ConnectorPrinterUploadResult(
                        request_id=request_id,
                        upload_id=upload_id or "unknown",
                        status="failed",
                        error="operation failed",
                    )
                elif message.type == "printer.control.request":
                    result = ConnectorPrinterControlResult(
                        request_id=request_id,
                        status="failed",
                        action=str(message.payload.get("action", "unknown")),
                        error="operation failed",
                    )
                elif message.type == "printer.temperature.request":
                    result = ConnectorPrinterTemperatureResult(
                        request_id=request_id, status="failed",
                        heater=temperature_heater, target=temperature_target, error="operation failed",
                    )
                else:
                    result = ConnectorPrinterFilesResult(request_id=request_id, status="failed", error="operation failed")
            response_type = {
                "discovery.request": "discovery.result",
                "printer.verify.request": "printer.verify.result",
                "printer.status.request": "printer.status.result",
                "printer.files.request": "printer.files.result",
                "printer.upload.request": "printer.upload.result",
                "printer.control.request": "printer.control.result",
                "printer.temperature.request": "printer.temperature.result",
            }[message.type]
            response = ConnectorMessage(
                connector_id=self.connector_id,
                type=response_type,
                payload=result.model_dump(mode="json"),
                sent_at=datetime.now(timezone.utc),
            )
            async with send_lock:
                await websocket.send(response.model_dump_json())


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")
    server_url = os.getenv("PRINTBUDDY_SERVER_URL")
    if not server_url:
        raise SystemExit("PRINTBUDDY_SERVER_URL is required")
    state_path = Path(os.getenv("PRINTBUDDY_CONNECTOR_STATE", "connector-state.json"))
    asyncio.run(
        ConnectorAgent(
            server_url,
            state_path,
            enrollment_code=os.getenv("PRINTBUDDY_ENROLLMENT_CODE"),
        ).run()
    )


if __name__ == "__main__":
    main()
