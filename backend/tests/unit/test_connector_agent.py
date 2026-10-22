"""Unit coverage for Connector message handling."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from connector.flashforge_upload import (
    MAX_ACTIVE_UPLOAD_SESSIONS,
    MAX_UPLOAD_STAGING_BYTES,
    UPLOAD_SESSION_TTL_SECONDS,
    UploadSession,
)
from connector.printbuddy_connector import ConnectorAgent
from connector_protocol import ConnectorMessage, ConnectorPrinterUploadRequest


class _WebSocket:
    def __init__(self, incoming: str) -> None:
        self.incoming = incoming
        self.sent: list[str] = []

    async def recv(self) -> str:
        if self.incoming is not None:
            value = self.incoming
            self.incoming = None
            return value
        raise RuntimeError("stop test receive loop")

    async def send(self, value: str) -> None:
        self.sent.append(value)


@pytest.mark.asyncio
async def test_agent_answers_discovery_request_without_logging_or_forwarding_secrets(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="discovery.request",
        payload={
            "request_id": "req-1",
            "subnet": "192.168.1.0/30",
            "ports": [7125],
            "max_hosts": 4,
            "timeout_ms": 100,
        },
    )
    monkeypatch.setattr(
        "connector.printbuddy_connector.discover_lan",
        lambda value: _fake_discovery(value),
    )
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "discovery.result"
    assert response.payload["request_id"] == "req-1"
    assert response.payload["results"][0]["ip_address"] == "192.168.1.2"
    assert "credential" not in json.dumps(response.payload)


@pytest.mark.asyncio
async def test_agent_answers_verify_request_without_credentials(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="printer.verify.request",
        payload={
            "request_id": "verify-1",
            "ip_address": "192.168.1.10",
            "port": 8883,
            "provider": "bambu",
            "serial_number": "SERIAL-1",
            "timeout_ms": 100,
        },
    )
    probe = AsyncMock(
        return_value=type(
            "Verification",
            (),
            {
                "reachable": True,
                "protocol": "mqtts",
                "service": "bambu-mqtt",
                "model": None,
                "error": None,
            },
        )()
    )
    monkeypatch.setattr("connector.printbuddy_connector.verify_provider", probe)
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.verify.result"
    assert response.payload["reachable"] is True
    assert "access_code" not in json.dumps(response.payload)
    probe.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_answers_flashforge_status_without_returning_credentials(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="printer.status.request",
        payload={
            "request_id": "status-ff-1",
            "ip_address": "192.168.1.10",
            "port": 8898,
            "provider": "flashforge_ad5m",
            "serial_number": "FF-42",
            "access_code": "secret-check-code",
            "timeout_ms": 100,
        },
    )
    status = AsyncMock(
        return_value=type(
            "Status",
            (),
            {
                "connected": True,
                "state": "RUNNING",
                "telemetry": {"filename": "cube.gcode", "progress": 42.0},
                "error": None,
            },
        )()
    )
    monkeypatch.setattr("connector.printbuddy_connector.get_provider_status", status)
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.status.result"
    assert response.payload["state"] == "RUNNING"
    assert "secret-check-code" not in json.dumps(response.payload)
    status.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_answers_flashforge_files_without_returning_credentials(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="printer.files.request",
        payload={
            "request_id": "files-ff-1",
            "ip_address": "192.168.1.10",
            "provider": "flashforge_creator5",
            "serial_number": "FF-42",
            "access_code": "secret-check-code",
        },
    )
    files = AsyncMock(return_value=([], "recent_only", "http-recent"))
    monkeypatch.setattr("connector.printbuddy_connector.list_flashforge_files", files)
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.files.result"
    assert response.payload["completeness"] == "recent_only"
    assert "secret-check-code" not in json.dumps(response.payload)
    files.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_answers_flashforge_control_without_returning_credentials(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1",
        type="printer.control.request",
        payload={
            "request_id": "control-ff-1",
            "ip_address": "192.168.1.10",
            "provider": "flashforge_ad5m",
            "serial_number": "FF-42",
            "access_code": "secret-check-code",
            "action": "pause",
        },
    )
    control = AsyncMock(return_value=("RUNNING", "PAUSE", "cube.gcode"))
    monkeypatch.setattr("connector.printbuddy_connector.execute_control", control)
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.control.result"
    assert response.payload["state_after"] == "PAUSE"
    assert "secret-check-code" not in json.dumps(response.payload)
    control.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_answers_flashforge_temperature_without_returning_credentials(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    request = ConnectorMessage(
        connector_id="connector-1", type="printer.temperature.request",
        payload={
            "request_id": "temperature-ff-1", "ip_address": "192.168.1.10",
            "provider": "flashforge_ad5m", "model": "Adventurer 5M",
            "serial_number": "FF-42", "access_code": "secret-check-code",
            "heater": "nozzle", "target": 210,
        },
    )
    temperature = AsyncMock(return_value=210.0)
    monkeypatch.setattr("connector.printbuddy_connector.execute_temperature", temperature)
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.temperature.result"
    assert response.payload["observed"] == 210.0
    assert "secret-check-code" not in json.dumps(response.payload)
    temperature.assert_awaited_once()


@pytest.mark.asyncio
async def test_agent_validation_error_does_not_echo_oversized_check_code(tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    secret = "check-code-that-must-not-leak-" * 12
    request = ConnectorMessage(
        connector_id="connector-1", type="printer.control.request",
        payload={
            "request_id": "control-invalid-1", "ip_address": "192.168.1.10",
            "provider": "flashforge_ad5m", "serial_number": "FF-42",
            "access_code": secret, "action": "pause",
        },
    )
    websocket = _WebSocket(request.model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.type == "printer.control.result"
    assert response.payload["error"] == "invalid Connector request"
    assert secret not in json.dumps(response.payload)


def test_agent_closes_incomplete_upload_sessions_on_connection_end(tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")

    class _Upload:
        closed = False

        def close(self):
            self.closed = True

    session = _Upload()
    agent._uploads["upload-1"] = session
    agent._close_uploads()

    assert session.closed is True
    assert agent._uploads == {}


@pytest.mark.asyncio
async def test_agent_abort_phase_removes_upload_staging(tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    begin = {
        "request_id": "begin-1", "upload_id": "upload-1", "phase": "begin",
        "ip_address": "192.168.1.10", "provider": "flashforge_ad5m",
        "serial_number": "SN", "access_code": "code", "filename": "cube.gcode", "size": 5,
    }
    session = UploadSession(ConnectorPrinterUploadRequest(**begin))
    staging_path = session.path
    agent._uploads["upload-1"] = session
    abort = {**begin, "request_id": "abort-1", "phase": "abort"}
    websocket = _WebSocket(ConnectorMessage(
        connector_id="connector-1", type="printer.upload.request", payload=abort,
    ).model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.payload["status"] == "aborted"
    assert "upload-1" not in agent._uploads
    assert staging_path.exists() is False


@pytest.mark.asyncio
async def test_duplicate_upload_begin_does_not_remove_existing_session(tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    begin = ConnectorPrinterUploadRequest(
        request_id="begin-existing", upload_id="upload-1", phase="begin",
        ip_address="192.168.1.10", provider="flashforge_ad5m",
        filename="cube.gcode", size=5,
    )
    session = UploadSession(begin)
    staging_path = session.path
    agent._uploads["upload-1"] = session
    duplicate = begin.model_copy(update={"request_id": "begin-duplicate"})
    websocket = _WebSocket(ConnectorMessage(
        connector_id="connector-1", type="printer.upload.request",
        payload=duplicate.model_dump(mode="json"),
    ).model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.payload["status"] == "failed"
    assert agent._uploads["upload-1"] is session
    assert staging_path.exists() is True
    agent._close_uploads()


@pytest.mark.asyncio
async def test_upload_finish_uses_destination_bound_by_begin(monkeypatch, tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    original = ConnectorPrinterUploadRequest(
        request_id="begin-original",
        upload_id="upload-bound",
        phase="begin",
        ip_address="192.168.1.10",
        provider="flashforge_ad5m",
        serial_number="SN-original",
        access_code="code-original",
        filename="original.gcode",
        size=0,
    )
    session = UploadSession(original)
    agent._uploads[original.upload_id] = session
    uploaded = []

    async def capture_upload(request, _path):
        uploaded.append(request)

    monkeypatch.setattr("connector.printbuddy_connector.upload_to_flashforge", capture_upload)
    altered_finish = original.model_copy(update={
        "request_id": "finish-altered",
        "phase": "finish",
        "ip_address": "8.8.8.8",
        "provider": "flashforge_creator5",
        "serial_number": "SN-altered",
        "access_code": "code-altered",
        "filename": "altered.gcode",
    })
    websocket = _WebSocket(ConnectorMessage(
        connector_id="connector-1",
        type="printer.upload.request",
        payload=altered_finish.model_dump(mode="json"),
    ).model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    assert uploaded == [original]
    assert agent._uploads == {}
    assert session.path.exists() is False


@pytest.mark.parametrize("existing_count,existing_size,new_size", [
    (MAX_ACTIVE_UPLOAD_SESSIONS, 0, 0),
    (1, MAX_UPLOAD_STAGING_BYTES, 1),
])
@pytest.mark.asyncio
async def test_agent_bounds_upload_staging_sessions_and_declared_bytes(
    tmp_path, existing_count, existing_size, new_size
):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    agent.connector_id = "connector-1"
    for index in range(existing_count):
        request = ConnectorPrinterUploadRequest(
            request_id=f"begin-{index}", upload_id=f"upload-{index}", phase="begin",
            ip_address="192.168.1.10", provider="flashforge_ad5m",
            filename="cube.gcode", size=existing_size,
        )
        agent._uploads[request.upload_id] = UploadSession(request)

    new_request = ConnectorPrinterUploadRequest(
        request_id="begin-new", upload_id="upload-new", phase="begin",
        ip_address="192.168.1.10", provider="flashforge_ad5m",
        filename="cube.gcode", size=new_size,
    )
    websocket = _WebSocket(ConnectorMessage(
        connector_id="connector-1", type="printer.upload.request",
        payload=new_request.model_dump(mode="json"),
    ).model_dump_json())

    with pytest.raises(RuntimeError, match="stop test"):
        await agent._receive_loop(websocket, asyncio.Lock())

    response = ConnectorMessage.model_validate_json(websocket.sent[0])
    assert response.payload["status"] == "failed"
    assert "upload-new" not in agent._uploads
    assert len(agent._uploads) == existing_count
    agent._close_uploads()


def test_agent_expires_idle_upload_staging(tmp_path):
    agent = ConnectorAgent("https://example.invalid", tmp_path / "state.json")
    session = UploadSession(ConnectorPrinterUploadRequest(
        request_id="begin-1", upload_id="upload-1", phase="begin",
        ip_address="192.168.1.10", provider="flashforge_ad5m",
        filename="cube.gcode", size=5,
    ))
    staging_path = session.path
    session.last_activity = 1
    agent._uploads["upload-1"] = session

    assert agent._cleanup_expired_uploads(now=1 + UPLOAD_SESSION_TTL_SECONDS) == 1
    assert agent._uploads == {}
    assert staging_path.exists() is False


async def _fake_discovery(request):
    return [
        {
            "ip_address": "192.168.1.2",
            "port": request.ports[0],
            "protocol": "http",
            "service": "moonraker",
            "reachable": True,
        }
    ]
