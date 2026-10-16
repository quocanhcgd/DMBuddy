"""Unit coverage for Connector message handling."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from connector.printbuddy_connector import ConnectorAgent
from connector_protocol import ConnectorMessage


class _WebSocket:
    def __init__(self, incoming: str) -> None:
        self.incoming = incoming
        self.sent: list[str] = []

    async def recv(self) -> str:
        if self.incoming is not None:
            value = self.incoming
            self.incoming = None
            return value
        raise RuntimeError("stop test receive loop")

    async def send(self, value: str) -> None:
        self.sent.append(value)


@pytest.mark.asyncio
async def test_agent_answers_discovery_request_without_logging_or_forwarding_secrets(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="discovery.request",
        payload={
            "request_id": "req-1",
            "subnet": "192.168.1.0/30",
            "ports": [7125],
            "max_hosts": 4,
            "timeout_ms": 100,
        },
    )
    monkeypatch.setattr(
        "connector.printbuddy_connector.discover_lan",
        lambda value: _fake_discovery(value),
    )
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "discovery.result"
    assert response.payload["request_id"] == "req-1"
    assert response.payload["results"][0]["ip_address"] == "192.168.1.2"
    assert "credential" not in json.dumps(response.payload)


@pytest.mark.asyncio
async def test_agent_answers_verify_request_without_credentials(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="printer.verify.request",
        payload={
            "request_id": "verify-1",
            "ip_address": "192.168.1.10",
            "port": 8883,
            "provider": "bambu",
            "serial_number": "SERIAL-1",
            "timeout_ms": 100,
        },
    )
    probe = AsyncMock(return_value=True)
    monkeypatch.setattr("connector.printbuddy_connector.verify_printer_endpoint", probe)
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.verify.result"
    assert response.payload["reachable"] is True
    assert "access_code" not in json.dumps(response.payload)
    probe.assert_awaited_once()


async def _fake_discovery(request):
    return [
        {
            "ip_address": "192.168.1.2",
            "port": request.ports[0],
            "protocol": "http",
            "service": "moonraker",
            "reachable": True,
        }
    ]
