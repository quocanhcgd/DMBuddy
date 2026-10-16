"""Bounded private-LAN discovery used by the standalone Connector.

The scanner deliberately performs TCP reachability checks only.  Printer
verification and credentials remain separate operations handled by a later
transport task; discovery never accepts arbitrary URLs or returns banners.
"""

from __future__ import annotations

import asyncio
import ipaddress
from collections.abc import Awaitable, Callable

from connector_protocol import (
    ConnectorDiscoveryRequest,
    ConnectorDiscoveryResultEntry,
    ConnectorPrinterStatusRequest,
    ConnectorPrinterVerifyRequest,
)

_MAX_HOSTS = 256
_MAX_PORTS = 16
_MAX_CONCURRENCY = 64

_SERVICE_BY_PORT = {
    80: ("http", "http"),
    443: ("https", "https"),
    7125: ("http", "moonraker"),
    8883: ("mqtts", "bambu-mqtt"),
    990: ("ftps", "bambu-ftps"),
}


def validate_discovery_request(request: ConnectorDiscoveryRequest) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
    """Validate discovery bounds again on the agent, even if server validated them."""

    try:
        network = ipaddress.ip_network(request.subnet, strict=False)
    except ValueError as exc:
        raise ValueError("subnet must be valid CIDR notation") from exc
    if (
        not network.is_private
        or network.is_loopback
        or network.is_link_local
        or network.is_multicast
        or network.is_unspecified
    ):
        raise ValueError("discovery is limited to private LAN subnets")
    if network.num_addresses > min(request.max_hosts, _MAX_HOSTS):
        raise ValueError("subnet is larger than the discovery host limit")
    if len(request.ports) > _MAX_PORTS or any(port < 1 or port > 65535 for port in request.ports):
        raise ValueError("ports must be between 1 and 65535")
    return network


def _service_for_port(port: int) -> tuple[str, str]:
    return _SERVICE_BY_PORT.get(port, ("tcp", "tcp"))


def validate_private_endpoint(host: str, port: int) -> None:
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("printer endpoint must be a private IP address") from exc
    if (
        not address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
    ):
        raise ValueError("printer endpoint must be a private LAN address")
    if port < 1 or port > 65535:
        raise ValueError("port must be between 1 and 65535")


async def probe_endpoint(
    host: str,
    port: int,
    timeout_ms: int,
    *,
    open_connection: Callable[..., Awaitable[tuple[object, object]]] = asyncio.open_connection,
) -> bool:
    """Probe one private endpoint without reading banners or sending credentials."""

    validate_private_endpoint(host, port)
    writer = None
    try:
        _, writer = await asyncio.wait_for(
            open_connection(host, port),
            timeout=timeout_ms / 1000,
        )
        return True
    except (OSError, asyncio.TimeoutError):
        return False
    finally:
        if writer is not None:
            writer.close()
            wait_closed = getattr(writer, "wait_closed", None)
            if wait_closed is not None:
                await wait_closed()


async def verify_printer_endpoint(
    request: ConnectorPrinterVerifyRequest,
    *,
    open_connection: Callable[..., Awaitable[tuple[object, object]]] = asyncio.open_connection,
) -> bool:
    return await probe_endpoint(request.ip_address, request.port, request.timeout_ms, open_connection=open_connection)


async def probe_printer_status(
    request: ConnectorPrinterStatusRequest,
    *,
    open_connection: Callable[..., Awaitable[tuple[object, object]]] = asyncio.open_connection,
) -> bool:
    return await probe_endpoint(request.ip_address, request.port, request.timeout_ms, open_connection=open_connection)


async def discover_lan(
    request: ConnectorDiscoveryRequest,
    *,
    open_connection: Callable[..., Awaitable[tuple[object, object]]] = asyncio.open_connection,
) -> list[ConnectorDiscoveryResultEntry]:
    """Probe bounded host/port pairs and return only sanitized reachability data."""

    network = validate_discovery_request(request)
    addresses = list(network.hosts())
    if not addresses and network.num_addresses == 1:
        addresses = [network.network_address]
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    timeout = request.timeout_ms / 1000

    async def probe(
        address: ipaddress.IPv4Address | ipaddress.IPv6Address,
        port: int,
    ) -> ConnectorDiscoveryResultEntry | None:
        async with semaphore:
            writer = None
            try:
                _, writer = await asyncio.wait_for(
                    open_connection(str(address), port),
                    timeout=timeout,
                )
                protocol, service = _service_for_port(port)
                return ConnectorDiscoveryResultEntry(
                    ip_address=str(address),
                    port=port,
                    protocol=protocol,
                    service=service,
                    reachable=True,
                )
            except (OSError, asyncio.TimeoutError):
                return None
            finally:
                if writer is not None:
                    writer.close()
                    wait_closed = getattr(writer, "wait_closed", None)
                    if wait_closed is not None:
                        await wait_closed()

    tasks = [probe(address, port) for address in addresses for port in sorted(set(request.ports))]
    results = await asyncio.gather(*tasks)
    return [result for result in results if result is not None][:256]

