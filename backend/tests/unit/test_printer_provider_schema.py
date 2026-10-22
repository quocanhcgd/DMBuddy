from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.app.schemas.printer import (
    CrealityCfsNanoStatusResponse,
    PrinterCreate,
    PrinterResponse,
    normalize_external_camera_update,
)


def _printer_payload(**overrides):
    payload = {
        "name": "Workshop P1S",
        "serial_number": " 01s00abc123 ",
        "ip_address": "192.168.1.20",
        "access_code": "12345678",
    }
    payload.update(overrides)
    return payload


def test_printer_create_defaults_to_bambu_provider():
    printer = PrinterCreate(**_printer_payload())

    assert printer.provider == "bambu"
    assert printer.serial_number == "01S00ABC123"


def test_creality_cfs_nano_status_preserves_unknown_slots_and_validates_identifiers():
    status = CrealityCfsNanoStatusResponse.model_validate(
        {
            "station_type": "CFS-Nano",
            "state": "connect",
            "online": True,
            "slots": [
                {"slot": "T1A", "material_name": "PLA", "color": "#0A2989"},
                {"slot": "T1B", "material_name": None, "color": None},
            ],
        }
    )

    assert status.slots[0].material_name == "PLA"
    assert status.slots[1].material_name is None
    with pytest.raises(ValidationError):
        CrealityCfsNanoStatusResponse.model_validate(
            {"slots": [{"slot": "AMS-A", "material_name": "PLA"}]}
        )


def test_printer_create_accepts_klipper_provider_metadata():
    printer = PrinterCreate(
        **_printer_payload(
            provider="klipper",
            api_url="http://voron.local:7125",
            auth_token="moonraker-token",
            provider_options='{"ui":"mainsail"}',
            external_camera_url="http://voron.local/webcam/?action=stream",
        )
    )

    assert printer.provider == "klipper"
    assert printer.api_url == "http://voron.local:7125"
    assert printer.external_camera_enabled is True
    assert printer.external_camera_type == "mjpeg"


def test_klipper_webrtc_camera_url_is_not_treated_as_mjpeg():
    printer = PrinterCreate(
        **_printer_payload(
            provider="fluidd",
            api_url="http://192.168.0.38:7125",
            external_camera_url="http://192.168.0.38/webcam/webrtc",
        )
    )

    assert printer.external_camera_type == "webrtc"


def test_klipper_printer_can_be_created_without_bambu_serial_or_access_code():
    printer = PrinterCreate(
        name="Voron 2.4",
        provider="klipper",
        ip_address="voron.local",
        api_url="http://voron.local:7125",
        external_camera_url="rtsp://voron.local/stream",
    )

    assert printer.provider == "klipper"
    assert printer.serial_number == "KLIPPER-VORON-LOCAL"
    assert printer.access_code == "moonraker"
    assert printer.external_camera_type == "rtsp"


def test_fluidd_printer_can_be_created_without_bambu_serial_or_access_code():
    printer = PrinterCreate(
        name="Elegoo Neptune 4 Pro",
        provider="fluidd",
        ip_address="neptune.local",
        external_camera_url="http://neptune.local/webcam/snapshot.jpg",
    )

    assert printer.provider == "fluidd"
    assert printer.api_url == "http://neptune.local:7125"
    assert printer.serial_number == "KLIPPER-NEPTUNE-LOCAL"
    assert printer.access_code == "moonraker"
    assert printer.external_camera_type == "snapshot"


def test_prusalink_printer_can_be_created_without_bambu_serial_or_access_code():
    printer = PrinterCreate.model_validate(
        {
            "name": "Prusa MK4S",
            "provider": "prusalink",
            "ip_address": "prusa.local",
            "serial_number": "",
            "access_code": "",
            "auth_token": "dummy-prusalink-password",
            "external_camera_url": "http://prusa.local/camera/stream",
        }
    )

    assert printer.provider == "prusalink"
    assert printer.api_url == "http://prusa.local"
    assert printer.serial_number == "PRUSALINK-PRUSA-LOCAL"
    assert printer.access_code == "prusalink"
    assert printer.auth_token == "dummy-prusalink-password"


def test_prusa_connect_mobile_printer_can_be_created_with_uuid_and_token_only():
    printer = PrinterCreate.model_validate(
        {
            "name": "MK4S via Connect",
            "provider": "prusaconnect",
            "ip_address": "13b5af3d-7b44-42b1-9327-cf8a6fbf3f3c",
            "auth_token": "dummy-connect-jwt",
        }
    )

    assert printer.provider == "prusaconnect"
    assert printer.serial_number == "PRUSACONNECT-13B5AF3D-7B44-42B1-9327-CF8A6FBF3F3C"[:50]
    assert printer.access_code == "prusaconnect"
    assert printer.api_url == "https://connect-mobile-api.prusa3d.com"
    assert printer.auth_token == "dummy-connect-jwt"


def test_elegoo_sdcp_printer_can_be_created_with_ip_only():
    printer = PrinterCreate.model_validate(
        {
            "name": "Centauri Carbon",
            "provider": "elegoo_sdcp",
            "ip_address": "centauri.local",
        }
    )

    assert printer.provider == "elegoo_sdcp"
    assert printer.serial_number == "ELEGOO-SDCP-CENTAURI-LOCAL"
    assert printer.access_code == "elegoo-sdcp"
    assert printer.api_url is None
    assert printer.auth_token is None


def test_non_bambu_printer_can_be_created_without_external_camera_url():
    printer = PrinterCreate(
        name="Voron 2.4",
        provider="klipper",
        ip_address="voron.local",
        api_url="http://voron.local:7125",
    )

    assert printer.provider == "klipper"
    assert printer.serial_number == "KLIPPER-VORON-LOCAL"
    assert printer.access_code == "moonraker"
    assert printer.external_camera_url is None
    assert printer.external_camera_type is None
    assert printer.external_camera_enabled is False


def test_external_camera_update_enables_and_infers_type_from_url_only_patch():
    update_data = normalize_external_camera_update(
        {
            "external_camera_url": "  http://neptune.local/webcam/?action=stream  ",
        }
    )

    assert update_data == {
        "external_camera_url": "http://neptune.local/webcam/?action=stream",
        "external_camera_enabled": True,
        "external_camera_type": "mjpeg",
    }


def test_external_camera_update_clears_disabled_state_when_url_is_blank():
    update_data = normalize_external_camera_update({"external_camera_url": "   "})

    assert update_data == {
        "external_camera_url": None,
        "external_camera_enabled": False,
        "external_camera_type": None,
    }


def test_printer_create_rejects_unknown_provider():
    with pytest.raises(ValidationError):
        PrinterCreate(**_printer_payload(provider="octoprint"))


def test_flashforge_create_canonicalizes_model_and_ports_without_exposing_secret():
    printer = PrinterCreate(
        name="AD5M Pro",
        provider="flashforge_ad5m",
        model="adventurer 5m pro",
        serial_number="ff-123",
        ip_address="192.168.1.60",
        auth_token="check-code",
    )

    assert printer.model == "Adventurer 5M Pro"
    assert printer.access_code == "flashforge"
    assert printer.provider_options == '{"http_port":8898,"camera_port":8080,"tcp_port":8899}'


def test_flashforge_creator5_rejects_tcp_option():
    with pytest.raises(ValidationError, match="does not support"):
        PrinterCreate(
            name="Creator 5",
            provider="flashforge_creator5",
            model="Creator 5",
            serial_number="creator-123",
            ip_address="creator.local",
            auth_token="check-code",
            provider_options='{"tcp_port":8899}',
        )


def test_printer_response_scrubs_credentials_and_reports_presence():
    row = SimpleNamespace(
        id=9, name="P1S", serial_number="SN", ip_address="192.168.1.2", access_code="secret",
        provider="bambu", api_url=None, auth_token="token", provider_options=None, model=None, location=None,
        auto_archive=True, reconnect_interval_seconds=30, external_camera_enabled=False,
        external_camera_url=None, external_camera_type=None, external_camera_snapshot_url=None, camera_rotation=0,
        is_active=True, nozzle_count=1, print_hours_offset=0.0, plate_detection_enabled=False,
        plate_detection_roi_x=None, plate_detection_roi_y=None, plate_detection_roi_w=None,
        plate_detection_roi_h=None, connector_id=None, connector_last_seen_at=None, connector_last_error=None,
        created_at="2026-01-01T00:00:00", updated_at="2026-01-01T00:00:00",
    )

    response = PrinterResponse.from_orm_with_roi(row)
    assert response.access_code is None
    assert response.auth_token is None
    assert response.access_code_set is True
    assert response.auth_token_set is True
    payload = response.model_dump()
    assert payload["access_code"] is None
    assert payload["auth_token"] is None
