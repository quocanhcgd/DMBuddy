"""Connector discovery tests for FlashForge UDP result normalization."""

import pytest

from connector.discovery import _flashforge_entry, discover_flashforge_lan, discover_flashforge_m115, discover_lan
from connector_protocol import ConnectorDiscoveryRequest, ConnectorDiscoveryResultEntry
from flashforge_discovery import parse_discovery_response


def _modern_packet(product_id: int) -> bytes:
    packet = bytearray(276)
    packet[:7] = b"Printer"
    packet[0x84:0x86] = (8899).to_bytes(2, "big")
    packet[0x88:0x8A] = product_id.to_bytes(2, "big")
    packet[0x8E:0x90] = (8898).to_bytes(2, "big")
    packet[0x92:0x9A] = b"FF-0001\0"
    return bytes(packet)


def test_flashforge_entry_exposes_http_endpoint_and_identity():
    parsed = parse_discovery_response(_modern_packet(0x0023), "192.168.1.50")

    entry = _flashforge_entry(parsed)

    assert isinstance(entry, ConnectorDiscoveryResultEntry)
    assert entry.ip_address == "192.168.1.50"
    assert entry.port == 8898
    assert entry.provider == "flashforge_ad5m"
    assert entry.model == "Adventurer 5M"
    assert entry.serial_number == "FF-0001"


def test_flashforge_entry_does_not_return_creator_command_port():
    parsed = parse_discovery_response(_modern_packet(0x0029), "10.0.0.50")

    entry = _flashforge_entry(parsed)

    assert entry is not None
    assert entry.port == 8898
    assert entry.provider == "flashforge_creator5"


class _FakeSocket:
    def __init__(self, packet: bytes) -> None:
        self.packet = packet
        self.sent: list[tuple[bytes, tuple[str, int]]] = []
        self.closed = False

    def setsockopt(self, *_args) -> None:
        return None

    def settimeout(self, _timeout: float) -> None:
        return None

    def bind(self, _address) -> None:
        return None

    def sendto(self, payload: bytes, address: tuple[str, int]) -> None:
        self.sent.append((payload, address))

    def recvfrom(self, _size: int) -> tuple[bytes, tuple[str, int]]:
        if self.packet is not None:
            packet, self.packet = self.packet, None
            return packet, ("192.168.1.50", 8899)
        raise TimeoutError

    def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_flashforge_udp_discovery_is_bounded_and_returns_http_identity():
    fake = _FakeSocket(_modern_packet(0x0023))

    def factory(*_args):
        return fake

    request = ConnectorDiscoveryRequest(
        request_id="ff-1",
        subnet="192.168.1.0/30",
        ports=[8899],
        max_hosts=4,
        timeout_ms=100,
    )
    results = await discover_flashforge_lan(request, socket_factory=factory)

    assert len(results) == 1
    assert results[0].provider == "flashforge_ad5m"
    assert results[0].port == 8898
    assert fake.closed is True
    assert all(payload == b"" for payload, _address in fake.sent)
    assert len(fake.sent) == 4  # multicast + two hosts + directed broadcast


@pytest.mark.asyncio
async def test_generic_tcp_probe_skips_flashforge_discovery_ports(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def open_connection(host: str, port: int):
        calls.append((host, port))
        raise OSError("closed")

    async def no_udp(_request):
        return []

    monkeypatch.setattr("connector.discovery.discover_flashforge_lan", no_udp)
    request = ConnectorDiscoveryRequest(
        request_id="ff-2",
        subnet="192.168.1.0/30",
        ports=[8899, 80],
        max_hosts=4,
        timeout_ms=100,
    )

    await discover_lan(request, open_connection=open_connection)

    assert calls
    assert all(port == 80 for _host, port in calls)


class _FakeReader:
    async def read(self, _size: int) -> bytes:
        return b"Machine Type: FlashForge Adventurer 5M\nSN: FF-42\nok\n"


class _FakeWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, value: bytes) -> None:
        self.writes.append(value)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


@pytest.mark.asyncio
async def test_m115_fallback_only_returns_ad5m_identity_and_closes_connection():
    writers: list[_FakeWriter] = []

    async def open_connection(host: str, port: int):
        assert host in {"192.168.1.1", "192.168.1.2"}
        assert port == 8899
        writer = _FakeWriter()
        writers.append(writer)
        return _FakeReader(), writer

    request = ConnectorDiscoveryRequest(
        request_id="ff-3",
        subnet="192.168.1.0/30",
        ports=[8899],
        max_hosts=4,
        timeout_ms=100,
    )
    results = await discover_flashforge_m115(request, open_connection=open_connection)

    assert len(results) == 2
    assert {entry.model for entry in results} == {"Adventurer 5M"}
    assert all(entry.port == 8898 for entry in results)
    assert [writer.writes for writer in writers] == [[b"~M115\n"], [b"~M115\n"]]
    assert all(writer.closed for writer in writers)
