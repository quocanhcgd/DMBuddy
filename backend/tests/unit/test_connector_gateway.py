"""Unit tests for the in-process Connector session registry."""

from unittest.mock import AsyncMock

import pytest

from backend.app.services.connector_gateway import ConnectorGateway


@pytest.mark.asyncio
async def test_gateway_register_send_and_unregister():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    session = await gateway.register("connector-1", websocket)

    assert gateway.is_online("connector-1") is True
    assert await gateway.send("connector-1", {"type": "heartbeat.ack"}) is True
    websocket.send_json.assert_awaited_once_with({"type": "heartbeat.ack"})
    assert await gateway.unregister(session) is True
    assert gateway.is_online("connector-1") is False
    assert await gateway.send("connector-1", {}) is False
    metrics = gateway.metrics()
    assert metrics["active_sessions"] == 0
    assert metrics["sessions_started_total"] == 1
    assert metrics["session_disconnects_total"] == 1


@pytest.mark.asyncio
async def test_gateway_replaces_previous_session():
    gateway = ConnectorGateway()
    first = AsyncMock()
    second = AsyncMock()
    first_session = await gateway.register("connector-1", first)
    second_session = await gateway.register("connector-1", second)

    first.close.assert_awaited_once_with(code=4001, reason="Replaced by a newer Connector session")
    assert await gateway.unregister(first_session) is False
    assert await gateway.unregister(second_session) is True
    metrics = gateway.metrics()
    assert metrics["sessions_started_total"] == 2
    assert metrics["session_replacements_total"] == 1
