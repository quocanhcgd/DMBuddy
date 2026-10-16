"""Tests for provider-specific verification executed by the Connector."""

from unittest.mock import Mock

import httpx
import pytest

from connector.provider_verification import ProviderVerification, verify_provider
from connector_protocol import ConnectorPrinterVerifyRequest


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
