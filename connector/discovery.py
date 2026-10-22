"""Bounded private-LAN discovery used by the standalone Connector.

The scanner deliberately performs TCP reachability checks only.  Printer
verification and credentials remain separate operations handled by a later
transport task; discovery never accepts arbitrary URLs or returns banners.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections.abc import Awaitable, Callable

from connector_protocol import (
    ConnectorDiscoveryRequest,
    ConnectorDiscoveryResultEntry,
    ConnectorPrinterStatusRequest,
    ConnectorPrinterVerifyRequest,
)
from flashforge_discovery import parse_discovery_response, parse_m115_response

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
_FLASHFORGE_DISCOVERY_PORTS = frozenset({8899, 19000, 48899})
_FLASHFORGE_MULTICAST = "225.0.0.9"
_FLASHFORGE_HTTP_PORT = 8898


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

    generic_ports = sorted(set(request.ports) - _FLASHFORGE_DISCOVERY_PORTS)
    tasks = [probe(address, port) for address in addresses for port in generic_ports]
    results = await asyncio.gather(*tasks)
    sanitized = [result for result in results if result is not None]
    if _FLASHFORGE_DISCOVERY_PORTS.intersection(request.ports):
        sanitized.extend(await discover_flashforge_lan(request))
    return sanitized[:256]


def _flashforge_targets(network: ipaddress.IPv4Network | ipaddress.IPv6Network) -> list[str]:
    """Return bounded unicast/broadcast targets for a discovery request."""

    targets = [str(address) for address in network.hosts()]
    if not targets and network.num_addresses == 1:
        targets.append(str(network.network_address))
    if isinstance(network, ipaddress.IPv4Network):
        targets.append(str(network.broadcast_address))
    return targets


def _flashforge_entry(parsed: object) -> ConnectorDiscoveryResultEntry | None:
    """Convert parser output into a safe endpoint result."""

    result = parsed
    http_port = getattr(result, "http_port", None)
    command_port = getattr(result, "command_port", None)
    model = getattr(result, "model", None)
    adapter_type = getattr(result, "adapter_type", None)
    port = http_port or command_port
    if not port:
        return None
    return ConnectorDiscoveryResultEntry(
        ip_address=str(result.host),
        port=port,
        protocol="http" if http_port else "udp",
        service="flashforge-http" if http_port else "flashforge-discovery",
        reachable=True,
        provider=adapter_type,
        model=None if model == "Unknown" else model,
        serial_number=getattr(result, "serial_number", None) or None,
    )


async def discover_flashforge_lan(
    request: ConnectorDiscoveryRequest,
    *,
    socket_factory: Callable[..., socket.socket] = socket.socket,
) -> list[ConnectorDiscoveryResultEntry]:
    """Listen for bounded FlashForge UDP discovery responses.

    FlashForge printers answer a zero-length datagram on multicast/broadcast
    discovery ports. The blocking socket is isolated in a worker thread so the
    Connector's WebSocket heartbeat remains responsive.
    """

    network = validate_discovery_request(request)
    ports = sorted(_FLASHFORGE_DISCOVERY_PORTS.intersection(request.ports))
    if not ports:
        return []

    def _collect() -> list[ConnectorDiscoveryResultEntry]:
        sock = socket_factory(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        found: dict[tuple[str, int], ConnectorDiscoveryResultEntry] = {}
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(max(0.05, request.timeout_ms / 1000))
            sock.bind(("", 0))
            for port in ports:
                try:
                    sock.sendto(b"", (_FLASHFORGE_MULTICAST, port))
                except OSError:
                    pass
                for target in _flashforge_targets(network):
                    try:
                        sock.sendto(b"", (target, port))
                    except OSError:
                        continue

            deadline = time.monotonic() + max(0.5, request.timeout_ms / 1000 * 4)
            while time.monotonic() < deadline and len(found) < 256:
                try:
                    packet, address = sock.recvfrom(4096)
                except TimeoutError:
                    break
                except OSError:
                    break
                parsed = parse_discovery_response(packet, address[0])
                entry = _flashforge_entry(parsed) if parsed is not None else None
                if entry is not None:
                    found[(entry.ip_address, entry.port)] = entry
            return list(found.values())
        finally:
            sock.close()

    results = await asyncio.to_thread(_collect)
    if results:
        return results
    return await discover_flashforge_m115(request)


async def discover_flashforge_m115(
    request: ConnectorDiscoveryRequest,
    *,
    open_connection: Callable[..., Awaitable[tuple[object, object]]] = asyncio.open_connection,
) -> list[ConnectorDiscoveryResultEntry]:
    """Probe private hosts with the AD5M ``~M115`` identity command."""

    network = validate_discovery_request(request)
    if 8899 not in request.ports:
        return []
    semaphore = asyncio.Semaphore(_MAX_CONCURRENCY)
    timeout = request.timeout_ms / 1000

    async def probe(host: str) -> ConnectorDiscoveryResultEntry | None:
        async with semaphore:
            reader = writer = None
            try:
                reader, writer = await asyncio.wait_for(open_connection(host, 8899), timeout=timeout)
                writer.write(b"~M115\n")
                drain = getattr(writer, "drain", None)
                if drain is not None:
                    await drain()
                data = await asyncio.wait_for(reader.read(4096), timeout=timeout)
                parsed = parse_m115_response(data.decode("utf-8", errors="ignore"), host)
                return _flashforge_entry(parsed) if parsed is not None else None
            except (OSError, asyncio.TimeoutError):
                return None
            finally:
                if writer is not None:
                    writer.close()
                    wait_closed = getattr(writer, "wait_closed", None)
                    if wait_closed is not None:
                        await wait_closed()

    results = await asyncio.gather(*(probe(str(address)) for address in network.hosts()))
    return [result for result in results if result is not None][:256]

