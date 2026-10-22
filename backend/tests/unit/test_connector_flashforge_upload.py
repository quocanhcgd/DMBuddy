import base64
from pathlib import Path

import pytest

from connector.flashforge_upload import UPLOAD_SESSION_TTL_SECONDS, UploadSession, upload_to_flashforge
from connector_protocol import ConnectorPrinterUploadRequest


def _request(**overrides):
    values = {
        "request_id": "upload-req",
        "upload_id": "upload-1",
        "phase": "begin",
        "ip_address": "192.168.1.10",
        "provider": "flashforge_creator5",
        "serial_number": "SN",
        "access_code": "secret-check-code",
        "filename": "cube.gcode",
        "size": 5,
    }
    values.update(overrides)
    return ConnectorPrinterUploadRequest(**values)


def test_upload_session_enforces_order_and_size(tmp_path):
    session = UploadSession(_request())
    try:
        assert session.accept_chunk(
            _request(phase="chunk", chunk_index=0, data_b64=base64.b64encode(b"hello").decode())
        ) == 5
        with pytest.raises(ValueError, match="Unexpected upload chunk"):
            session.accept_chunk(
                _request(phase="chunk", chunk_index=2, data_b64=base64.b64encode(b"!").decode())
            )
        path = session.finish(_request(phase="finish"))
        assert Path(path).read_bytes() == b"hello"
    finally:
        session.close()


def test_upload_session_rejects_mismatched_declared_size():
    session = UploadSession(_request(size=6))
    try:
        with pytest.raises(ValueError, match="does not match"):
            session.finish(_request(phase="finish"))
    finally:
        session.close()


def test_upload_session_expires_after_idle_ttl():
    session = UploadSession(_request())
    try:
        session.last_activity = 10
        assert session.is_expired(10 + UPLOAD_SESSION_TTL_SECONDS - 1) is False
        assert session.is_expired(10 + UPLOAD_SESSION_TTL_SECONDS) is True
    finally:
        session.close()


@pytest.mark.parametrize("filename", ["folder/cube.gcode", "folder\\cube.gcode", "../cube.gcode"])
def test_upload_session_rejects_non_basename_filename(filename):
    with pytest.raises(ValueError, match="basename"):
        UploadSession(_request(filename=filename))


@pytest.mark.asyncio
@pytest.mark.parametrize("host", ["8.8.8.8", "printer.example.com"])
async def test_upload_rejects_non_private_destination_before_network_io(tmp_path, host):
    path = tmp_path / "cube.gcode"
    path.write_bytes(b"G28\n")

    with pytest.raises(ValueError, match="private"):
        await upload_to_flashforge(_request(ip_address=host), path)
