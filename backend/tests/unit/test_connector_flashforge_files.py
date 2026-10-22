import pytest

from connector.flashforge_files import list_flashforge_files
from connector_protocol import ConnectorPrinterFilesRequest


class _Reader:
    def __init__(self, chunks_by_command):
        self.chunks_by_command = [list(chunks) for chunks in chunks_by_command]
        self.command_index = 0

    async def read(self, _size):
        chunks = self.chunks_by_command[self.command_index] if self.command_index < len(self.chunks_by_command) else []
        if chunks:
            return chunks.pop(0)
        self.command_index += 1
        return b""


class _Writer:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, value):
        self.writes.append(value)

    async def drain(self):
        return None

    def close(self):
        self.closed = True

    async def wait_closed(self):
        return None


@pytest.mark.asyncio
async def test_ad5m_uses_m661_and_releases_control(monkeypatch):
    writer = _Writer()
    reader = _Reader([[b"control success\n"], [b"/data/cube.gcode\n/data/bench.3mf\n"]])

    async def open_connection(*_args, **_kwargs):
        return reader, writer

    monkeypatch.setattr("connector.flashforge_files.asyncio.open_connection", open_connection)
    files, completeness, source = await list_flashforge_files(
        ConnectorPrinterFilesRequest(
            request_id="files-1", ip_address="192.168.1.9", provider="flashforge_ad5m", access_code="secret", serial_number="SN"
        )
    )
    assert [entry.name for entry in files] == ["cube.gcode", "bench.3mf"]
    assert completeness == "complete"
    assert source == "tcp-m661"
    assert writer.writes == [b"~M601 S1\n", b"~M661\n", b"~M602\n"]


@pytest.mark.asyncio
async def test_creator5_never_opens_tcp_and_returns_recent_http(monkeypatch):
    class _Response:
        status_code = 200

        def json(self):
            return {"code": 0, "gcodeList": ["recent.gcode", {"secret": "ignored"}]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return _Response()

    async def fail_tcp(*_args, **_kwargs):
        raise AssertionError("Creator 5 must not open TCP")

    monkeypatch.setattr("connector.flashforge_files.httpx.AsyncClient", lambda **_kwargs: _Client())
    monkeypatch.setattr("connector.flashforge_files.asyncio.open_connection", fail_tcp)
    files, completeness, source = await list_flashforge_files(
        ConnectorPrinterFilesRequest(
            request_id="files-2", ip_address="192.168.1.10", provider="flashforge_creator5", access_code="secret", serial_number="SN"
        )
    )
    assert [entry.name for entry in files] == ["recent.gcode"]
    assert completeness == "recent_only"
    assert source == "http-recent"


@pytest.mark.asyncio
async def test_ad5m_falls_back_to_http_after_tcp_error(monkeypatch):
    async def fail_tcp(*_args, **_kwargs):
        raise TimeoutError("timed out")

    class _Response:
        status_code = 200

        def json(self):
            return {"code": 0, "gcodeList": ["recent.gx"]}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def post(self, *_args, **_kwargs):
            return _Response()

    monkeypatch.setattr("connector.flashforge_files._ad5m_tcp", fail_tcp)
    monkeypatch.setattr("connector.flashforge_files.httpx.AsyncClient", lambda **_kwargs: _Client())
    files, completeness, source = await list_flashforge_files(
        ConnectorPrinterFilesRequest(
            request_id="files-3", ip_address="192.168.1.11", provider="flashforge_ad5m", access_code="secret", serial_number="SN"
        )
    )
    assert [entry.name for entry in files] == ["recent.gx"]
    assert completeness == "recent_only"
    assert source == "http-recent"
