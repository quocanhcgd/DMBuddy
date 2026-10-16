"""Unit tests for bounded LAN discovery performed by a Connector."""

import asyncio

import pytest

from connector.discovery import discover_lan, probe_endpoint
from connector_protocol import ConnectorDiscoveryRequest


class _Writer:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_discovery_returns_sanitized_reachable_endpoints():
    calls: list[tuple[str, int]] = []

    async def open_connection(host: str, port: int):
        calls.append((host, port))
        if host == "192.168.10.1" and port == 7125:
            return object(), _Writer()
        raise OSError("connection refused")

    request = ConnectorDiscoveryRequest(
        request_id="req-1",
        subnet="192.168.10.0/30",
        ports=[80, 7125],
        max_hosts=4,
        timeout_ms=100,
    )
    results = await discover_lan(request, open_connection=open_connection)

    assert len(calls) == 4
    assert [entry.model_dump() for entry in results] == [
        {
            "ip_address": "192.168.10.1",
            "port": 7125,
            "protocol": "http",
            "service": "moonraker",
            "reachable": True,
        }
    ]


@pytest.mark.asyncio
async def test_discovery_rejects_public_and_oversized_networks():
    public = ConnectorDiscoveryRequest(request_id="req-1", subnet="8.8.8.0/24", ports=[80])
    oversized = ConnectorDiscoveryRequest(request_id="req-2", subnet="192.168.0.0/16", ports=[80], max_hosts=256)

    with pytest.raises(ValueError, match="private LAN"):
        await discover_lan(public)
    with pytest.raises(ValueError, match="host limit"):
        await discover_lan(oversized)


@pytest.mark.asyncio
async def test_discovery_closes_successful_connections():
    writers: list[_Writer] = []

    async def open_connection(host: str, port: int):
        writer = _Writer()
        writers.append(writer)
        return object(), writer

    request = ConnectorDiscoveryRequest(request_id="req-3", subnet="10.0.0.1/32", ports=[80], max_hosts=1)
    await discover_lan(request, open_connection=open_connection)
    assert writers[0].closed is True


@pytest.mark.asyncio
async def test_endpoint_probe_requires_private_ip_and_closes_socket():
    writer = _Writer()
    calls = []

    async def open_connection(host: str, port: int):
        calls.append((host, port))
        return object(), writer

    assert await probe_endpoint("192.168.1.8", 8883, 100, open_connection=open_connection) is True
    assert writer.closed is True
    assert calls == [("192.168.1.8", 8883)]
    with pytest.raises(ValueError, match="private IP"):
        await probe_endpoint("printer.local", 8883, 100, open_connection=open_connection)
    with pytest.raises(ValueError, match="private LAN"):
        await probe_endpoint("8.8.8.8", 443, 100, open_connection=open_connection)
