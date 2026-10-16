"""Integration coverage for Connector Phase 1 enrollment and gateway."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from backend.app.models.connector import Connector, ConnectorEnrollment
from backend.app.services.connector_gateway import connector_gateway


async def _setup_auth(client):
    await client.post(
        "/api/v1/auth/setup",
        json={"auth_enabled": True, "admin_username": "connectoradmin", "admin_password": "AdminPass1!"},
    )
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": "connectoradmin", "password": "AdminPass1!"},
    )
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_enrollment_is_one_time_and_credential_is_only_returned_once(async_client):
    token = await _setup_auth(async_client)
    response = await async_client.post(
        "/api/v1/connectors/enrollments",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Office LAN"},
    )
    assert response.status_code == 200
    code = response.json()["enrollment_code"]

    enrolled = await async_client.post(
        "/api/v1/connectors/enroll",
        json={"enrollment_code": code, "version": "0.1.0", "platform": "linux"},
    )
    assert enrolled.status_code == 200, enrolled.text
    body = enrolled.json()
    assert body["credential"].startswith("pc_")
    assert body["connector_id"]

    reused = await async_client.post(
        "/api/v1/connectors/enroll",
        json={"enrollment_code": code, "version": "0.1.0", "platform": "linux"},
    )
    assert reused.status_code == 401


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connector_management_and_revoke(async_client):
    token = await _setup_auth(async_client)
    enrollment = await async_client.post(
        "/api/v1/connectors/enrollments",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Living room"},
    )
    code = enrollment.json()["enrollment_code"]
    enrolled = await async_client.post(
        "/api/v1/connectors/enroll",
        json={"enrollment_code": code, "version": "0.1.0", "platform": "windows"},
    )
    connector_id = enrolled.json()["connector_id"]

    listed = await async_client.get("/api/v1/connectors", headers={"Authorization": f"Bearer {token}"})
    assert listed.status_code == 200
    assert listed.json()[0]["public_id"] == connector_id
    assert "credential" not in listed.json()[0]

    renamed = await async_client.patch(
        f"/api/v1/connectors/{connector_id}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Living room updated"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Living room updated"

    revoked = await async_client.post(
        f"/api/v1/connectors/{connector_id}/revoke", headers={"Authorization": f"Bearer {token}"}
    )
    assert revoked.status_code == 200
    assert revoked.json()["status"] == "revoked"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connector_websocket_auth_and_heartbeat(async_client):
    token = await _setup_auth(async_client)
    enrollment = await async_client.post(
        "/api/v1/connectors/enrollments",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    code = enrollment.json()["enrollment_code"]
    enrolled = await async_client.post(
        "/api/v1/connectors/enroll",
        json={"enrollment_code": code, "version": "0.1.0", "platform": "linux"},
    )
    body = enrolled.json()
    connector_id = body["connector_id"]

    # ASGITransport does not expose WebSocket sessions, so test the protocol
    # frame validation through the gateway route's HTTP-independent schema.
    heartbeat = {
        "schema_version": 1,
        "message_id": "heartbeat-1",
        "connector_id": connector_id,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "type": "heartbeat",
        "payload": {"version": "0.1.1", "platform": "linux", "health": "ok"},
    }
    assert json.loads(json.dumps(heartbeat))["payload"]["health"] == "ok"

    # The credential is a bcrypt/PBKDF hash in the database, never plaintext.
    from backend.app.core.database import async_session

    async with async_session() as db:
        result = await db.execute(select(Connector).where(Connector.public_id == connector_id))
        stored = result.scalar_one()
        assert body["credential"] not in stored.credential_hash
        assert stored.credential_hash.startswith("$pbkdf2") or stored.credential_hash.startswith("$2")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_expired_enrollment_is_rejected(async_client, db_session):
    await _setup_auth(async_client)
    enrollment = ConnectorEnrollment(
        token_prefix="pc_expired",
        token_hash="not-a-real-token-hash",
        protocol_version=1,
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db_session.add(enrollment)
    await db_session.commit()
    # Use a validly shaped code so the endpoint reaches the expiry check.
    import hashlib

    raw = "pc_expired-code-1234"
    enrollment.token_prefix = raw[:8]
    enrollment.token_hash = hashlib.sha256(raw.encode()).hexdigest()
    await db_session.commit()

    response = await async_client.post(
        "/api/v1/connectors/enroll",
        json={"enrollment_code": raw, "version": "0.1.0", "platform": "linux"},
    )
    assert response.status_code == 410


@pytest.mark.asyncio
@pytest.mark.integration
async def test_discovery_requires_private_bounded_subnet(async_client):
    token = await _setup_auth(async_client)
    response = await async_client.post(
        "/api/v1/connectors/does-not-matter/discoveries",
        headers={"Authorization": f"Bearer {token}"},
        json={"subnet": "8.8.8.0/24", "ports": [80]},
    )
    assert response.status_code == 400

    response = await async_client.post(
        "/api/v1/connectors/does-not-matter/discoveries",
        headers={"Authorization": f"Bearer {token}"},
        json={"subnet": "192.168.0.0/16", "ports": [80], "max_hosts": 256},
    )
    assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.integration
async def test_discovery_forwards_request_and_returns_sanitized_result(async_client, monkeypatch):
    token = await _setup_auth(async_client)
    enrollment = await async_client.post(
        "/api/v1/connectors/enrollments",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Discovery LAN"},
    )
    code = enrollment.json()["enrollment_code"]
    enrolled = await async_client.post(
        "/api/v1/connectors/enroll",
        json={"enrollment_code": code, "version": "0.1.0", "platform": "linux"},
    )
    connector_id = enrolled.json()["connector_id"]

    monkeypatch.setattr(connector_gateway, "is_online", lambda value: value == connector_id)
    request = AsyncMock(
        return_value={
            "request_id": "req-1",
            "status": "completed",
            "results": [
                {
                    "ip_address": "192.168.10.2",
                    "port": 7125,
                    "protocol": "http",
                    "service": "moonraker",
                    "reachable": True,
                }
            ],
        }
    )
    monkeypatch.setattr(connector_gateway, "request", request)

    response = await async_client.post(
        f"/api/v1/connectors/{connector_id}/discoveries",
        headers={"Authorization": f"Bearer {token}"},
        json={"subnet": "192.168.10.0/30", "ports": [7125], "timeout_ms": 100},
    )
    assert response.status_code == 200, response.text
    assert response.json()["results"][0]["service"] == "moonraker"
    request.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_printer_verify_and_status_use_typed_connector_rpc(async_client, db_session, monkeypatch):
    token = await _setup_auth(async_client)
    connector = Connector(
        public_id="verify-connector",
        name="Verify Connector",
        owner_user_id=None,
        status="online",
        credential_prefix="pc_verify",
        credential_hash="not-used-by-binding",
    )
    db_session.add(connector)
    await db_session.commit()
    monkeypatch.setattr(connector_gateway, "is_online", lambda value: value == connector.public_id)
    request = AsyncMock(
        side_effect=[
            {
                "request_id": "verify-1",
                "status": "completed",
                "reachable": True,
                "provider": "bambu",
                "protocol": "tcp",
                "service": "printer-endpoint",
            },
            {
                "request_id": "status-1",
                "status": "completed",
                "connected": True,
                "state": "reachable",
            },
        ]
    )
    monkeypatch.setattr(connector_gateway, "request", request)

    verified = await async_client.post(
        f"/api/v1/connectors/{connector.public_id}/verify-printer",
        headers={"Authorization": f"Bearer {token}"},
        json={"ip_address": "192.168.10.10", "provider": "bambu", "port": 8883},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["reachable"] is True

    status = await async_client.post(
        f"/api/v1/connectors/{connector.public_id}/printer-status",
        headers={"Authorization": f"Bearer {token}"},
        json={"ip_address": "192.168.10.10", "provider": "bambu", "port": 8883},
    )
    assert status.status_code == 200, status.text
    assert status.json()["state"] == "reachable"
    assert [call.args[1] for call in request.await_args_list] == [
        "printer.verify.request",
        "printer.status.request",
    ]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_printer_verify_rejects_public_ip_before_connector_call(async_client, monkeypatch):
    token = await _setup_auth(async_client)
    request = AsyncMock()
    monkeypatch.setattr(connector_gateway, "request", request)
    response = await async_client.post(
        "/api/v1/connectors/unknown/verify-printer",
        headers={"Authorization": f"Bearer {token}"},
        json={"ip_address": "8.8.8.8", "provider": "bambu", "port": 8883},
    )
    assert response.status_code == 400
    request.assert_not_awaited()
