"""FlashForge job control over the Connector with one-command semantics."""

from __future__ import annotations

import asyncio

import httpx

from connector.discovery import validate_private_endpoint
from connector.provider_verification import _flashforge_status_payload
from connector_protocol import ConnectorPrinterControlRequest

READBACK_ATTEMPTS = 5
READBACK_INTERVAL_SECONDS = 0.35


def _detail_state(payload: dict) -> tuple[str, str | None]:
    detail = payload.get("detail") if isinstance(payload, dict) else None
    if not isinstance(detail, dict):
        return "unknown", None
    telemetry = _flashforge_status_payload(detail)
    return str(telemetry.get("state") or "unknown"), str(telemetry.get("filename") or "") or None


async def _detail(client: httpx.AsyncClient, request: ConnectorPrinterControlRequest) -> tuple[str, str | None]:
    response = await client.post(
        f"http://{request.ip_address}:{request.http_port}/detail",
        json={"serialNumber": request.serial_number, "checkCode": request.access_code},
    )
    if response.status_code < 200 or response.status_code >= 300:
        raise RuntimeError("FlashForge status endpoint unavailable")
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise RuntimeError("FlashForge credentials rejected")
    return _detail_state(payload)


async def _execute_control(request: ConnectorPrinterControlRequest) -> tuple[str, str, str | None]:
    """Read state, issue exactly one command, then poll status without retrying it."""
    validate_private_endpoint(request.ip_address, request.http_port)
    if not request.serial_number or not request.access_code:
        raise ValueError("serial number and check code are required")
    if request.provider.lower().strip() not in {"flashforge_ad5m", "flashforge_creator5"}:
        raise ValueError("Connector control is unavailable for this provider")
    async with httpx.AsyncClient(timeout=request.timeout_ms / 1000, follow_redirects=False, trust_env=False) as client:
        state_before, current_filename = await _detail(client, request)
        allowed = {
            "start": {"IDLE", "FINISH", "FAILED"},
            "pause": {"RUNNING"},
            "resume": {"PAUSE"},
            "cancel": {"RUNNING", "PAUSE"},
        }[request.action]
        if state_before not in allowed:
            raise ValueError(f"FlashForge printer is not ready for {request.action}")
        if request.action == "start":
            if not request.filename:
                raise ValueError("filename is required for start")
            command = "/printGcode"
            payload = {
                "serialNumber": request.serial_number,
                "checkCode": request.access_code,
                "fileName": request.filename,
                "levelingBeforePrint": request.bed_leveling,
                "flowCalibration": request.flow_calibration,
                "timeLapseVideo": request.timelapse,
            }
        else:
            command = "/control"
            payload = {
                "serialNumber": request.serial_number,
                "checkCode": request.access_code,
                "payload": {"cmd": "jobCtl_cmd", "args": {"jobID": "", "action": "continue" if request.action == "resume" else request.action}},
            }
        response = await client.post(f"http://{request.ip_address}:{request.http_port}{command}", json=payload)
        if response.status_code < 200 or response.status_code >= 300:
            raise RuntimeError("FlashForge control endpoint unavailable")
        result = response.json()
        if not isinstance(result, dict) or result.get("code") != 0:
            raise RuntimeError("FlashForge rejected the control command")
        expected = {
            "start": "RUNNING",
            "pause": "PAUSE",
            "resume": "RUNNING",
            "cancel": {"IDLE", "FINISH", "FAILED"},
        }[request.action]
        for attempt in range(READBACK_ATTEMPTS):
            if attempt:
                await asyncio.sleep(READBACK_INTERVAL_SECONDS)
            state_after, observed_filename = await _detail(client, request)
            reached_state = state_after in expected if isinstance(expected, set) else state_after == expected
            reached_filename = (
                request.action != "start"
                or (observed_filename or "").casefold() == request.filename.casefold()
            )
            if reached_state and reached_filename:
                return state_before, state_after, observed_filename or current_filename
        raise RuntimeError("FlashForge control readback did not reach the requested state")


async def execute_control(request: ConnectorPrinterControlRequest) -> tuple[str, str, str | None]:
    """Apply one total operation deadline across command and readback."""
    try:
        async with asyncio.timeout(request.timeout_ms / 1000):
            return await _execute_control(request)
    except TimeoutError as exc:
        raise RuntimeError("FlashForge control operation timed out; command was not retried") from exc
