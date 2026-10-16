"""HTTP and response schemas for Connector management."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from connector_protocol import PROTOCOL_VERSION


class ConnectorEnrollmentCreate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    ttl_seconds: int = Field(default=600, ge=60, le=900)


class ConnectorEnrollmentResponse(BaseModel):
    enrollment_code: str
    expires_at: datetime
    protocol_version: int = PROTOCOL_VERSION


class ConnectorEnrollRequest(BaseModel):
    enrollment_code: str = Field(min_length=16, max_length=256)
    name: str | None = Field(default=None, min_length=1, max_length=100)
    version: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=64)
    public_key: str | None = Field(default=None, max_length=4096)
    protocol_version: int = Field(default=PROTOCOL_VERSION, ge=1, le=255)


class ConnectorEnrollResponse(BaseModel):
    connector_id: str
    credential: str
    name: str
    protocol_version: int = PROTOCOL_VERSION
    server_time: datetime


class ConnectorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)


class ConnectorResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    public_id: str
    name: str
    status: str
    version: str | None
    platform: str | None
    last_seen_at: datetime | None
    last_disconnect_reason: str | None
    credential_version: int
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ConnectorCommandResponse(BaseModel):
    command_id: str
    status: str
    detail: str | None = None


class ConnectorDiscoveryCreate(BaseModel):
    subnet: str = Field(min_length=1, max_length=64)
    ports: list[int] = Field(default_factory=lambda: [80, 7125, 8883, 990], min_length=1, max_length=16)
    max_hosts: int = Field(default=256, ge=1, le=256)
    timeout_ms: int = Field(default=500, ge=100, le=2000)


class ConnectorDiscoveryResponse(BaseModel):
    request_id: str
    status: str
    results: list[dict]
    error: str | None = None


class ConnectorPrinterVerifyCreate(BaseModel):
    ip_address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=8883, ge=1, le=65535)
    provider: str = Field(default="bambu", min_length=1, max_length=32)
    serial_number: str | None = Field(default=None, max_length=64)
    access_code: str | None = Field(default=None, max_length=256)
    auth_token: str | None = Field(default=None, max_length=512)
    timeout_ms: int = Field(default=1000, ge=100, le=5000)


class ConnectorPrinterVerifyResponse(BaseModel):
    request_id: str
    status: str
    reachable: bool
    provider: str
    protocol: str
    service: str
    model: str | None = None
    error: str | None = None


class ConnectorPrinterStatusCreate(BaseModel):
    ip_address: str = Field(min_length=1, max_length=253)
    port: int = Field(default=8883, ge=1, le=65535)
    provider: str = Field(default="bambu", min_length=1, max_length=32)
    timeout_ms: int = Field(default=1000, ge=100, le=5000)


class ConnectorPrinterStatusResponse(BaseModel):
    request_id: str
    status: str
    connected: bool
    state: str
    error: str | None = None
