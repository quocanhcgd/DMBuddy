import pytest

import connector.flashforge_control as flashforge_control
from connector.flashforge_control import execute_control
from connector_protocol import ConnectorPrinterControlRequest


class _Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class _Client:
    def __init__(self, details=None):
        self.calls = []
        self.details = iter(details or [
            {"code": 0, "detail": {"status": "RUNNING", "printFileName": "cube.gcode"}},
            {"code": 0, "detail": {"status": "PAUSE", "printFileName": "cube.gcode"}},
        ])

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/detail"):
            return _Response(next(self.details))
        return _Response({"code": 0})


@pytest.mark.asyncio
async def test_control_reads_before_and_after_and_sends_one_command(monkeypatch):
    client = _Client()
    monkeypatch.setattr("connector.flashforge_control.httpx.AsyncClient", lambda **_kwargs: client)
    before, after, filename = await execute_control(
        ConnectorPrinterControlRequest(
            request_id="control-1",
            ip_address="192.168.1.10",
            provider="flashforge_ad5m",
            serial_number="SN",
            access_code="secret-check-code",
            action="pause",
        )
    )
    assert (before, after, filename) == ("RUNNING", "PAUSE", "cube.gcode")
    assert len(client.calls) == 3
    assert client.calls[1][0].endswith("/control")
    assert client.calls[1][1]["json"]["payload"]["args"]["action"] == "pause"


@pytest.mark.asyncio
async def test_control_polls_readback_but_never_repeats_side_effect(monkeypatch):
    client = _Client([
        {"code": 0, "detail": {"status": "RUNNING", "printFileName": "cube.gcode"}},
        {"code": 0, "detail": {"status": "RUNNING", "printFileName": "cube.gcode"}},
        {"code": 0, "detail": {"status": "PAUSE", "printFileName": "cube.gcode"}},
    ])
    monkeypatch.setattr("connector.flashforge_control.httpx.AsyncClient", lambda **_kwargs: client)
    monkeypatch.setattr("connector.flashforge_control.asyncio.sleep", lambda _delay: _no_wait())
    before, after, filename = await execute_control(
        ConnectorPrinterControlRequest(
            request_id="control-2", ip_address="192.168.1.10", provider="flashforge_ad5m",
            serial_number="SN", access_code="secret-check-code", action="pause",
        )
    )
    assert (before, after, filename) == ("RUNNING", "PAUSE", "cube.gcode")
    assert sum(url.endswith("/control") for url, _ in client.calls) == 1
    assert sum(url.endswith("/detail") for url, _ in client.calls) == 3


async def _no_wait():
    return None


@pytest.mark.asyncio
async def test_control_total_deadline_after_command_does_not_retry(monkeypatch):
    import asyncio

    client = _Client()
    monkeypatch.setattr("connector.flashforge_control.httpx.AsyncClient", lambda **_kwargs: client)
    detail = flashforge_control._detail
    calls = 0

    async def delayed_readback(http_client, request):
        nonlocal calls
        calls += 1
        if calls == 2:
            await asyncio.sleep(2)
        return await detail(http_client, request)

    monkeypatch.setattr("connector.flashforge_control._detail", delayed_readback)
    with pytest.raises(RuntimeError, match="operation timed out"):
        await execute_control(
            ConnectorPrinterControlRequest(
                request_id="control-timeout", ip_address="192.168.1.10", provider="flashforge_ad5m",
                serial_number="SN", access_code="secret-check-code", action="pause", timeout_ms=1000,
            )
        )
    assert sum(url.endswith("/control") for url, _ in client.calls) == 1
