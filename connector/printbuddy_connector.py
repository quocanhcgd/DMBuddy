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

from connector.discovery import discover_lan, probe_printer_status
from connector.provider_verification import verify_provider
from connector_protocol import (
    MAX_FRAME_BYTES,
    PROTOCOL_VERSION,
    ConnectorDiscoveryRequest,
    ConnectorDiscoveryResult,
    ConnectorMessage,
    ConnectorPrinterStatusRequest,
    ConnectorPrinterStatusResult,
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
                    stop_task = asyncio.create_task(asyncio.to_thread(self.stop_event.wait))
                    done, pending = await asyncio.wait(
                        {heartbeat_task, receive_task, stop_task},
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
            if message.type not in {"discovery.request", "printer.verify.request", "printer.status.request"}:
                continue
            request_id = str(message.payload.get("request_id", ""))
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
                else:
                    request = ConnectorPrinterStatusRequest.model_validate(message.payload)
                    reachable = await probe_printer_status(request)
                    result = ConnectorPrinterStatusResult(
                        request_id=request.request_id,
                        status="completed",
                        connected=reachable,
                        state="reachable" if reachable else "unreachable",
                    )
            except ValueError as exc:
                if message.type == "discovery.request":
                    result = ConnectorDiscoveryResult(request_id=request_id, status="failed", error=str(exc))
                elif message.type == "printer.verify.request":
                    result = ConnectorPrinterVerifyResult(
                        request_id=request_id,
                        status="failed",
                        provider=str(message.payload.get("provider", "unknown")),
                        protocol="tcp",
                        service="printer-endpoint",
                        error=str(exc),
                    )
                else:
                    result = ConnectorPrinterStatusResult(request_id=request_id, status="failed", error=str(exc))
            except Exception:
                logger.warning("Connector printer operation failed", exc_info=True)
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
                else:
                    result = ConnectorPrinterStatusResult(
                        request_id=request_id,
                        status="failed",
                        error="operation failed",
                    )
            response_type = {
                "discovery.request": "discovery.result",
                "printer.verify.request": "printer.verify.result",
                "printer.status.request": "printer.status.result",
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
