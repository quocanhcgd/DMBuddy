"""Provider-specific, short-lived printer verification for the Connector.

Secrets are accepted only for the in-memory verification call. This module
never persists, logs, or includes them in a result. Unsupported providers fail
closed with a capability error instead of falling back to a generic proxy.
"""

from __future__ import annotations

import asyncio
import ssl
import threading
from dataclasses import dataclass

import httpx

from connector.discovery import validate_private_endpoint
from connector_protocol import ConnectorPrinterVerifyRequest


@dataclass(frozen=True, slots=True)
class ProviderVerification:
    reachable: bool
    protocol: str
    service: str
    model: str | None = None
    error: str | None = None


def _generic_http_error(response: httpx.Response) -> str:
    if response.status_code in {401, 403}:
        return "authentication failed"
    if response.status_code == 404:
        return "provider endpoint not found"
    return f"provider returned HTTP {response.status_code}"


async def _verify_http(
    request: ConnectorPrinterVerifyRequest,
    *,
    path: str,
    service: str,
) -> ProviderVerification:
    url = f"http://{request.ip_address}:{request.port}{path}"
    headers = {"Authorization": f"Bearer {request.auth_token}"} if request.auth_token else {}
    timeout = request.timeout_ms / 1000
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url, headers=headers)
        if response.status_code < 200 or response.status_code >= 300:
            return ProviderVerification(False, "http", service, error=_generic_http_error(response))
        model = None
        try:
            payload = response.json()
            if isinstance(payload, dict):
                result = payload.get("result", payload)
                if isinstance(result, dict):
                    model = str(result.get("klippy_version") or result.get("text") or "") or None
        except (ValueError, TypeError):
            pass
        return ProviderVerification(True, "http", service, model=model)
    except httpx.TimeoutException:
        return ProviderVerification(False, "http", service, error="provider request timed out")
    except (httpx.HTTPError, OSError):
        return ProviderVerification(False, "http", service, error="provider endpoint unreachable")


def _verify_bambu_sync(host: str, port: int, access_code: str, timeout: float, serial_number: str | None) -> bool:
    try:
        import paho.mqtt.client as mqtt
    except ImportError:
        return False

    connected = threading.Event()
    success = False
    client_id = f"printbuddy_verify_{(serial_number or 'printer')[-16:]}"
    client = mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv311,
    )
    client.username_pw_set("bblp", access_code)
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    client.tls_set_context(context)

    def on_connect(_client, _userdata, _flags, reason_code, _properties=None):
        nonlocal success
        success = reason_code == 0
        connected.set()

    client.on_connect = on_connect
    try:
        client.connect(host, port, keepalive=10)
        client.loop_start()
        connected.wait(timeout)
        return success
    except (OSError, ValueError):
        return False
    finally:
        try:
            client.disconnect()
        except Exception:  # pragma: no cover - broker may already have closed
            pass
        try:
            client.loop_stop()
        except Exception:  # pragma: no cover - paho cleanup is best effort
            pass


async def verify_provider(request: ConnectorPrinterVerifyRequest) -> ProviderVerification:
    """Verify one supported provider without returning response bodies or secrets."""

    validate_private_endpoint(request.ip_address, request.port)
    provider = request.provider.lower().strip()
    if provider == "bambu":
        if not request.access_code:
            return ProviderVerification(False, "mqtts", "bambu-mqtt", error="access code is required")
        reachable = await asyncio.to_thread(
            _verify_bambu_sync,
            request.ip_address,
            request.port,
            request.access_code,
            request.timeout_ms / 1000,
            request.serial_number,
        )
        return ProviderVerification(
            reachable,
            "mqtts",
            "bambu-mqtt",
            error=None if reachable else "MQTT authentication or connection failed",
        )
    if provider in {"klipper", "mainsail", "fluidd"}:
        return await _verify_http(request, path="/server/info", service="moonraker")
    if provider == "prusalink":
        return await _verify_http(request, path="/api/version", service="prusalink-api")
    return ProviderVerification(False, "tcp", "unsupported", error="provider verification unavailable")

