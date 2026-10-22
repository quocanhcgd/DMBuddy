"""FlashForge temperature control through the Connector.

The command is deliberately sent once.  All retries after that point are
read-only ``/detail`` polls so a network timeout cannot duplicate heating.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from connector.discovery import validate_private_endpoint
from connector_protocol import ConnectorPrinterTemperatureRequest

_PROVIDERS = {"flashforge_ad5m", "flashforge_creator5"}
_READY_STATES = {"IDLE", "RUNNING", "PAUSE", "FINISH"}


def _state_and_temperature(detail: dict[str, Any], request: ConnectorPrinterTemperatureRequest) -> tuple[str, float | None]:
    raw_state = str(detail.get("status") or "unknown").strip().lower().replace(" ", "_")
    state = {
        "ready": "IDLE", "standby": "IDLE", "idle": "IDLE", "printing": "RUNNING",
        "running": "RUNNING", "paused": "PAUSE", "pause": "PAUSE", "finish": "FINISH",
        "finished": "FINISH", "complete": "FINISH", "completed": "FINISH",
        "error": "FAILED", "failed": "FAILED", "alarm": "FAILED",
    }.get(raw_state, raw_state or "unknown")
    if request.heater == "bed":
        value = detail.get("platTargetTemp")
    elif request.heater == "chamber":
        value = detail.get("chamberTargetTemp")
    elif request.provider.lower().strip() == "flashforge_creator5":
        values = detail.get("nozzleTargetTemps")
        if not isinstance(values, list):
            values = [detail.get("rightTargetTemp")]
        index = request.extruder or 0
        value = values[index] if index < len(values) else None
    else:
        value = detail.get("rightTargetTemp")
    return state, float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


async def _detail(client: httpx.AsyncClient, request: ConnectorPrinterTemperatureRequest) -> tuple[str, float | None]:
    response = await client.post(
        f"http://{request.ip_address}:{request.http_port}/detail",
        json={"serialNumber": request.serial_number, "checkCode": request.access_code},
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError("FlashForge status endpoint unavailable")
    payload = response.json()
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict) or payload.get("code") != 0:
        raise RuntimeError("FlashForge credentials rejected")
    return _state_and_temperature(detail, request)


def _command(request: ConnectorPrinterTemperatureRequest) -> dict[str, Any]:
    provider = request.provider.lower().strip()
    if request.heater == "bed":
        return {"platform": request.target}
    if request.heater == "chamber":
        return {"chamber": request.target}
    if provider == "flashforge_ad5m":
        return {"rightNozzle": request.target}
    values = [-200] * 4
    values[request.extruder or 0] = request.target
    return {"nozzles": values}


async def _execute_temperature(request: ConnectorPrinterTemperatureRequest) -> float | None:
    """Set one target and return the sanitized target readback."""
    validate_private_endpoint(request.ip_address, request.http_port)
    provider = request.provider.lower().strip()
    if provider not in _PROVIDERS:
        raise ValueError("Connector temperature control is unavailable for this provider")
    if not request.serial_number or not request.access_code:
        raise ValueError("serial number and check code are required")
    if provider == "flashforge_ad5m" and request.heater == "chamber":
        raise ValueError("Chamber temperature control is only supported by Creator 5 Pro")
    if provider == "flashforge_creator5" and request.heater == "chamber" and str(request.model or "").strip().lower() != "creator 5 pro":
        raise ValueError("Chamber temperature control is only supported by Creator 5 Pro")
    limits = {"nozzle": 265 if provider == "flashforge_ad5m" else 320, "bed": 110 if provider == "flashforge_ad5m" else 120, "chamber": 65}
    if request.target > limits[request.heater]:
        raise ValueError(f"{request.heater} temperature must be 0-{limits[request.heater]} C")
    if provider == "flashforge_creator5" and request.heater == "nozzle" and request.extruder is None:
        raise ValueError("Creator 5 nozzle index is required")
    if provider == "flashforge_ad5m" and request.extruder is not None:
        raise ValueError("AD5M does not expose multiple nozzle indexes")

    async with httpx.AsyncClient(timeout=request.timeout_ms / 1000, follow_redirects=False, trust_env=False) as client:
        state, _ = await _detail(client, request)
        if state not in _READY_STATES:
            raise ValueError("FlashForge printer is not ready for temperature control")
        response = await client.post(
            f"http://{request.ip_address}:{request.http_port}/control",
            json={
                "serialNumber": request.serial_number,
                "checkCode": request.access_code,
                "payload": {"cmd": "temperatureCtl_cmd", "args": _command(request)},
            },
        )
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError("FlashForge temperature endpoint unavailable")
        result = response.json()
        if not isinstance(result, dict) or result.get("code") != 0:
            raise RuntimeError("FlashForge rejected the temperature command")

        deadline = time.monotonic() + max(1.0, request.timeout_ms / 1000)
        observed: float | None = None
        while True:
            _, observed = await _detail(client, request)
            if observed is not None and abs(observed - request.target) <= 1:
                return observed
            if time.monotonic() >= deadline:
                raise RuntimeError("FlashForge temperature readback timed out")
            await asyncio.sleep(0.25)


async def execute_temperature(request: ConnectorPrinterTemperatureRequest) -> float | None:
    """Apply one total operation deadline across command and readback."""
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            return await _execute_temperature(request)
    except TimeoutError as exc:
        raise RuntimeError("FlashForge temperature operation timed out; command was not retried") from exc
