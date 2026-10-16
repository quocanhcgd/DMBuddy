"""Tests for the printer transport boundary."""

from unittest.mock import AsyncMock

import pytest

from backend.app.services.printer_transport import (
    CapabilityUnavailableError,
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
async def test_direct_transport_does_not_silently_scan_from_server():
    with pytest.raises(CapabilityUnavailableError):
        await DirectPrinterTransport().discover({}, timeout=1)


def test_transport_factory_keeps_connection_modes_explicit():
    assert isinstance(printer_transport_for_mode("direct"), DirectPrinterTransport)
    assert isinstance(printer_transport_for_mode("vpn"), DirectPrinterTransport)
    assert isinstance(printer_transport_for_mode("connector", "connector-1"), ConnectorPrinterTransport)
    with pytest.raises(ValueError):
        printer_transport_for_mode("unknown")
