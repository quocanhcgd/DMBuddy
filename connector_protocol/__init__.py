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
]


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
    "ConnectorMessage",
    "MAX_FRAME_BYTES",
    "MessageType",
    "PROTOCOL_VERSION",
]
