"""Tests for provider-specific verification executed by the Connector."""

from unittest.mock import Mock

import httpx
import pytest

from connector.provider_verification import (
    ProviderStatus,
    ProviderVerification,
    _flashforge_status_payload,
    get_provider_status,
    verify_provider,
)
from connector_protocol import (
    ConnectorPrinterStatusRequest,
    ConnectorPrinterStatusResult,
    ConnectorPrinterVerifyRequest,
)


class _FakeAsyncClient:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.headers = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    async def get(self, _url, *, headers):
        self.headers = headers
        return self.response


class _FakePostClient(_FakeAsyncClient):
    def __init__(self, response: httpx.Response):
        super().__init__(response)
        self.json_body = None

    async def post(self, _url, *, json):
        self.json_body = json
        return self.response


def test_flashforge_status_normalization_bounds_strings_and_drops_non_finite_values():
    telemetry = _flashforge_status_payload({
        "status": "R" * 100,
        "printFileName": "g" * 300,
        "printProgress": float("nan"),
        "rightTemp": float("inf"),
        "platTemp": 40,
        "firmwareVersion": "v" * 200,
    })

    assert len(telemetry["state"]) == 32
    assert len(telemetry["filename"]) == 256
    assert "progress" not in telemetry
    assert telemetry["temperatures"] == {"bed": 40.0}
    assert len(telemetry["firmware_version"]) == 128


@pytest.mark.parametrize(
    "telemetry",
    [
        {"filename": "f" * 257},
        {"unsupported": "value"},
        {"progress": float("nan")},
        {"temperatures": {"nozzle": float("inf")}},
        {"temperatures": {"nozzle": 10**1000}},
        {"temperatures": {f"nozzle-{index}": 20 for index in range(17)}},
    ],
)
def test_connector_status_result_rejects_oversized_or_invalid_telemetry(telemetry):
    with pytest.raises(ValueError):
        ConnectorPrinterStatusResult(
            request_id="status-1",
            status="completed",
            connected=True,
            state="IDLE",
            telemetry=telemetry,
        )


@pytest.mark.asyncio
async def test_moonraker_verification_uses_private_http_endpoint_and_token(monkeypatch):
    response = httpx.Response(200, json={"result": {"klippy_version": "v0.12"}})
    client = _FakeAsyncClient(response)
    monkeypatch.setattr("connector.provider_verification.httpx.AsyncClient", lambda **_kwargs: client)

    result = await verify_provider(
        ConnectorPrinterVerifyRequest(
            request_id="verify-1",
            ip_address="192.168.1.20",
            port=7125,
            provider="klipper",
            auth_token="secret-token",
        )
    )

    assert result == ProviderVerification(True, "http", "moonraker", model="v0.12")
    assert client.headers == {"Authorization": "Bearer secret-token"}


@pytest.mark.asyncio
async def test_moonraker_verification_redacts_http_error_body(monkeypatch):
    response = httpx.Response(401, json={"error": "secret printer details"})
    client = _FakeAsyncClient(response)
    monkeypatch.setattr("connector.provider_verification.httpx.AsyncClient", lambda **_kwargs: client)

    result = await verify_provider(
        ConnectorPrinterVerifyRequest(
            request_id="verify-2",
            ip_address="10.0.0.12",
            port=7125,
            provider="fluidd",
        )
    )

    assert result.reachable is False
    assert result.error == "authentication failed"
    assert "secret printer details" not in str(result)


@pytest.mark.asyncio
async def test_bambu_verification_requires_access_code_and_does_not_echo_it(monkeypatch):
    request = ConnectorPrinterVerifyRequest(
        request_id="verify-3",
        ip_address="192.168.1.30",
        port=8883,
        provider="bambu",
    )
    missing = await verify_provider(request)
    assert missing.error == "access code is required"

    probe = Mock(return_value=True)
    monkeypatch.setattr("connector.provider_verification._verify_bambu_sync", probe)
    result = await verify_provider(request.model_copy(update={"access_code": "12345678"}))
    assert result.reachable is True
    assert "12345678" not in str(result)
    probe.assert_called_once()


@pytest.mark.asyncio
async def test_unsupported_provider_fails_closed():
    result = await verify_provider(
        ConnectorPrinterVerifyRequest(
            request_id="verify-4",
            ip_address="192.168.1.40",
            port=1234,
            provider="elegoo_sdcp",
        )
    )
    assert result.reachable is False
    assert result.error == "provider verification unavailable"


@pytest.mark.asyncio
async def test_flashforge_verification_checks_detail_code_without_echoing_secret(monkeypatch):
    response = httpx.Response(200, json={"code": 0, "detail": {"serialNumber": "private"}})
    client = _FakePostClient(response)
    monkeypatch.setattr("connector.provider_verification.httpx.AsyncClient", lambda **_kwargs: client)

    result = await verify_provider(
        ConnectorPrinterVerifyRequest(
            request_id="verify-5",
            ip_address="192.168.1.50",
            port=8898,
            provider="flashforge_ad5m",
            serial_number="FF-42",
            access_code="check-secret",
        )
    )

    assert result.reachable is True
    assert result.service == "flashforge-http"
    assert client.json_body == {"serialNumber": "FF-42", "checkCode": "check-secret"}
    assert "check-secret" not in str(result)


@pytest.mark.asyncio
async def test_flashforge_status_normalizes_safe_detail_and_does_not_echo_secret(monkeypatch):
    response = httpx.Response(
        200,
        json={
            "code": 0,
            "detail": {
                "status": "printing",
                "printFileName": "cube.gcode",
                "printProgress": 0.42,
                "rightTemp": 210,
                "platTemp": 60,
                "firmwareVersion": "2.0",
                "checkCode": "private",
            },
        },
    )
    client = _FakePostClient(response)
    monkeypatch.setattr("connector.provider_verification.httpx.AsyncClient", lambda **_kwargs: client)

    result = await get_provider_status(
        ConnectorPrinterStatusRequest(
            request_id="status-1",
            ip_address="192.168.1.50",
            port=8898,
            provider="flashforge_ad5m",
            serial_number="FF-42",
            access_code="check-secret",
        )
    )

    assert result == ProviderStatus(
        True,
        "RUNNING",
        telemetry={
            "state": "RUNNING",
            "filename": "cube.gcode",
            "progress": 42.0,
            "temperatures": {"nozzle": 210.0, "bed": 60.0},
            "firmware_version": "2.0",
        },
    )
    assert "check-secret" not in str(result)
    assert client.json_body == {"serialNumber": "FF-42", "checkCode": "check-secret"}
