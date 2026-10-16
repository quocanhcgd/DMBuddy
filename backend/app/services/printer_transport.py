"""Transport boundary for printers reached directly or through a Connector.

Only discovery is implemented in this increment.  The boundary is deliberately
small so status, control and file capabilities can be added without making API
routes aware of WebSocket sessions or LAN sockets.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from backend.app.schemas.connector import ConnectorDiscoveryResponse
from backend.app.services.connector_gateway import ConnectorGateway, connector_gateway


class PrinterTransportError(RuntimeError):
    """Base error for a transport operation."""


class CapabilityUnavailableError(PrinterTransportError):
    """The selected transport/provider does not implement an operation yet."""


class ConnectorOfflineError(PrinterTransportError):
    """The bound Connector is not currently available."""


class PrinterTransport(Protocol):
    async def discover(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> ConnectorDiscoveryResponse: ...


class DirectPrinterTransport:
    """Direct mode placeholder until local discovery is routed through a provider."""

    async def discover(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> ConnectorDiscoveryResponse:
        del payload, timeout
        raise CapabilityUnavailableError("direct printer discovery is not enabled by this transport")


class ConnectorPrinterTransport:
    """Transport for requests sent over one authenticated Connector session."""

    def __init__(self, connector_id: str, gateway: ConnectorGateway | None = None) -> None:
        if not connector_id:
            raise ValueError("connector_id is required for connector transport")
        self.connector_id = connector_id
        self.gateway = gateway or connector_gateway

    async def discover(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> ConnectorDiscoveryResponse:
        response = await self.gateway.request(
            self.connector_id,
            "discovery.request",
            dict(payload),
            timeout=timeout,
        )
        if response is None:
            raise ConnectorOfflineError("Connector did not return a discovery result")
        return ConnectorDiscoveryResponse.model_validate(response)


def printer_transport_for_mode(
    connection_mode: str,
    connector_id: str | None = None,
    *,
    gateway: ConnectorGateway | None = None,
) -> PrinterTransport:
    """Build the transport boundary without silently falling back to direct LAN."""

    if connection_mode == "connector":
        return ConnectorPrinterTransport(connector_id or "", gateway)
    if connection_mode in {"direct", "vpn"}:
        return DirectPrinterTransport()
    raise ValueError(f"Unsupported printer connection mode: {connection_mode!r}")

