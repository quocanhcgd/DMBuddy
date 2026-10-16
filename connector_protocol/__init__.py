"""Versioned wire contract shared by Printbuddy server and Connector.

The package intentionally contains only protocol data models. It does not
import the backend application, so a packaged Connector can use it without
installing the server runtime.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

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


class ConnectorDiscoveryResult(BaseModel):
    """Filtered discovery result returned by a Connector."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    results: list[ConnectorDiscoveryResultEntry] = Field(default_factory=list, max_length=256)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterVerifyRequest(BaseModel):
    """Network-level printer verification request; never carries credentials."""

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    provider: str = Field(min_length=1, max_length=32)
    serial_number: str | None = Field(default=None, max_length=64)
    timeout_ms: int = Field(default=1000, ge=100, le=5000)


class ConnectorPrinterVerifyResult(BaseModel):
    """Sanitized endpoint verification result."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed"]
    reachable: bool = False
    provider: str = Field(min_length=1, max_length=32)
    protocol: str = Field(min_length=1, max_length=32)
    service: str = Field(min_length=1, max_length=64)
    error: str | None = Field(default=None, max_length=200)


class ConnectorPrinterStatusRequest(BaseModel):
    """Status probe request for a bound printer endpoint."""

    request_id: str = Field(min_length=1, max_length=64)
    ip_address: str = Field(min_length=1, max_length=253)
    port: int = Field(ge=1, le=65535)
    provider: str = Field(min_length=1, max_length=32)
    timeout_ms: int = Field(default=1000, ge=100, le=5000)


class ConnectorPrinterStatusResult(BaseModel):
    """Network status snapshot; provider telemetry is a later capability."""

    request_id: str = Field(min_length=1, max_length=64)
    status: Literal["completed", "failed", "unavailable"]
    connected: bool = False
    state: Literal["reachable", "unreachable", "unknown"] = "unknown"
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
    "ConnectorPrinterVerifyRequest",
    "ConnectorPrinterVerifyResult",
    "ConnectorMessage",
    "MAX_FRAME_BYTES",
    "MessageType",
    "PROTOCOL_VERSION",
]
