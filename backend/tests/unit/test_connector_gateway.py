"""Unit tests for the in-process Connector session registry."""

import asyncio
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


@pytest.mark.asyncio
async def test_gateway_request_resolves_for_matching_connector():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    await gateway.register("connector-1", websocket)

    pending = asyncio.create_task(
        gateway.request("connector-1", "discovery.request", {"subnet": "192.168.1.0/24"}, timeout=1)
    )
    await asyncio.sleep(0)
    assert await gateway.resolve_request("connector-2", {"request_id": "wrong"}) is False
    request_frame = websocket.send_json.await_args.args[0]
    request_id = request_frame["payload"]["request_id"]
    assert await gateway.resolve_request("connector-2", {"request_id": request_id}) is False
    assert await gateway.resolve_request("connector-1", {"request_id": request_id, "status": "completed"}) is True
    assert await pending == {"request_id": request_id, "status": "completed"}


@pytest.mark.asyncio
async def test_gateway_request_times_out_and_cleans_pending_registry():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    await gateway.register("connector-1", websocket)

    assert await gateway.request("connector-1", "discovery.request", {}, timeout=0.001) is None
    assert gateway.metrics()["request_timeouts_total"] == 1
