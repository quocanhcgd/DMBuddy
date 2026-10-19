from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import httpx
import pytest

from backend.app.services.printer_manager import PrinterManager, _provider_connection_error
from backend.app.services.printer_providers.factory import create_printer_client
from backend.app.services.printer_providers.moonraker import _moonraker_url_candidates


def test_moonraker_client_normalizes_host_port_without_scheme():
    printer = SimpleNamespace(
        provider="fluidd", api_url="neptune.local:7125", auth_token=None, ip_address="neptune.local"
    )

    client = create_printer_client(printer)

    assert client.base_url == "http://neptune.local:7125/"


def test_moonraker_custom_port_and_reverse_proxy_path_are_preserved_for_fallback():
    assert _moonraker_url_candidates("https://192.168.1.10:8443/moonraker") == [
        "https://192.168.1.10:8443/moonraker/",
        "https://192.168.1.10:7125/moonraker/",
    ]


@pytest.mark.asyncio
async def test_moonraker_connection_failure_returns_actionable_diagnostic():
    with patch("backend.app.services.printer_manager.create_printer_client") as create_client:
        client = MagicMock()
        client.connect.side_effect = httpx.ConnectError("unreachable")
        client.disconnect = MagicMock()
        create_client.return_value = client

        result = await PrinterManager().test_connection(
            "192.168.1.100",
            "KLIPPER-PRINTER",
            "moonraker",
            provider="klipper",
            api_url="http://192.168.1.100:7125",
        )

    assert result["success"] is False
    assert "Could not open a network connection to Moonraker" in result["error"]
    assert result["error_type"] == "ConnectError"


def test_moonraker_connection_error_does_not_expose_response_body():
    request = httpx.Request("GET", "http://printer.local:7125/server/info")
    response = httpx.Response(401, request=request, text="sensitive server response")
    error = httpx.HTTPStatusError("unauthorized", request=request, response=response)

    diagnostic = _provider_connection_error("klipper", error)

    assert "HTTP 401" in diagnostic
    assert "sensitive server response" not in diagnostic
