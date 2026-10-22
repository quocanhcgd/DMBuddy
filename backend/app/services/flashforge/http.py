"""Bounded HTTP API client for FlashForge LAN endpoints.

Protocol facts are inferred from Print-Farm-Controller and require firmware
verification. The client intentionally does not follow redirects or expose raw
printer response bodies through exceptions.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from backend.app.services.flashforge.errors import (
    FlashForgeAuthenticationError,
    FlashForgeResponseTooLargeError,
    FlashForgeTransportError,
)
from backend.app.services.printer_providers.flashforge_contract import (
    contract_for,
    normalize_flashforge_host,
    validate_flashforge_options,
)

DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_UPLOAD_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class FlashForgeHttpClient:
    """Synchronous bounded HTTP client; call from a worker thread in async code."""

    def __init__(
        self,
        *,
        host: str,
        provider: str,
        model: str | None,
        serial_number: str,
        check_code: str,
        http_port: int | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        upload_timeout: float = DEFAULT_UPLOAD_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        client: httpx.Client | None = None,
    ) -> None:
        _, canonical_model = contract_for(provider, model)
        options = validate_flashforge_options(
            provider,
            canonical_model,
            {"http_port": http_port} if http_port is not None else None,
        )
        self.host = normalize_flashforge_host(host)
        self.provider = provider
        self.model = canonical_model
        self.serial_number = str(serial_number).strip()
        self._check_code = str(check_code).strip()
        if not self.serial_number or not self._check_code:
            raise ValueError("FlashForge serial number and check code are required")
        if timeout <= 0 or upload_timeout <= 0 or max_response_bytes <= 0:
            raise ValueError("timeouts and max_response_bytes must be positive")
        self.port = options["http_port"]
        self.base_url = f"http://{self.host}:{self.port}"
        self.timeout = timeout
        self.upload_timeout = upload_timeout
        self.max_response_bytes = max_response_bytes
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        )
        self._owns_client = client is None
        self._request_lock = threading.RLock()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> FlashForgeHttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def post_json(self, endpoint: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """POST an authenticated JSON request and require firmware code zero."""

        if not endpoint.startswith("/") or ".." in endpoint.split("/"):
            raise ValueError("FlashForge endpoint must be an absolute API path")
        body = {
            "serialNumber": self.serial_number,
            "checkCode": self._check_code,
        }
        if payload:
            if {key.lower() for key in payload} & {"serialnumber", "checkcode"}:
                raise ValueError("FlashForge API payload cannot override authentication fields")
            body.update(payload)
        return self._request("POST", endpoint, json_body=body)

    def detail(self) -> dict[str, Any]:
        return self.post_json("/detail")

    def gcode_list(self) -> dict[str, Any]:
        return self.post_json("/gcodeList")

    def control(self, command: str, args: dict[str, Any]) -> dict[str, Any]:
        if not command or not isinstance(args, dict):
            raise ValueError("FlashForge control command and args are required")
        return self.post_json("/control", {"payload": {"cmd": command, "args": args}})

    def print_gcode(self, filename: str, **options: Any) -> dict[str, Any]:
        if "fileName" in options:
            raise ValueError("FlashForge print options cannot override the validated filename")
        safe_name = _safe_filename(filename)
        return self.post_json("/printGcode", {"fileName": safe_name, **options})

    def upload_gcode(
        self,
        local_path: str | Path,
        *,
        remote_filename: str | None = None,
        leveling_before_print: bool = False,
        extra_headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """Stream a G-code file to the printer without requesting auto-start."""

        path = Path(local_path)
        if not path.is_file():
            raise ValueError("FlashForge upload source must be a file")
        filename = _safe_filename(remote_filename or path.name)
        headers = {
            "serialNumber": self.serial_number,
            "checkCode": self._check_code,
            "fileSize": str(path.stat().st_size),
            "printNow": "false",
            "levelingBeforePrint": str(bool(leveling_before_print)).lower(),
        }
        if extra_headers:
            forbidden = {key.lower() for key in extra_headers} & {
                "serialnumber", "checkcode", "filesize", "printnow", "levelingbeforeprint"
            }
            if forbidden:
                raise ValueError("FlashForge upload headers cannot override required fields")
            headers.update(extra_headers)
        with self._request_lock:
            try:
                with path.open("rb") as stream:
                    request = self._client.build_request(
                        "POST",
                        f"{self.base_url}/uploadGcode",
                        headers=headers,
                        files={"gcodeFile": (filename, stream, "application/octet-stream")},
                        timeout=self.upload_timeout,
                    )
                    response = self._client.send(request, stream=True, follow_redirects=False)
                    try:
                        return self._decode_response(response)
                    finally:
                        response.close()
            except httpx.TimeoutException as exc:
                raise FlashForgeTransportError("FlashForge HTTP request timed out") from exc
            except httpx.HTTPError as exc:
                raise FlashForgeTransportError("FlashForge HTTP transport failed") from exc

    def _request(self, method: str, endpoint: str, *, json_body: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}{quote(endpoint, safe='/')}"
        with self._request_lock:
            try:
                with self._client.stream(
                    method,
                    url,
                    json=json_body,
                    timeout=self.timeout,
                    follow_redirects=False,
                ) as response:
                    return self._decode_response(response)
            except httpx.TimeoutException as exc:
                raise FlashForgeTransportError("FlashForge HTTP request timed out") from exc
            except httpx.HTTPError as exc:
                raise FlashForgeTransportError("FlashForge HTTP transport failed") from exc

    def _decode_response(self, response: httpx.Response) -> dict[str, Any]:
        if not 200 <= response.status_code < 300:
            raise FlashForgeTransportError(f"FlashForge HTTP endpoint returned status {response.status_code}")
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > self.max_response_bytes:
                raise FlashForgeResponseTooLargeError("FlashForge response exceeded the configured size limit")
        try:
            payload = json.loads(content or b"{}")
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FlashForgeTransportError("FlashForge returned malformed JSON") from exc
        if not isinstance(payload, dict):
            raise FlashForgeTransportError("FlashForge returned an unexpected JSON shape")
        code = payload.get("code")
        if type(code) is not int or code != 0:
            safe_code = str(code)[:32] if code is not None else "missing"
            message = str(payload.get("message") or payload.get("msg") or "").lower()
            if code == -2 or "lan mode error" in message:
                raise FlashForgeAuthenticationError("FlashForge LAN API is disabled or credentials were rejected")
            raise FlashForgeTransportError(f"FlashForge rejected the request (code {safe_code})")
        return payload


def _safe_filename(filename: str) -> str:
    value = str(filename).replace("\\", "/").rsplit("/", 1)[-1].strip()
    if not value or value in {".", ".."} or "\x00" in value:
        raise ValueError("Invalid FlashForge filename")
    if Path(value).suffix.lower() not in {".gcode", ".gx", ".g", ".3mf"}:
        raise ValueError("Unsupported FlashForge print file extension")
    return value
