"""Tests for the printer transport boundary."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.app.services.printer_transport import (
    CapabilityUnavailableError,
    ConnectorDeliveryUnknownError,
    ConnectorOfflineError,
    ConnectorPrinterTransport,
    DirectPrinterTransport,
    printer_transport_for_mode,
)


@pytest.mark.asyncio
async def test_connector_transport_validates_and_returns_discovery_result():
    gateway = AsyncMock()
    gateway.request.return_value = {
        "request_id": "request-1",
        "status": "completed",
        "results": [
            {
                "ip_address": "192.168.1.22",
                "port": 7125,
                "protocol": "http",
                "service": "moonraker",
                "reachable": True,
            }
        ],
    }
    transport = ConnectorPrinterTransport("connector-1", gateway)

    result = await transport.discover({"request_id": "request-1"}, timeout=2)

    assert result.request_id == "request-1"
    assert result.results[0]["service"] == "moonraker"
    gateway.request.assert_awaited_once_with("connector-1", "discovery.request", {"request_id": "request-1"}, timeout=2)


@pytest.mark.asyncio
async def test_connector_transport_reports_offline_without_direct_fallback():
    gateway = AsyncMock()
    gateway.request.return_value = None

    with pytest.raises(ConnectorOfflineError):
        await ConnectorPrinterTransport("connector-1", gateway).discover({}, timeout=1)


@pytest.mark.asyncio
async def test_connector_transport_preserves_delivery_unknown_without_retry():
    from backend.app.services.connector_gateway import ConnectorRequestDeliveryUnknown

    gateway = AsyncMock()
    gateway.request.side_effect = ConnectorRequestDeliveryUnknown("control-uncertain")
    transport = ConnectorPrinterTransport("connector-1", gateway)

    with pytest.raises(ConnectorDeliveryUnknownError) as error:
        await transport.control({"request_id": "control-uncertain", "action": "start"}, timeout=5)

    assert error.value.outcome == "delivery_unknown"
    assert error.value.request_id == "control-uncertain"
    gateway.request.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_transport_does_not_silently_scan_from_server():
    with pytest.raises(CapabilityUnavailableError):
        await DirectPrinterTransport().discover({}, timeout=1)
    with pytest.raises(CapabilityUnavailableError):
        await DirectPrinterTransport().verify({}, timeout=1)


def test_transport_factory_keeps_connection_modes_explicit():
    assert isinstance(printer_transport_for_mode("direct"), DirectPrinterTransport)
    assert isinstance(printer_transport_for_mode("vpn"), DirectPrinterTransport)
    assert isinstance(printer_transport_for_mode("connector", "connector-1"), ConnectorPrinterTransport)
    with pytest.raises(ValueError):
        printer_transport_for_mode("unknown")


@pytest.mark.asyncio
async def test_connector_transport_supports_typed_verify_and_status_messages():
    gateway = AsyncMock()
    gateway.request.side_effect = [
        {"request_id": "verify-1", "status": "completed", "reachable": True},
        {"request_id": "status-1", "status": "completed", "connected": True, "state": "reachable"},
    ]
    transport = ConnectorPrinterTransport("connector-1", gateway)

    verified = await transport.verify({"request_id": "verify-1"}, timeout=5)
    status = await transport.status({"request_id": "status-1"}, timeout=5)

    assert verified["reachable"] is True
    assert status["state"] == "reachable"
    assert gateway.request.await_args_list[0].args == ("connector-1", "printer.verify.request", {"request_id": "verify-1"})
    assert gateway.request.await_args_list[1].args == ("connector-1", "printer.status.request", {"request_id": "status-1"})


@pytest.mark.asyncio
async def test_connector_transport_supports_read_only_file_listing():
    gateway = AsyncMock()
    gateway.request.return_value = {
        "request_id": "files-1",
        "status": "completed",
        "path": "/",
        "files": [{"name": "cube.gcode", "path": "/cube.gcode", "type": "file"}],
        "completeness": "recent_only",
        "source": "http-recent",
    }
    result = await ConnectorPrinterTransport("connector-1", gateway).files({"request_id": "files-1"}, timeout=5)
    assert result["files"][0]["name"] == "cube.gcode"
    gateway.request.assert_awaited_once_with(
        "connector-1", "printer.files.request", {"request_id": "files-1"}, timeout=5
    )


@pytest.mark.asyncio
async def test_connector_transport_uploads_in_bounded_chunks(tmp_path):
    local_path = tmp_path / "cube.gcode"
    local_path.write_bytes(b"hello world")
    gateway = AsyncMock()
    async def upload_response(_connector_id, _message_type, payload, *, timeout):
        del timeout
        phase = payload["phase"]
        return {
            "request_id": payload["request_id"],
            "upload_id": payload["upload_id"],
            "status": "completed" if phase == "finish" else "accepted",
            "received_bytes": 11 if phase != "begin" else 0,
        }

    gateway.request.side_effect = upload_response
    result = await ConnectorPrinterTransport("connector-1", gateway).upload_file(
        {"request_id": "begin", "ip_address": "192.168.1.10", "provider": "flashforge_ad5m"},
        local_path,
        filename="cube.gcode",
        timeout=20,
    )
    assert result["status"] == "completed"
    assert gateway.request.await_count == 3
    assert gateway.request.await_args_list[1].args[2]["phase"] == "chunk"
    request_ids = [call.args[2]["request_id"] for call in gateway.request.await_args_list]
    assert len(set(request_ids)) == 3


@pytest.mark.asyncio
async def test_connector_transport_aborts_staging_when_a_phase_times_out(tmp_path):
    local_path = tmp_path / "cube.gcode"
    local_path.write_bytes(b"hello world")
    gateway = AsyncMock()
    gateway.request.side_effect = [
        {"status": "accepted"},
        None,
        {"status": "aborted"},
    ]
    transport = ConnectorPrinterTransport("connector-1", gateway)

    with pytest.raises(ConnectorOfflineError):
        await transport.upload_file(
            {"ip_address": "192.168.1.10", "provider": "flashforge_ad5m"},
            local_path,
            filename="cube.gcode",
            timeout=5,
        )

    assert gateway.request.await_count == 3
    assert gateway.request.await_args_list[-1].args[2]["phase"] == "abort"


@pytest.mark.asyncio
async def test_connector_transport_shields_abort_cleanup_during_cancellation(tmp_path):
    local_path = tmp_path / "cube.gcode"
    local_path.write_bytes(b"hello world")
    chunk_started = asyncio.Event()
    gateway = AsyncMock()

    async def upload_response(_connector_id, _message_type, payload, *, timeout):
        del timeout
        phase = payload["phase"]
        if phase == "chunk":
            chunk_started.set()
            await asyncio.Event().wait()
        return {"status": "aborted" if phase == "abort" else "accepted"}

    gateway.request.side_effect = upload_response
    task = asyncio.create_task(
        ConnectorPrinterTransport("connector-1", gateway).upload_file(
            {"ip_address": "192.168.1.10", "provider": "flashforge_ad5m"},
            local_path,
            filename="cube.gcode",
            timeout=5,
        )
    )
    await chunk_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    phases = [call.args[2]["phase"] for call in gateway.request.await_args_list]
    assert phases == ["begin", "chunk", "abort"]


@pytest.mark.asyncio
async def test_connector_transport_supports_job_control():
    gateway = AsyncMock()
    gateway.request.return_value = {
        "request_id": "control-1",
        "status": "completed",
        "action": "pause",
        "state_before": "RUNNING",
        "state_after": "PAUSE",
    }
    result = await ConnectorPrinterTransport("connector-1", gateway).control(
        {"request_id": "control-1", "action": "pause"}, timeout=12
    )
    assert result["state_after"] == "PAUSE"
    gateway.request.assert_awaited_once_with(
        "connector-1", "printer.control.request", {"request_id": "control-1", "action": "pause"}, timeout=12
    )


@pytest.mark.asyncio
async def test_connector_transport_supports_temperature_control():
    gateway = AsyncMock()
    gateway.request.return_value = {
        "request_id": "temperature-1", "status": "completed", "heater": "nozzle",
        "target": 210, "observed": 210,
    }
    result = await ConnectorPrinterTransport("connector-1", gateway).temperature(
        {"request_id": "temperature-1", "heater": "nozzle", "target": 210}, timeout=12
    )
    assert result["observed"] == 210
    gateway.request.assert_awaited_once_with(
        "connector-1", "printer.temperature.request",
        {"request_id": "temperature-1", "heater": "nozzle", "target": 210}, timeout=12
    )
