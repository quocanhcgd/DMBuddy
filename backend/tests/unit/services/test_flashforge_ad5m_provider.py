from types import SimpleNamespace

import pytest

from backend.app.services.flashforge.errors import FlashForgeTransportError
from backend.app.services.printer_providers.factory import create_printer_client
from backend.app.services.printer_providers.flashforge_ad5m import (
    FlashForgeAd5mPrinterClient,
    create_flashforge_ad5m_client,
)


class FakeHttp:
    def __init__(self, detail=None, recent=None):
        self.detail_payload = detail or {}
        self.recent_payload = recent or {"gcodeList": []}
        self.closed = False
        self.print_calls = []
        self.control_calls = []
        self.upload_calls = []
        self.print_error = None
        self.control_error = None

    def detail(self):
        if isinstance(self.detail_payload, list):
            return self.detail_payload.pop(0)
        return self.detail_payload

    def gcode_list(self):
        if isinstance(self.recent_payload, Exception):
            raise self.recent_payload
        return self.recent_payload

    def close(self):
        self.closed = True

    def print_gcode(self, filename, **options):
        self.print_calls.append((filename, options))
        if self.print_error:
            raise self.print_error
        return {"code": 0}

    def control(self, command, args):
        self.control_calls.append((command, args))
        if self.control_error:
            raise self.control_error
        return {"code": 0}

    def upload_gcode(self, local_path, **options):
        self.upload_calls.append((local_path, options))
        return {"code": 0}


class FakeTcp:
    def __init__(self, response="CMD M661 Received.\n/data/cube.gcode::ok\n"):
        self.response = response

    def list_files_raw(self):
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_ad5m_provider_maps_only_reported_status_fields_and_emits_lifecycle():
    detail = {
        "status": "printing",
        "printProgress": 0.25,
        "printFileName": "cube.gcode",
        "printLayer": "12",
        "targetPrintLayer": "48",
        "estimatedTime": 121,
        "rightTemp": 205,
        "rightTargetTemp": 210,
        "platTemp": 55,
        "platTargetTemp": 60,
        "firmwareVersion": "1.2.3",
        "serialNumber": "private-serial",
        "checkCode": "private-code",
    }
    states = []
    starts = []
    http = FakeHttp({"detail": {"status": "ready"}})
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
        on_state_change=states.append,
        on_print_start=starts.append,
    )

    assert client.request_status_update() is True
    http.detail_payload = {"detail": detail}
    assert client.request_status_update() is True
    assert client.state.connected is True
    assert client.state.state == "RUNNING"
    assert client.state.progress == 25
    assert client.state.remaining_time == 3
    assert client.state.current_print == "cube.gcode"
    assert client.state.temperatures == {
        "nozzle": 205.0,
        "nozzle_target": 210.0,
        "nozzle_heating": True,
        "bed": 55.0,
        "bed_target": 60.0,
        "bed_heating": True,
    }
    assert client.state.firmware_version == "1.2.3"
    assert len(states) == 2
    assert all(state is client.state for state in states)
    assert starts[0]["filename"] == "cube.gcode"
    assert client.state.raw_data["detail"]["status"] == detail["status"]
    assert "serialNumber" not in client.state.raw_data["detail"]
    assert "checkCode" not in client.state.raw_data["detail"]


def test_ad5m_file_listing_prefers_full_tcp_list():
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M",
        serial_number="FF-SN",
        check_code="secret",
        http_client=FakeHttp(recent={"gcodeList": ["recent.gcode"]}),
        tcp_client=FakeTcp("CMD M661 Received.\n/data/cube.gcode::ok\n"),
    )

    assert client.list_files() == [
        {"name": "cube.gcode", "type": "file", "size": None, "modified": None, "path": "/cube.gcode"}
    ]
    assert client.state.raw_data["file_listing"] == {"complete": True, "source": "tcp-m661"}


def test_ad5m_file_listing_falls_back_to_marked_recent_files():
    http = FakeHttp(recent={"gcodeListDetail": [{"gcodeFileName": "recent.gx"}]})
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(FlashForgeTransportError("TCP unavailable")),
    )

    assert client.list_files() == [
        {"name": "recent.gx", "type": "file", "size": None, "modified": None, "path": "/recent.gx"}
    ]
    assert client.state.raw_data["file_listing"] == {"complete": False, "source": "http-recent"}


def test_ad5m_file_listing_does_not_retain_stale_completeness_after_both_sources_fail():
    http = FakeHttp(recent=FlashForgeTransportError("HTTP unavailable"))
    tcp = FakeTcp("CMD M661 Received.\n/data/cube.gcode::ok\n")
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=tcp,
    )

    assert client.list_files()
    tcp.response = FlashForgeTransportError("TCP unavailable")
    with pytest.raises(FlashForgeTransportError, match="HTTP unavailable"):
        client.list_files()

    assert "file_listing" not in client.state.raw_data


def test_ad5m_connect_closes_http_session_when_initial_status_fails():
    http = FakeHttp()

    def fail_detail():
        raise FlashForgeTransportError("printer offline")

    http.detail = fail_detail
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    with pytest.raises(FlashForgeTransportError, match="printer offline"):
        client.connect()

    assert http.closed is True
    assert client.state.connected is False


def test_ad5m_upload_uses_validated_basename_without_starting_print(tmp_path):
    source = tmp_path / "cube.gcode"
    source.write_text("G28\n", encoding="utf-8")
    http = FakeHttp()
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.upload_file(source, "/cube.gcode") is True
    assert http.upload_calls == [(source, {"remote_filename": "cube.gcode", "leveling_before_print": False})]
    with pytest.raises(ValueError, match="remote path"):
        client.upload_file(source, "/Metadata/../private.gcode")
    with pytest.raises(ValueError, match="root directory"):
        client.upload_file(source, "/Metadata/cube.gcode")


def test_ad5m_start_print_reconciles_ack_and_does_not_retry(tmp_path, monkeypatch):
    monkeypatch.setattr("backend.app.services.printer_providers.flashforge_ad5m.time.sleep", lambda _: None)
    http = FakeHttp(
        detail=[
            {"detail": {"status": "ready"}},
            {"detail": {"status": "ready"}},
            {"detail": {"status": "printing", "printFileName": "cube.gcode"}},
        ],
    )
    tcp = FakeTcp("CMD M661 Received.\n/data/cube.gcode::ok\n")
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=tcp,
    )

    assert client.start_print("/cube.gcode", bed_levelling=False) is True
    assert http.print_calls == [("cube.gcode", {"levelingBeforePrint": False})]
    assert len(http.print_calls) == 1


def test_ad5m_start_print_rejects_nested_path_and_unsupported_options():
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=FakeHttp(),
        tcp_client=FakeTcp(),
    )

    with pytest.raises(ValueError, match="root directory"):
        client.start_print("/Metadata/cube.gcode")
    with pytest.raises(ValueError, match="AMS mapping"):
        client.start_print("/cube.gcode", ams_mapping=[1])


@pytest.mark.parametrize(
    ("initial", "action", "observed", "expected"),
    [
        ("printing", "pause_print", "paused", "pause"),
        ("paused", "resume_print", "printing", "continue"),
        ("printing", "stop_print", "ready", "cancel"),
    ],
)
def test_ad5m_job_controls_reconcile_status(initial, action, observed, expected, monkeypatch):
    monkeypatch.setattr("backend.app.services.printer_providers.flashforge_ad5m.time.sleep", lambda _: None)
    http = FakeHttp(detail=[{"detail": {"status": initial}}, {"detail": {"status": observed}}])
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert getattr(client, action)() is True
    assert http.control_calls == [("jobCtl_cmd", {"jobID": "", "action": expected})]


def test_ad5m_job_action_ack_timeout_reconciles_without_retry(monkeypatch):
    monkeypatch.setattr("backend.app.services.printer_providers.flashforge_ad5m.time.sleep", lambda _: None)
    http = FakeHttp(detail=[{"detail": {"status": "printing"}}, {"detail": {"status": "paused"}}])
    http.control_error = FlashForgeTransportError("control response timed out")
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.pause_print() is True
    assert len(http.control_calls) == 1


@pytest.mark.parametrize(
    ("method", "initial", "observed", "target", "command_args"),
    [
        (
            "set_nozzle_temperature",
            {"status": "ready", "rightTargetTemp": 0},
            {"status": "ready", "rightTargetTemp": 215},
            215,
            {"rightNozzle": 215},
        ),
        (
            "set_bed_temperature",
            {"status": "printing", "platTargetTemp": 60},
            {"status": "printing", "platTargetTemp": 70},
            70,
            {"platform": 70},
        ),
    ],
)
def test_ad5m_temperature_controls_reconcile_status_without_retry(
    method, initial, observed, target, command_args, monkeypatch
):
    monkeypatch.setattr("backend.app.services.printer_providers.flashforge_ad5m.time.sleep", lambda _: None)
    http = FakeHttp(detail=[{"detail": initial}, {"detail": observed}])
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert getattr(client, method)(target) is True
    assert http.control_calls == [("temperatureCtl_cmd", command_args)]


def test_ad5m_temperature_controls_enforce_contract_range_before_network():
    http = FakeHttp()
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    with pytest.raises(ValueError, match="0-265 C"):
        client.set_nozzle_temperature(266)
    with pytest.raises(ValueError, match="0-110 C"):
        client.set_bed_temperature(111)
    assert http.control_calls == []


def test_ad5m_temperature_control_does_not_send_when_state_is_unknown():
    http = FakeHttp(detail={"detail": {"status": "unknown"}})
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.set_nozzle_temperature(210) is False
    assert http.control_calls == []


@pytest.mark.parametrize(
    ("fan", "status_field", "command_args"),
    [
        ("cooling", "coolingFanSpeed", {"coolingFan": 60}),
        ("chamber", "chamberFanSpeed", {"chamberFan": 40}),
    ],
)
def test_ad5m_fan_controls_validate_and_reconcile_status(fan, status_field, command_args):
    http = FakeHttp(
        detail=[
            {"detail": {"status": "ready"}},
            {"detail": {"status": "ready", status_field: next(iter(command_args.values()))}},
        ]
    )
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.set_fan_speed(fan, next(iter(command_args.values()))) is True
    assert http.control_calls == [("printerCtl_cmd", command_args)]


def test_ad5m_fan_controls_reject_unsupported_alias_and_range():
    http = FakeHttp()
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    with pytest.raises(ValueError, match="only cooling and chamber"):
        client.set_fan_speed("aux", 30)
    with pytest.raises(ValueError, match="0-100"):
        client.set_fan_speed("cooling", 101)
    assert http.control_calls == []


def test_ad5m_fan_timeout_reconciles_without_retry(monkeypatch):
    monkeypatch.setattr("backend.app.services.printer_providers.flashforge_ad5m.time.sleep", lambda _: None)
    http = FakeHttp(
        detail=[
            {"detail": {"status": "ready"}},
            {"detail": {"status": "ready", "coolingFanSpeed": 75}},
        ]
    )
    http.control_error = FlashForgeTransportError("control response timed out")
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.set_fan_speed("cooling", 75) is True
    assert http.control_calls == [("printerCtl_cmd", {"coolingFan": 75})]


def test_ad5m_camera_activation_uses_validated_firmware_url():
    http = FakeHttp(
        detail=[
            {"detail": {"status": "ready"}},
            {"detail": {"status": "ready", "cameraStreamUrl": "http://printer.local:8080/?action=stream"}},
        ]
    )
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.activate_camera() == "http://printer.local:8080/?action=stream"
    assert http.control_calls == [("streamCtrl_cmd", {"action": "open"})]


def test_ad5m_camera_activation_timeout_reconciles_without_retry():
    http = FakeHttp(
        detail=[
            {"detail": {"status": "ready"}},
            {"detail": {"status": "ready", "cameraStreamUrl": "http://printer.local:8080/live"}},
        ]
    )
    http.control_error = FlashForgeTransportError("control response timed out")
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.activate_camera() == "http://printer.local:8080/live"
    assert http.control_calls == [("streamCtrl_cmd", {"action": "open"})]


def test_ad5m_camera_activation_rejects_foreign_status_url_and_uses_fallback():
    http = FakeHttp(
        detail=[
            {"detail": {"status": "ready"}},
            {"detail": {"status": "ready", "cameraStreamUrl": "http://other-host:8080/live"}},
        ]
    )
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        camera_port=8081,
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.activate_camera() == "http://printer.local:8081/?action=stream"


def test_ad5m_camera_activation_does_not_open_when_printer_is_busy():
    http = FakeHttp({"detail": {"status": "heating"}})
    client = FlashForgeAd5mPrinterClient(
        host="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        check_code="secret",
        http_client=http,
        tcp_client=FakeTcp(),
    )

    assert client.activate_camera() is None
    assert http.control_calls == []


def test_ad5m_factory_decrypts_check_code_at_provider_boundary(monkeypatch):
    captured = {}

    def fake_decrypt(value):
        captured["stored"] = value
        return "decrypted-check-code"

    monkeypatch.setattr("backend.app.services.printer_providers.flashforge_ad5m.decrypt_check_code", fake_decrypt)
    printer = SimpleNamespace(
        provider="flashforge_ad5m",
        ip_address="printer.local",
        model="Adventurer 5M Pro",
        serial_number="FF-SN",
        auth_token="fernet:encrypted",
        provider_options='{"http_port": 9000, "tcp_port": 9001}',
    )

    client = create_flashforge_ad5m_client(printer)

    assert isinstance(client, FlashForgeAd5mPrinterClient)
    assert captured["stored"] == "fernet:encrypted"
    assert client.http_port == 9000
    assert client.tcp_port == 9001
    assert client.http._check_code == "decrypted-check-code"
    client.disconnect()


def test_factory_routes_creator5_to_http_provider_without_tcp_client():
    from backend.app.services.printer_providers.flashforge_creator5 import FlashForgeCreator5PrinterClient

    printer = SimpleNamespace(
        provider="flashforge_creator5",
        ip_address="printer.local",
        model="Creator 5 Pro",
        serial_number="FF-SN",
        auth_token="check-code",
        provider_options="{}",
    )

    client = create_printer_client(printer)

    assert isinstance(client, FlashForgeCreator5PrinterClient)
    assert not hasattr(client, "tcp")
    client.disconnect()
