"""Fake HTTP coverage for one-command FlashForge temperature control."""

import httpx
import pytest

import connector.flashforge_temperature as flashforge_temperature
from connector.flashforge_temperature import execute_temperature
from connector_protocol import ConnectorPrinterTemperatureRequest


class _Client:
    def __init__(self, details, controls):
        self.details = iter(details)
        self.controls = controls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None

    async def post(self, url, json):
        if url.endswith("/detail"):
            return httpx.Response(200, json={"code": 0, "detail": next(self.details)})
        self.controls.append(json)
        return httpx.Response(200, json={"code": 0})


def _request(**kwargs):
    values = {
        "request_id": "temp-1", "ip_address": "192.168.1.10", "provider": "flashforge_ad5m",
        "serial_number": "SN", "access_code": "secret", "heater": "nozzle", "target": 210,
        "timeout_ms": 1000,
    }
    values.update(kwargs)
    return ConnectorPrinterTemperatureRequest(**values)


@pytest.mark.asyncio
async def test_ad5m_nozzle_sends_right_nozzle_once(monkeypatch):
    controls = []
    client = _Client(
        [{"status": "idle", "rightTargetTemp": 0}, {"status": "idle", "rightTargetTemp": 210}], controls
    )
    monkeypatch.setattr("connector.flashforge_temperature.httpx.AsyncClient", lambda **_: client)
    observed = await execute_temperature(_request())
    assert observed == 210
    assert controls[0]["payload"]["args"] == {"rightNozzle": 210}
    assert len(controls) == 1


@pytest.mark.asyncio
async def test_creator5_uses_four_tool_sentinel(monkeypatch):
    controls = []
    client = _Client(
        [{"status": "idle", "nozzleTargetTemps": [0, 0, 0, 0]}, {"status": "idle", "nozzleTargetTemps": [0, 0, 215, 0]}], controls
    )
    monkeypatch.setattr("connector.flashforge_temperature.httpx.AsyncClient", lambda **_: client)
    request = _request(provider="flashforge_creator5", model="Creator 5", extruder=2, target=215)
    assert await execute_temperature(request) == 215
    assert controls[0]["payload"]["args"] == {"nozzles": [-200, -200, 215, -200]}


@pytest.mark.asyncio
async def test_creator5_non_pro_rejects_chamber_without_command(monkeypatch):
    controls = []
    client = _Client([], controls)
    monkeypatch.setattr("connector.flashforge_temperature.httpx.AsyncClient", lambda **_: client)
    request = _request(provider="flashforge_creator5", model="Creator 5", heater="chamber", target=45)
    with pytest.raises(ValueError, match="Creator 5 Pro"):
        await execute_temperature(request)
    assert controls == []


@pytest.mark.asyncio
async def test_readback_timeout_does_not_send_second_command(monkeypatch):
    controls = []
    client = _Client(
        [{"status": "idle", "rightTargetTemp": 0}] * 20, controls
    )
    monkeypatch.setattr("connector.flashforge_temperature.httpx.AsyncClient", lambda **_: client)
    request = _request(timeout_ms=1000)
    with pytest.raises(RuntimeError, match="operation timed out"):
        await execute_temperature(request)
    assert len(controls) == 1


@pytest.mark.asyncio
async def test_total_deadline_after_temperature_command_does_not_retry(monkeypatch):
    import asyncio

    controls = []
    client = _Client(
        [{"status": "idle", "rightTargetTemp": 0}, {"status": "idle", "rightTargetTemp": 0}], controls
    )
    monkeypatch.setattr("connector.flashforge_temperature.httpx.AsyncClient", lambda **_: client)
    detail = flashforge_temperature._detail
    calls = 0

    async def delayed_readback(http_client, request):
        nonlocal calls
        calls += 1
        if calls == 2:
            await asyncio.sleep(2)
        return await detail(http_client, request)

    monkeypatch.setattr("connector.flashforge_temperature._detail", delayed_readback)
    with pytest.raises(RuntimeError, match="operation timed out"):
        await execute_temperature(_request(timeout_ms=1000))
    assert len(controls) == 1
