"""Transport boundary for printers reached directly or through a Connector.

Only discovery is implemented in this increment.  The boundary is deliberately
small so status, control and file capabilities can be added without making API
routes aware of WebSocket sessions or LAN sockets.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from backend.app.schemas.connector import ConnectorDiscoveryResponse
from backend.app.services.connector_gateway import (
    ConnectorGateway,
    ConnectorRequestDeliveryUnknown,
    connector_gateway,
)


class PrinterTransportError(RuntimeError):
    """Base error for a transport operation."""


class CapabilityUnavailableError(PrinterTransportError):
    """The selected transport/provider does not implement an operation yet."""


class ConnectorOfflineError(PrinterTransportError):
    """The bound Connector is not currently available."""


class ConnectorDeliveryUnknownError(ConnectorOfflineError):
    """A side-effect may have been delivered, but its result was not confirmed."""

    def __init__(self, request_id: str) -> None:
        super().__init__("Connector did not confirm the operation; delivery outcome is unknown")
        self.request_id = request_id
        self.outcome = "delivery_unknown"


class PrinterTransport(Protocol):
    async def discover(
        self,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> ConnectorDiscoveryResponse: ...

    async def verify(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]: ...

    async def status(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]: ...

    async def files(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]: ...

    async def upload_file(
        self, payload: Mapping[str, Any], local_path: Path, *, filename: str, timeout: float
    ) -> Mapping[str, Any]: ...

    async def temperature(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]: ...


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

    async def verify(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        del payload, timeout
        raise CapabilityUnavailableError("direct printer verification is not enabled by this transport")

    async def status(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        del payload, timeout
        raise CapabilityUnavailableError("direct printer status is not enabled by this transport")

    async def files(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        del payload, timeout
        raise CapabilityUnavailableError("direct printer file listing is not enabled by this transport")

    async def upload_file(
        self, payload: Mapping[str, Any], local_path: Path, *, filename: str, timeout: float
    ) -> Mapping[str, Any]:
        del payload, local_path, timeout
        raise CapabilityUnavailableError("direct printer upload is not enabled by this transport")

    async def temperature(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        del payload, timeout
        raise CapabilityUnavailableError("direct printer temperature control is not enabled by this transport")


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

    async def verify(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return await self._request("printer.verify.request", payload, timeout=timeout)

    async def status(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return await self._request("printer.status.request", payload, timeout=timeout)

    async def files(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return await self._request("printer.files.request", payload, timeout=timeout)

    async def upload_file(
        self, payload: Mapping[str, Any], local_path: Path, *, filename: str, timeout: float
    ) -> Mapping[str, Any]:
        upload_id = str(uuid4())
        size = local_path.stat().st_size
        base = {**dict(payload), "upload_id": upload_id, "filename": filename, "size": size}
        try:
            result = await self._request(
                "printer.upload.request", {**base, "request_id": str(uuid4()), "phase": "begin"}, timeout=timeout
            )
            if result.get("status") not in {"accepted", "completed"}:
                return result
            chunk_size = 96 * 1024
            with local_path.open("rb") as stream:
                index = 0
                while chunk := stream.read(chunk_size):
                    result = await self._request(
                        "printer.upload.request",
                        {
                            **base,
                            "request_id": str(uuid4()),
                            "phase": "chunk",
                            "chunk_index": index,
                            "data_b64": base64.b64encode(chunk).decode("ascii"),
                        },
                        timeout=timeout,
                    )
                    if result.get("status") != "accepted":
                        return result
                    index += 1
            return await self._request(
                "printer.upload.request", {**base, "request_id": str(uuid4()), "phase": "finish"}, timeout=timeout
            )
        except (Exception, asyncio.CancelledError):
            await self._abort_upload(base, timeout=timeout)
            raise

    async def _abort_upload(self, payload: Mapping[str, Any], *, timeout: float) -> None:
        try:
            await asyncio.shield(
                self._request(
                    "printer.upload.request",
                    {**dict(payload), "request_id": str(uuid4()), "phase": "abort"},
                    timeout=min(max(timeout, 0.1), 3.0),
                )
            )
        except (Exception, asyncio.CancelledError):
            return

    async def control(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return await self._request("printer.control.request", payload, timeout=timeout)

    async def temperature(self, payload: Mapping[str, Any], *, timeout: float) -> Mapping[str, Any]:
        return await self._request("printer.temperature.request", payload, timeout=timeout)

    async def _request(
        self,
        message_type: str,
        payload: Mapping[str, Any],
        *,
        timeout: float,
    ) -> Mapping[str, Any]:
        try:
            response = await self.gateway.request(self.connector_id, message_type, dict(payload), timeout=timeout)
        except ConnectorRequestDeliveryUnknown as exc:
            raise ConnectorDeliveryUnknownError(exc.request_id) from exc
        if response is None:
            raise ConnectorOfflineError("Connector did not return a response")
        return response


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

