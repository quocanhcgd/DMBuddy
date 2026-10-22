"""Versioned wire contract shared by Printbuddy server and Connector.

The package intentionally contains only protocol data models. It does not
import the backend application, so a packaged Connector can use it without
installing the server runtime.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer

PROTOCOL_VERSION = 1
MAX_FRAME_BYTES = 256 * 1024

MessageType = Literal[
    "auth.accepted",
    "heartbeat",
    "heartbeat.ack",
    "error",
    "discovery.request",
    "discovery.result",
    "printer.verify.request",
    "printer.verify.result",
    "printer.status.request",
    "printer.status.result",
    "printer.files.request",
    "printer.files.result",
    "printer.upload.request",
    "printer.upload.result",
    "printer.control.request",
    "printer.control.result",
    "printer.temperature.request",
    "printer.temperature.result",
]


class ConnectorDiscoveryRequest(BaseModel):
    """Bounded LAN discovery request sent from server to a Connector."""

    request_id: str = Field(min_length=1, max_length=64)
    subnet: str = Field(min_length=1, max_length=64)
    ports: list[int] = Field(min_length=1, max_length=16)
    max_hosts: int = Field(default=256, ge=1, le=256)
    timeout_ms: int = Field(default=500, ge=100, le=2000)


class ConnectorDiscoveryResultEntry(BaseModel):
    """A sanitized endpoint discovered on the Connector's private LAN."""

    model_config = ConfigDict(extra="forbid")

    ip_address: str = Field(min_length=1, max_length=64)
    port: int = Field(ge=1, le=65535)
    protocol: str = Field(min_length=1, max_length=32)
    service: str = Field(min_length=1, max_length=64)
    reachable: bool = True
    provider: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    serial_number: str | None = Field(default=None, max_length=128)

    @model_serializer(mode="wrap")
    def _serialize_without_optional_nulls(self, serializer):
        """Keep legacy endpoint JSON compact while preserving FlashForge fields."""

        return {key: value for key, value in serializer(self).items() if value is not None}


class ConnectorDiscoveryResult(BaseModel):
    """Filtered discovery result returned by a Connector."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    results: list[ConnectorDiscoveryResultEntry] = Field(default_factory=list, max_length=256)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterVerifyRequest(BaseModel):
    """Short-lived provider verification request over authenticated WSS."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    provider: str = Field(min_length=1, max_length=32)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    auth_token: str | None = Field(default=None, max_length=512)
    timeout_ms: int = Field(default=1000, ge=100, le=5000)


class ConnectorPrinterVerifyResult(BaseModel):
    """Sanitized endpoint verification result."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    reachable: bool = False
    provider: str = Field(min_length=1, max_length=32)
    protocol: str = Field(min_length=1, max_length=32)
    service: str = Field(min_length=1, max_length=64)
    model: str | None = Field(default=None, max_length=128)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterStatusRequest(BaseModel):
    """Status probe request for a bound printer endpoint."""

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    provider: str = Field(min_length=1, max_length=32)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    timeout_ms: int = Field(default=1000, ge=100, le=5000)


class ConnectorPrinterStatusResult(BaseModel):
    """Network status snapshot; provider telemetry is a later capability."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed", "unavailable"]
    connected: bool = False
    state: str = Field(default="unknown", min_length=1, max_length=32)
    telemetry: dict[str, Any] | None = None
    error: str | None = Field(default=None, max_length=200)

    @field_validator("telemetry")
    @classmethod
    def validate_telemetry(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        allowed = {"state", "filename", "progress", "temperatures", "firmware_version"}
        if len(value) > len(allowed) or not set(value).issubset(allowed):
            raise ValueError("status telemetry contains unsupported fields")
        for key in ("state", "filename", "firmware_version"):
            item = value.get(key)
            maximum = 32 if key == "state" else 256 if key == "filename" else 128
            if item is not None and (not isinstance(item, str) or len(item) > maximum):
                raise ValueError(f"status telemetry {key} is invalid")
        progress = value.get("progress")
        if progress is not None and (
            isinstance(progress, bool)
            or not isinstance(progress, int | float)
            or not 0 <= progress <= 100
            or not math.isfinite(progress)
        ):
            raise ValueError("status telemetry progress is invalid")
        temperatures = value.get("temperatures")
        if temperatures is not None:
            if not isinstance(temperatures, dict) or len(temperatures) > 16:
                raise ValueError("status telemetry temperatures are invalid")
            for key, temperature in temperatures.items():
                if (
                    not isinstance(key, str)
                    or len(key) > 32
                    or isinstance(temperature, bool)
                    or not isinstance(temperature, int | float)
                    or not -300 <= temperature <= 1000
                    or not math.isfinite(temperature)
                ):
                    raise ValueError("status telemetry temperature is invalid")
        return value


class ConnectorPrinterFilesRequest(BaseModel):
    """Read-only file listing request for a printer reachable by Connector."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    provider: str = Field(min_length=1, max_length=32)
    http_port: int = Field(default=8898, ge=1, le=65535)
    tcp_port: int | None = Field(default=None, ge=1, le=65535)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    path: str = Field(default="/", min_length=1, max_length=256)
    timeout_ms: int = Field(default=3000, ge=100, le=10000)


class ConnectorPrinterFileEntry(BaseModel):
    """Sanitized printer file metadata; raw firmware payloads are excluded."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=256)
    path: str = Field(min_length=1, max_length=512)
    type: Literal["file"] = "file"
    size: int | None = Field(default=None, ge=0, le=2**31 - 1)


class ConnectorPrinterFilesResult(BaseModel):
    """Bounded, credential-free file listing result."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    path: str = Field(default="/", min_length=1, max_length=256)
    files: list[ConnectorPrinterFileEntry] = Field(default_factory=list, max_length=256)
    completeness: Literal["complete", "recent_only"] = "recent_only"
    source: str | None = Field(default=None, max_length=32)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterUploadRequest(BaseModel):
    """Chunked FlashForge upload request; credential fields are request-only."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    upload_id: str = Field(min_length=1, max_length=64)
    phase: Literal["begin", "chunk", "finish", "abort"]
    ip_address: str = Field(min_length=1, max_length=253)
    provider: str = Field(min_length=1, max_length=32)
    http_port: int = Field(default=8898, ge=1, le=65535)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    filename: str = Field(min_length=1, max_length=256)
    size: int = Field(default=0, ge=0, le=2**31 - 1)
    tool_count: int = Field(default=1, ge=1, le=4)
    chunk_index: int | None = Field(default=None, ge=0, le=100000)
    total_chunks: int | None = Field(default=None, ge=1, le=100001)
    data_b64: str | None = Field(default=None, max_length=200000)
    timeout_ms: int = Field(default=300000, ge=1000, le=600000)


class ConnectorPrinterUploadResult(BaseModel):
    """Sanitized upload acknowledgement."""

    request_id: str = Field(min_length=1, max_length=64)
    upload_id: str = Field(min_length=1, max_length=64)
    status: Literal["accepted", "completed", "aborted", "failed"]
    received_bytes: int = Field(default=0, ge=0, le=2**31 - 1)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterControlRequest(BaseModel):
    """One FlashForge job command with bounded status reconciliation."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    provider: str = Field(min_length=1, max_length=32)
    http_port: int = Field(default=8898, ge=1, le=65535)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    action: Literal["start", "pause", "resume", "cancel"]
    filename: str | None = Field(default=None, max_length=256)
    bed_leveling: bool = True
    flow_calibration: bool = False
    timelapse: bool = False
    timeout_ms: int = Field(default=8000, ge=1000, le=30000)


class ConnectorPrinterControlResult(BaseModel):
    """Credential-free result after one command and readback."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    action: str = Field(min_length=1, max_length=16)
    state_before: str = Field(default="unknown", min_length=1, max_length=32)
    state_after: str = Field(default="unknown", min_length=1, max_length=32)
    filename: str | None = Field(default=None, max_length=256)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterTemperatureRequest(BaseModel):
    """One FlashForge temperature command with bounded target readback."""

    model_config = ConfigDict(extra="forbid")

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    provider: str = Field(min_length=1, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    http_port: int = Field(default=8898, ge=1, le=65535)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    heater: Literal["nozzle", "bed", "chamber"]
    target: int = Field(ge=0, le=320)
    extruder: int | None = Field(default=None, ge=0, le=3)
    timeout_ms: int = Field(default=8000, ge=1000, le=30000)


class ConnectorPrinterTemperatureResult(BaseModel):
    """Credential-free temperature command result."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    heater: str = Field(min_length=1, max_length=16)
    target: int = Field(default=0, ge=0, le=320)
    observed: float | None = None
    error: str | None = Field(default=None, max_length=200)


class ConnectorMessage(BaseModel):
    """Envelope for all post-handshake Connector messages."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = Field(default=PROTOCOL_VERSION, ge=1, le=255)
    message_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=64)
    connector_id: str = Field(min_length=1, max_length=128)
    sent_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: MessageType
    payload: dict[str, Any] = Field(default_factory=dict)


class ConnectorAuthFrame(BaseModel):
    """Optional first frame for clients that cannot set an Authorization header."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["auth"]
    credential: str = Field(min_length=16, max_length=256)
    protocol_version: int = Field(default=PROTOCOL_VERSION, ge=1, le=255)


class ConnectorHeartbeat(BaseModel):
    """Health information sent by the Connector; never contains secrets."""

    model_config = ConfigDict(extra="forbid")

    version: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=64)
    health: Literal["ok", "degraded"] = "ok"


__all__ = [
    "ConnectorAuthFrame",
    "ConnectorHeartbeat",
    "ConnectorDiscoveryRequest",
    "ConnectorDiscoveryResult",
    "ConnectorDiscoveryResultEntry",
    "ConnectorPrinterStatusRequest",
    "ConnectorPrinterStatusResult",
    "ConnectorPrinterFilesRequest",
    "ConnectorPrinterFileEntry",
    "ConnectorPrinterFilesResult",
    "ConnectorPrinterUploadRequest",
    "ConnectorPrinterUploadResult",
    "ConnectorPrinterControlRequest",
    "ConnectorPrinterControlResult",
    "ConnectorPrinterTemperatureRequest",
    "ConnectorPrinterTemperatureResult",
    "ConnectorPrinterVerifyRequest",
    "ConnectorPrinterVerifyResult",
    "ConnectorMessage",
    "MAX_FRAME_BYTES",
    "MessageType",
    "PROTOCOL_VERSION",
]
