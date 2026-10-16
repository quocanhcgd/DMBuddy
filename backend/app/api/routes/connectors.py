"""Connector enrollment, management and outbound WebSocket gateway."""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.auth import RequirePermissionIfAuthEnabled, get_password_hash, verify_password
from backend.app.core.database import async_session, get_db
from backend.app.core.permissions import Permission
from backend.app.models.connector import Connector, ConnectorEnrollment
from backend.app.models.user import User
from backend.app.schemas.connector import (
    ConnectorEnrollmentCreate,
    ConnectorEnrollmentResponse,
    ConnectorEnrollRequest,
    ConnectorEnrollResponse,
    ConnectorResponse,
    ConnectorUpdate,
)
from backend.app.services.connector_gateway import connector_gateway
from connector_protocol import PROTOCOL_VERSION, ConnectorAuthFrame, ConnectorHeartbeat, ConnectorMessage

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/connectors", tags=["connectors"])

_ENROLLMENT_PREFIX_LENGTH = 8
_CREDENTIAL_PREFIX_LENGTH = 12
_MAX_WS_MESSAGE_BYTES = 256 * 1024


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _naive_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=None) if value.tzinfo else value


def _hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _token_prefix(value: str, length: int) -> str:
    return value[:length]


def _connector_or_404(connector: Connector | None) -> Connector:
    if connector is None:
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


def _owned_connector(connector: Connector, current_user: User | None) -> Connector:
    if current_user is not None and not current_user.is_admin and connector.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail="Connector not found")
    if current_user is None and connector.owner_user_id is not None:
        # Auth-disabled callers have no identity and cannot access an owned row.
        raise HTTPException(status_code=404, detail="Connector not found")
    return connector


@router.post("/enrollments", response_model=ConnectorEnrollmentResponse)
async def create_enrollment(
    data: ConnectorEnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.CONNECTORS_CREATE),
):
    code = f"pc_{secrets.token_urlsafe(32)}"
    expires_at = _now() + timedelta(seconds=data.ttl_seconds)
    enrollment = ConnectorEnrollment(
        token_prefix=_token_prefix(code, _ENROLLMENT_PREFIX_LENGTH),
        token_hash=_hash_token(code),
        owner_user_id=current_user.id if current_user else None,
        name_hint=data.name,
        protocol_version=PROTOCOL_VERSION,
        expires_at=_naive_utc(expires_at),
    )
    db.add(enrollment)
    await db.commit()
    await db.refresh(enrollment)
    return ConnectorEnrollmentResponse(enrollment_code=code, expires_at=expires_at)


@router.post("/enroll", response_model=ConnectorEnrollResponse)
async def enroll_connector(data: ConnectorEnrollRequest, db: AsyncSession = Depends(get_db)):
    if data.protocol_version != PROTOCOL_VERSION:
        raise HTTPException(status_code=426, detail="Unsupported Connector protocol version")

    result = await db.execute(
        select(ConnectorEnrollment).where(
            ConnectorEnrollment.token_hash == _hash_token(data.enrollment_code),
            ConnectorEnrollment.used_at.is_(None),
        )
    )
    enrollment = result.scalar_one_or_none()
    if enrollment is None:
        raise HTTPException(status_code=401, detail="Invalid enrollment code")
    if _naive_utc(enrollment.expires_at) <= _naive_utc(_now()):
        raise HTTPException(status_code=410, detail="Enrollment code expired")

    connector_id = secrets.token_urlsafe(24)
    credential = f"pc_{secrets.token_urlsafe(48)}"
    connector = Connector(
        public_id=connector_id,
        owner_user_id=enrollment.owner_user_id,
        name=data.name or enrollment.name_hint or "Printbuddy Connector",
        status="pending",
        version=data.version,
        platform=data.platform,
        public_key_hash=_hash_token(data.public_key) if data.public_key else None,
        credential_prefix=_token_prefix(credential, _CREDENTIAL_PREFIX_LENGTH),
        credential_hash=get_password_hash(credential),
    )
    enrollment.used_at = _naive_utc(_now())
    db.add(connector)
    await db.commit()
    await db.refresh(connector)
    return ConnectorEnrollResponse(
        connector_id=connector.public_id,
        credential=credential,
        name=connector.name,
        server_time=_now(),
    )


@router.get("", response_model=list[ConnectorResponse])
@router.get("/", response_model=list[ConnectorResponse], include_in_schema=False)
async def list_connectors(
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.CONNECTORS_READ),
):
    query = select(Connector).order_by(Connector.created_at.desc())
    if current_user is not None and not current_user.is_admin:
        query = query.where(Connector.owner_user_id == current_user.id)
    elif current_user is None:
        query = query.where(Connector.owner_user_id.is_(None))
    result = await db.execute(query)
    connectors = list(result.scalars().all())
    for connector in connectors:
        connector.status = "online" if connector_gateway.is_online(connector.public_id) else (
            "revoked" if connector.revoked_at else "offline"
        )
    return connectors


@router.get("/{connector_id}", response_model=ConnectorResponse)
async def get_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.CONNECTORS_READ),
):
    result = await db.execute(select(Connector).where(Connector.public_id == connector_id))
    connector = _owned_connector(_connector_or_404(result.scalar_one_or_none()), current_user)
    if connector.revoked_at:
        connector.status = "revoked"
    elif connector_gateway.is_online(connector.public_id):
        connector.status = "online"
    elif connector.status == "online":
        connector.status = "offline"
    return connector


@router.patch("/{connector_id}", response_model=ConnectorResponse)
async def update_connector(
    connector_id: str,
    data: ConnectorUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.CONNECTORS_UPDATE),
):
    result = await db.execute(select(Connector).where(Connector.public_id == connector_id))
    connector = _owned_connector(_connector_or_404(result.scalar_one_or_none()), current_user)
    if connector.revoked_at:
        raise HTTPException(status_code=409, detail="Connector is revoked")
    if data.name is not None:
        connector.name = data.name
    await db.commit()
    await db.refresh(connector)
    return connector


@router.post("/{connector_id}/revoke", response_model=ConnectorResponse)
async def revoke_connector(
    connector_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = RequirePermissionIfAuthEnabled(Permission.CONNECTORS_REVOKE),
):
    result = await db.execute(select(Connector).where(Connector.public_id == connector_id))
    connector = _owned_connector(_connector_or_404(result.scalar_one_or_none()), current_user)
    connector.revoked_at = connector.revoked_at or _naive_utc(_now())
    connector.status = "revoked"
    connector.last_disconnect_reason = "revoked_by_user"
    session = await connector_gateway.get(connector.public_id)
    if session:
        try:
            await session.websocket.close(code=4003, reason="Connector revoked")
        except Exception:  # pragma: no cover - peer may already be gone
            logger.debug("Revoked Connector session already closed: %s", connector.public_id)
    await db.commit()
    await db.refresh(connector)
    return connector


async def _authenticate_connector(credential: str) -> Connector | None:
    async with async_session() as db:
        result = await db.execute(
            select(Connector).where(
                Connector.credential_prefix == _token_prefix(credential, _CREDENTIAL_PREFIX_LENGTH),
                Connector.revoked_at.is_(None),
            )
        )
        for connector in result.scalars().all():
            if verify_password(credential, connector.credential_hash):
                return connector
    return None


async def _set_connector_status(connector_id: str, status_value: str, **fields: object) -> None:
    async with async_session() as db:
        result = await db.execute(select(Connector).where(Connector.public_id == connector_id))
        connector = result.scalar_one_or_none()
        if connector is None:
            return
        if connector.revoked_at is not None and status_value == "online":
            return
        if connector.revoked_at is not None and status_value == "offline":
            status_value = "revoked"
        connector.status = status_value
        for name, value in fields.items():
            setattr(connector, name, value)
        await db.commit()


@router.websocket("/ws")
async def connector_websocket(websocket: WebSocket):
    """Authenticate a Connector and keep its heartbeat session alive."""
    await websocket.accept()
    session = None
    connector: Connector | None = None
    try:
        authorization = websocket.headers.get("authorization", "")
        credential = authorization[7:].strip() if authorization.lower().startswith("bearer ") else None
        if credential is None:
            first = await websocket.receive_text()
            if len(first.encode("utf-8")) > _MAX_WS_MESSAGE_BYTES:
                await websocket.close(code=1009, reason="Frame too large")
                return
            auth_frame = ConnectorAuthFrame.model_validate_json(first)
            if auth_frame.protocol_version != PROTOCOL_VERSION:
                await websocket.close(code=4002, reason="Unsupported protocol version")
                return
            credential = auth_frame.credential
        connector = await _authenticate_connector(credential)
        if connector is None:
            await websocket.close(code=4003, reason="Invalid Connector credential")
            return

        await websocket.send_json(
            {
                "schema_version": PROTOCOL_VERSION,
                "type": "auth.accepted",
                "connector_id": connector.public_id,
            }
        )
        session = await connector_gateway.register(connector.public_id, websocket)
        await _set_connector_status(
            connector.public_id,
            "online",
            last_seen_at=_naive_utc(_now()),
            last_disconnect_reason=None,
        )

        while True:
            raw = await websocket.receive_text()
            if len(raw.encode("utf-8")) > _MAX_WS_MESSAGE_BYTES:
                await websocket.close(code=1009, reason="Frame too large")
                return
            message = ConnectorMessage.model_validate_json(raw)
            if message.connector_id != connector.public_id:
                await websocket.close(code=4003, reason="Connector ID mismatch")
                return
            if message.schema_version != PROTOCOL_VERSION:
                await websocket.close(code=4002, reason="Unsupported protocol version")
                return
            if message.type == "heartbeat":
                heartbeat = ConnectorHeartbeat.model_validate(message.payload)
                await _set_connector_status(
                    connector.public_id,
                    "online",
                    version=heartbeat.version,
                    platform=heartbeat.platform,
                    last_seen_at=_naive_utc(_now()),
                )
                await websocket.send_json(
                    {
                        "schema_version": PROTOCOL_VERSION,
                        "message_id": message.message_id,
                        "connector_id": connector.public_id,
                        "type": "heartbeat.ack",
                        "sent_at": _now().isoformat(),
                    }
                )
            else:
                await websocket.send_json(
                    {
                        "schema_version": PROTOCOL_VERSION,
                        "message_id": message.message_id,
                        "connector_id": connector.public_id,
                        "type": "error",
                        "payload": {"code": "unsupported_message_type"},
                    }
                )
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.info("Connector WebSocket closed with protocol error", exc_info=True)
    finally:
        if session and await connector_gateway.unregister(session):
            await _set_connector_status(
                session.connector_id,
                "offline",
                last_disconnect_reason="connection_closed",
            )
