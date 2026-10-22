"""Provider-specific, short-lived printer verification for the Connector.

Secrets are accepted only for the in-memory verification call. This module
never persists, logs, or includes them in a result. Unsupported providers fail
closed with a capability error instead of falling back to a generic proxy.
"""

from __future__ import annotations

import asyncio
import math
import ssl
import threading
from dataclasses import dataclass

import httpx

from connector.discovery import probe_printer_status, validate_private_endpoint
from connector_protocol import ConnectorPrinterStatusRequest, ConnectorPrinterVerifyRequest


@dataclass(frozen=True, slots=True)
class ProviderVerification:
    reachable: bool
    protocol: str
    service: str
    model: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderStatus:
    connected: bool
    state: str
    telemetry: dict[str, object] | None = None
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


async def _verify_flashforge(request: ConnectorPrinterVerifyRequest) -> ProviderVerification:
    """Verify FlashForge LAN credentials without returning printer payloads."""

    if not request.serial_number or not request.access_code:
        return ProviderVerification(False, "http", "flashforge-http", error="serial number and check code are required")
    try:
        async with httpx.AsyncClient(timeout=request.timeout_ms / 1000, follow_redirects=False) as client:
            response = await client.post(
                f"http://{request.ip_address}:{request.port}/detail",
                json={"serialNumber": request.serial_number, "checkCode": request.access_code},
            )
        if response.status_code in {401, 403}:
            return ProviderVerification(False, "http", "flashforge-http", error="authentication failed")
        if response.status_code < 200 or response.status_code >= 300:
            return ProviderVerification(False, "http", "flashforge-http", error="FlashForge endpoint unavailable")
        try:
            payload = response.json()
        except (ValueError, TypeError):
            return ProviderVerification(False, "http", "flashforge-http", error="FlashForge returned malformed JSON")
        if not isinstance(payload, dict) or payload.get("code") != 0:
            return ProviderVerification(False, "http", "flashforge-http", error="FlashForge credentials rejected")
        return ProviderVerification(True, "http", "flashforge-http")
    except httpx.TimeoutException:
        return ProviderVerification(False, "http", "flashforge-http", error="provider request timed out")
    except (httpx.HTTPError, OSError):
        return ProviderVerification(False, "http", "flashforge-http", error="provider endpoint unreachable")


def _flashforge_status_payload(detail: dict) -> dict[str, object]:
    """Normalize only non-secret fields from a FlashForge detail response."""

    raw_status = detail.get("status")
    raw_state = raw_status.strip().lower().replace(" ", "_")[:32] if isinstance(raw_status, str) else "unknown"
    state = {
        "ready": "IDLE", "standby": "IDLE", "idle": "IDLE", "printing": "RUNNING",
        "running": "RUNNING", "paused": "PAUSE", "pause": "PAUSE", "finish": "FINISH",
        "finished": "FINISH", "complete": "FINISH", "completed": "FINISH",
        "error": "FAILED", "failed": "FAILED", "alarm": "FAILED",
    }.get(raw_state, raw_state or "unknown")
    telemetry: dict[str, object] = {"state": state}
    raw_filename = detail.get("printFileName")
    filename = raw_filename.strip()[:256] if isinstance(raw_filename, str) else ""
    if filename:
        telemetry["filename"] = filename
    progress = detail.get("printProgress")
    if (
        isinstance(progress, (int, float))
        and not isinstance(progress, bool)
        and (isinstance(progress, int) or math.isfinite(progress))
    ):
        telemetry["progress"] = max(0.0, min(100.0, float(progress) * (100 if progress <= 1 else 1)))
    temperatures: dict[str, float] = {}
    fields = {
        "nozzle": "rightTemp", "nozzle_target": "rightTargetTemp",
        "bed": "platTemp", "bed_target": "platTargetTemp", "chamber": "chamberTemp",
        "chamber_target": "chamberTargetTemp",
    }
    for output, source in fields.items():
        value = detail.get(source)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and -300 <= value <= 1000
            and (isinstance(value, int) or math.isfinite(value))
        ):
            temperatures[output] = float(value)
    if isinstance(detail.get("nozzleTemps"), list):
        for index, value in enumerate(detail["nozzleTemps"][:4]):
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and -300 <= value <= 1000
                and (isinstance(value, int) or math.isfinite(value))
            ):
                temperatures[f"nozzle{'' if index == 0 else f'_{index + 1}'}"] = float(value)
    if temperatures:
        telemetry["temperatures"] = temperatures
    firmware = detail.get("firmwareVersion")
    if isinstance(firmware, str) and firmware:
        telemetry["firmware_version"] = firmware[:128]
    return telemetry


async def get_provider_status(request: ConnectorPrinterStatusRequest) -> ProviderStatus:
    """Return provider telemetry for supported providers without exposing secrets."""

    validate_private_endpoint(request.ip_address, request.port)
    if request.provider.lower().strip() not in {"flashforge_ad5m", "flashforge_creator5"}:
        reachable = await probe_printer_status(request)
        return ProviderStatus(reachable, "reachable" if reachable else "unreachable")
    if not request.serial_number or not request.access_code:
        return ProviderStatus(False, "unknown", error="serial number and check code are required")
    try:
        async with httpx.AsyncClient(timeout=request.timeout_ms / 1000, follow_redirects=False) as client:
            response = await client.post(
                f"http://{request.ip_address}:{request.port}/detail",
                json={"serialNumber": request.serial_number, "checkCode": request.access_code},
            )
        if response.status_code < 200 or response.status_code >= 300:
            return ProviderStatus(False, "unreachable", error="FlashForge endpoint unavailable")
        payload = response.json()
        detail = payload.get("detail") if isinstance(payload, dict) else None
        if not isinstance(payload, dict) or payload.get("code") != 0 or not isinstance(detail, dict):
            return ProviderStatus(False, "unknown", error="FlashForge returned invalid status")
        telemetry = _flashforge_status_payload(detail)
        return ProviderStatus(True, str(telemetry.get("state") or "unknown"), telemetry=telemetry)
    except (httpx.TimeoutException, httpx.HTTPError, OSError, ValueError):
        return ProviderStatus(False, "unreachable", error="FlashForge status request failed")


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
    if provider in {"flashforge_ad5m", "flashforge_creator5"}:
        return await _verify_flashforge(request)
    return ProviderVerification(False, "tcp", "unsupported", error="provider verification unavailable")

