"""Minimal standalone Printbuddy Connector agent.

Phase 1 deliberately implements enrollment, authenticated WSS, heartbeat and
clean reconnect only. It does not scan the LAN or control printers yet.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import platform
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import websockets

from connector_protocol import MAX_FRAME_BYTES, PROTOCOL_VERSION, ConnectorMessage

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
    def __init__(self, server_url: str, state_path: Path, enrollment_code: str | None = None) -> None:
        self.server_url = server_url
        self.state_path = state_path
        self.enrollment_code = enrollment_code
        self.connector_id: str | None = None
        self.credential: str | None = None
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
        while True:
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
                    while True:
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
                        await websocket.send(heartbeat.model_dump_json())
                        await asyncio.wait_for(websocket.recv(), timeout=30)
                        await asyncio.sleep(15)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Connector connection unavailable; retrying in %.1fs (%s)", backoff, type(exc).__name__)
                await asyncio.sleep(backoff + secrets.randbelow(500) / 1000)
                backoff = min(backoff * 2, 60.0)


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
