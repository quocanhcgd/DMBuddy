"""Unit tests for the in-process Connector session registry."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.app.services.connector_gateway import ConnectorGateway, ConnectorRequestDeliveryUnknown


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
    assert await gateway.resolve_request("connector-2", None, "discovery.result", {"request_id": "wrong"}) is False
    request_frame = websocket.send_json.await_args.args[0]
    request_id = request_frame["payload"]["request_id"]
    session = await gateway.get("connector-1")
    assert await gateway.resolve_request("connector-2", session, "discovery.result", {"request_id": request_id}) is False
    replacement_session = type(session)("connector-1", AsyncMock(), asyncio.Lock())
    assert await gateway.resolve_request("connector-1", replacement_session, "discovery.result", {"request_id": request_id}) is False
    assert await gateway.resolve_request("connector-1", session, "printer.status.result", {"request_id": request_id}) is False
    assert await gateway.resolve_request("connector-1", session, "discovery.result", {"request_id": request_id, "status": "completed"}) is True
    assert await pending == {"request_id": request_id, "status": "completed"}


@pytest.mark.asyncio
async def test_gateway_request_times_out_and_cleans_pending_registry():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    await gateway.register("connector-1", websocket)

    assert await gateway.request("connector-1", "discovery.request", {}, timeout=0.001) is None
    assert gateway.metrics()["request_timeouts_total"] == 1
    assert gateway._pending == {}


@pytest.mark.asyncio
async def test_gateway_cancellation_while_sending_cleans_pending_entry():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    entered_send = asyncio.Event()
    finish_send = asyncio.Event()

    async def blocked_send(_message):
        entered_send.set()
        await finish_send.wait()

    websocket.send_json.side_effect = blocked_send
    await gateway.register("connector-1", websocket)
    pending = asyncio.create_task(
        gateway.request("connector-1", "printer.control.request", {"request_id": "cancel-send"}, timeout=1)
    )
    await entered_send.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert gateway._pending == {}


@pytest.mark.asyncio
async def test_gateway_timeout_covers_send_and_cleans_pending_entry():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    send_started = asyncio.Event()

    async def blocked_send(_message):
        send_started.set()
        await asyncio.Event().wait()

    websocket.send_json.side_effect = blocked_send
    await gateway.register("connector-1", websocket)

    with pytest.raises(ConnectorRequestDeliveryUnknown) as error:
        await gateway.request(
            "connector-1", "printer.control.request", {"request_id": "send-timeout"}, timeout=0.001
        )
    assert error.value.request_id == "send-timeout"
    assert gateway._pending == {}
    assert gateway.metrics()["request_timeouts_total"] == 1


@pytest.mark.asyncio
async def test_gateway_counts_late_response_after_timeout():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    session = await gateway.register("connector-1", websocket)
    with pytest.raises(ConnectorRequestDeliveryUnknown):
        await gateway.request(
            "connector-1", "printer.control.request", {"request_id": "late-control"}, timeout=0.001
        )
    assert await gateway.resolve_request(
        "connector-1", session, "printer.control.result", {"request_id": "late-control"}
    ) is False
    assert gateway.metrics()["late_or_unknown_responses_total"] == 1


@pytest.mark.asyncio
async def test_gateway_reports_delivery_unknown_when_side_effect_session_disconnects_after_send():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    session = await gateway.register("connector-1", websocket)
    pending = asyncio.create_task(
        gateway.request("connector-1", "printer.temperature.request", {"request_id": "temp-disconnect"}, timeout=1)
    )
    await asyncio.sleep(0)
    await gateway.unregister(session)

    with pytest.raises(ConnectorRequestDeliveryUnknown) as error:
        await pending
    assert error.value.request_id == "temp-disconnect"
    assert gateway.metrics()["request_delivery_unknown_total"] == 1


@pytest.mark.asyncio
async def test_gateway_keeps_pre_send_timeout_as_not_delivered():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    session = await gateway.register("connector-1", websocket)
    await session.send_lock.acquire()

    try:
        assert await gateway.request(
            "connector-1", "printer.control.request", {"request_id": "lock-timeout"}, timeout=0.001
        ) is None
    finally:
        session.send_lock.release()
    websocket.send_json.assert_not_awaited()


@pytest.mark.asyncio
async def test_gateway_rejects_duplicate_pending_request_ids():
    gateway = ConnectorGateway()
    websocket = AsyncMock()
    await gateway.register("connector-1", websocket)
    pending = asyncio.create_task(
        gateway.request("connector-1", "discovery.request", {"request_id": "same"}, timeout=1)
    )
    await asyncio.sleep(0)
    with pytest.raises(ValueError, match="already pending"):
        await gateway.request("connector-1", "discovery.request", {"request_id": "same"}, timeout=1)
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert gateway._pending == {}


@pytest.mark.asyncio
async def test_gateway_replacement_completes_old_requests_and_rejects_old_session_response():
    gateway = ConnectorGateway()
    first = AsyncMock()
    old_session = await gateway.register("connector-1", first)
    pending = asyncio.create_task(
        gateway.request("connector-1", "printer.control.request", {"request_id": "control-1"}, timeout=1)
    )
    await asyncio.sleep(0)
    second = AsyncMock()
    new_session = await gateway.register("connector-1", second)
    with pytest.raises(ConnectorRequestDeliveryUnknown):
        await pending
    assert await gateway.resolve_request(
        "connector-1", old_session, "printer.control.result", {"request_id": "control-1"}
    ) is False
    assert await gateway.unregister(new_session) is True
