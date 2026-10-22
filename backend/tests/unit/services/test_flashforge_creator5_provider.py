from pathlib import PurePosixPath

import pytest

from backend.app.services.printer_providers.flashforge_creator5 import FlashForgeCreator5PrinterClient


class FakeCreatorHttp:
    def __init__(self, detail=None, recent=None):
        self.detail_payload = detail or {"detail": {"status": "ready"}}
        self.recent_payload = recent or {"gcodeList": []}
        self.closed = False
        self.detail_calls = 0
        self.control_calls = []
        self.control_update = None
        self.print_calls = []
        self.print_update = None
        self.upload_calls = []

    def detail(self):
        self.detail_calls += 1
        return self.detail_payload

    def gcode_list(self):
        return self.recent_payload

    def control(self, command, args):
        self.control_calls.append((command, args))
        if getattr(self, "control_error", None):
            raise self.control_error
        if self.control_update:
            self.detail_payload = {"detail": self.control_update(command, args)}
        return {"code": 0}

    def print_gcode(self, filename, **options):
        self.print_calls.append((filename, options))
        if self.print_update:
            self.detail_payload = {"detail": self.print_update(filename, options)}
        return {"code": 0}

    def upload_gcode(self, local_path, **options):
        self.upload_calls.append((local_path, options))
        return {"code": 0}

    def close(self):
        self.closed = True


def _client(*, model="Creator 5", detail=None, recent=None, **kwargs):
    return FlashForgeCreator5PrinterClient(
        host="creator.local",
        model=model,
        serial_number="C5-SN",
        check_code="secret",
        http_client=FakeCreatorHttp(detail=detail, recent=recent),
        **kwargs,
    )


def test_creator5_status_maps_four_nozzles_without_guessing_active_tool_from_current_slot():
    client = _client(
        detail={
            "detail": {
                "status": "printing",
                "printProgress": 0.25,
                "printFileName": "four-tools.gcode",
                "nozzleTemps": [201, 202, 203, 204],
                "nozzleTargetTemps": [210, 0, 220, 0],
                "currentSlot": 3,
                "platTemp": 55,
                "platTargetTemp": 60,
            }
        }
    )

    assert client.request_status_update() is True
    assert len(client.state.nozzles) == 4
    assert client.state.state == "RUNNING"
    assert client.state.current_print == "four-tools.gcode"
    assert client.state.progress == 25
    assert client.state.temperatures["nozzle"] == 201
    assert client.state.temperatures["nozzle_2"] == 202
    assert client.state.temperatures["nozzle_3"] == 203
    assert client.state.temperatures["nozzle_4"] == 204
    assert client.state.active_extruder == -1
    assert client.state.raw_data["creator5_material_station"]["current_slot"] == 3
    assert "currentSlot" in client.state.raw_status


def test_creator5_status_sets_active_tool_only_when_one_nozzle_target_is_nonzero():
    client = _client(detail={"detail": {"status": "ready", "nozzleTargetTemps": [0, 215, 0, 0]}})

    client.request_status_update()

    assert client.state.active_extruder == 1


def test_creator5_status_redacts_credentials_from_saved_detail():
    client = _client(detail={"detail": {"status": "ready", "serialNumber": "private", "checkCode": "private"}})

    client.request_status_update()

    assert "serialNumber" not in client.state.raw_status
    assert "checkCode" not in client.state.raw_status


def test_creator5_camera_activation_uses_validated_firmware_url_once():
    client = _client(detail={"detail": {"status": "ready", "cameraStreamUrl": "http://creator.local:8080/live"}})

    assert client.activate_camera() == "http://creator.local:8080/live"
    assert client.http.control_calls == [("streamCtrl_cmd", {"action": "open"})]


def test_creator5_camera_activation_reconciles_timeout_without_repeating_command():
    from backend.app.services.flashforge.errors import FlashForgeTransportError

    client = _client(detail={"detail": {"status": "ready", "cameraStreamUrl": "http://creator.local:8080/live"}})
    client.http.control_error = FlashForgeTransportError("control response timed out")

    assert client.activate_camera() == "http://creator.local:8080/live"
    assert client.http.control_calls == [("streamCtrl_cmd", {"action": "open"})]


def test_creator5_camera_activation_rejects_foreign_host_before_fallback():
    client = _client(detail={"detail": {"status": "ready", "cameraStreamUrl": "http://other.local:8080/live"}})

    assert client.activate_camera() == "http://creator.local:8080/?action=stream"


def test_creator5_camera_activation_does_not_open_when_printer_is_busy():
    client = _client(detail={"detail": {"status": "heating"}})

    assert client.activate_camera() is None
    assert client.http.control_calls == []


def test_creator5_files_are_marked_recent_only_and_have_no_tcp_path():
    client = _client(recent={"gcodeListDetail": [{"gcodeFileName": "recent.gx"}]})

    files = client.list_files()

    assert files[0]["name"] == "recent.gx"
    assert client.state.raw_data["file_listing"] == {"complete": False, "source": "http-recent"}
    assert not hasattr(client, "tcp")

    with pytest.raises(ValueError, match="printer root"):
        client.list_files(str(PurePosixPath("/folder")))

    client.disconnect()
    assert client.http.closed is True


def test_creator5_nozzle_temperature_uses_tool_sentinel_and_verifies_readback():
    client = _client(detail={"detail": {"status": "ready", "nozzleTargetTemps": [0, 0, 0, 0]}})
    client.http.control_update = lambda _command, args: {
        "status": "ready",
        "nozzleTargetTemps": [args["nozzles"][0], args["nozzles"][1], args["nozzles"][2], args["nozzles"][3]],
    }

    assert client.set_nozzle_temperature(215, extruder=2) is True
    assert client.http.control_calls == [("temperatureCtl_cmd", {"nozzles": [-200, -200, 215, -200]})]


def test_creator5_temperature_timeout_does_not_repeat_side_effect():
    client = _client(detail={"detail": {"status": "ready", "nozzleTargetTemps": [0, 0, 0, 0]}})
    client.RECONCILE_INTERVAL_SECONDS = 0

    assert client.set_nozzle_temperature(215, extruder=1) is False
    assert len(client.http.control_calls) == 1


@pytest.mark.parametrize(
    ("target", "extruder", "message"),
    [(321, 0, "Nozzle temperature"), (200, 4, "index must be 0-3")],
)
def test_creator5_nozzle_temperature_validates_model_range_and_tool_index(target, extruder, message):
    client = _client()

    with pytest.raises(ValueError, match=message):
        client.set_nozzle_temperature(target, extruder=extruder)


def test_creator5_bed_temperature_uses_platform_field_and_readback():
    client = _client(detail={"detail": {"status": "ready", "platTargetTemp": 0}})
    client.http.control_update = lambda _command, args: {"status": "ready", "platTargetTemp": args["platform"]}

    assert client.set_bed_temperature(85) is True
    assert client.http.control_calls == [("temperatureCtl_cmd", {"platform": 85})]


def test_creator5_pro_chamber_temperature_uses_chamber_field_and_readback():
    client = _client(
        model="Creator 5 Pro",
        detail={"detail": {"status": "ready", "chamberTargetTemp": 0}},
    )
    client.http.control_update = lambda _command, args: {
        "status": "ready",
        "chamberTargetTemp": args["chamber"],
    }

    assert client.set_chamber_temperature(60) is True
    assert client.http.control_calls == [("temperatureCtl_cmd", {"chamber": 60})]


def test_creator5_standard_model_rejects_chamber_temperature():
    client = _client()

    with pytest.raises(ValueError, match="only supported by Creator 5 Pro"):
        client.set_chamber_temperature(45)


def test_creator5_pro_chamber_temperature_enforces_65_degree_limit():
    client = _client(model="Creator 5 Pro")

    with pytest.raises(ValueError, match="0-65°C"):
        client.set_chamber_temperature(66)


def test_creator5_material_config_uses_one_based_slot_and_verifies_readback():
    initial = {
        "detail": {
            "status": "ready",
            "slotInfos": [
                {"slotId": 1, "materialName": "PLA", "materialColor": "#FFFFFF"},
                {"slotId": 2, "materialName": "PETG", "materialColor": "#F82D29"},
                {"slotId": 3, "materialName": "ABS", "materialColor": "#1B1B1B"},
                {"slotId": 4, "materialName": "ASA", "materialColor": "#FFF245"},
            ],
        }
    }
    client = _client(detail=initial)
    client.http.control_update = lambda _command, args: {
        "status": "ready",
        "slotInfos": [
            {"slotId": 1, "materialName": "PLA", "materialColor": "#FFFFFF"},
            {"slotId": 2, "materialName": args["mt"], "materialColor": args["rgb"]},
            {"slotId": 3, "materialName": "ABS", "materialColor": "#1B1B1B"},
            {"slotId": 4, "materialName": "ASA", "materialColor": "#FFF245"},
        ],
    }

    assert client.set_filament_config(1, material="pla-cf") is True
    assert client.http.control_calls == [("msConfig_cmd", {"slot": 2, "mt": "PLA-CF", "rgb": "#F82D29"})]


@pytest.mark.parametrize(
    ("material", "color", "message"),
    [("PLA+", None, "supported Creator 5 filament type"), (None, "red", "supported Creator 5 filament color")],
)
def test_creator5_material_config_rejects_values_outside_reference_allowlists(material, color, message):
    client = _client(
        detail={
            "detail": {
                "status": "ready",
                "slotInfos": [{"slotId": 1, "materialName": "PLA", "materialColor": "#FFFFFF"}],
            }
        }
    )

    with pytest.raises(ValueError, match=message):
        client.set_filament_config(0, material=material, color=color)
    assert client.http.control_calls == []


def test_creator5_material_config_requires_idle_and_complete_readback_metadata():
    printing = _client(detail={"detail": {"status": "printing"}})
    with pytest.raises(ValueError, match="only be changed while the printer is idle"):
        printing.set_filament_config(0, material="PLA", color="#FFFFFF")
    assert printing.http.control_calls == []

    unknown = _client(detail={"detail": {"status": "ready"}})
    with pytest.raises(ValueError, match="supported Creator 5 filament color"):
        unknown.set_filament_config(0, material="PLA")
    assert unknown.http.control_calls == []


def test_creator5_material_config_does_not_repeat_command_when_readback_does_not_match():
    client = _client(
        detail={
            "detail": {
                "status": "ready",
                "slotInfos": [{"slotId": 1, "materialName": "PLA", "materialColor": "#FFFFFF"}],
            }
        }
    )
    client.http.control_update = lambda _command, _args: {
        "status": "ready",
        "slotInfos": [{"slotId": 1, "materialName": "PLA", "materialColor": "#FFFFFF"}],
    }

    assert client.set_filament_config(0, material="PETG", color="#F82D29") is False
    assert len(client.http.control_calls) == 1


def test_creator5_start_print_checks_idle_and_recent_file_then_reconciles_filename():
    client = _client(
        detail={"detail": {"status": "ready"}},
        recent={"gcodeList": ["cube.gcode"]},
    )
    client.http.print_update = lambda filename, _options: {
        "status": "printing",
        "printFileName": filename,
    }

    assert client.start_print("/cube.gcode", bed_levelling=False, flow_cali=True, timelapse=True) is True
    assert client.http.print_calls == [
        (
            "cube.gcode",
            {"levelingBeforePrint": False, "flowCalibration": True, "timeLapseVideo": True},
        )
    ]


def test_creator5_start_print_sends_explicit_upstream_material_mappings():
    client = _client(
        detail={"detail": {"status": "ready"}},
        recent={"gcodeList": ["multi.3mf"]},
    )
    client.http.print_update = lambda filename, _options: {"status": "printing", "printFileName": filename}
    mappings = [
        {
            "toolId": 0,
            "slotId": 3,
            "materialName": "PLA",
            "toolMaterialColor": "#2EC4B6",
            "slotMaterialColor": "#2EC4B6",
        },
        {
            "toolId": 1,
            "slotId": 1,
            "materialName": "PETG",
            "toolMaterialColor": "#FF6B35",
            "slotMaterialColor": "#FF6B35",
        },
    ]

    assert client.start_print("multi.3mf", creator5_material_mappings=mappings) is True
    assert client.http.print_calls == [
        (
            "multi.3mf",
            {
                "levelingBeforePrint": True,
                "flowCalibration": False,
                "timeLapseVideo": False,
                "materialMappings": mappings,
            },
        )
    ]


@pytest.mark.parametrize(
    "mappings",
    [
        [{"toolId": 0, "slotId": 1, "materialName": "PLA", "toolMaterialColor": "#FFFFFF", "slotMaterialColor": "#FFFFFF"}],
        [
            {"toolId": 0, "slotId": 1, "materialName": "PLA", "toolMaterialColor": "#FFFFFF", "slotMaterialColor": "#FFFFFF"},
            {"toolId": 0, "slotId": 2, "materialName": "PLA", "toolMaterialColor": "#FFFFFF", "slotMaterialColor": "#FFFFFF"},
        ],
        [
            {"toolId": 0, "slotId": 1, "materialName": "PLA", "toolMaterialColor": "#FFFFFF", "slotMaterialColor": "#FFFFFF"},
            {"toolId": 1, "slotId": 1, "materialName": "PETG", "toolMaterialColor": "#000000", "slotMaterialColor": "#FFFFFF"},
        ],
        [
            {"toolId": 0, "slotId": 5, "materialName": "PLA", "toolMaterialColor": "#FFFFFF", "slotMaterialColor": "#FFFFFF"},
            {"toolId": 1, "slotId": 2, "materialName": "PETG", "toolMaterialColor": "#000000", "slotMaterialColor": "#000000"},
        ],
    ],
)
def test_creator5_start_print_rejects_invalid_material_mapping_before_command(mappings):
    client = _client(detail={"detail": {"status": "ready"}}, recent={"gcodeList": ["multi.3mf"]})

    with pytest.raises(ValueError, match="Creator 5"):
        client.start_print("multi.3mf", creator5_material_mappings=mappings)
    assert client.http.print_calls == []


def test_creator5_start_print_rejects_unknown_local_file_and_mapping_options():
    client = _client(detail={"detail": {"status": "ready"}}, recent={"gcodeList": ["other.gcode"]})

    assert client.start_print("missing.gcode") is False
    assert client.http.print_calls == []
    with pytest.raises(ValueError, match="tool mapping is unavailable"):
        client.start_print("other.gcode", ams_mapping=[1])
    with pytest.raises(ValueError, match="root directory"):
        client.start_print("/nested/other.gcode")


def test_creator5_start_print_does_not_repeat_command_when_readback_times_out():
    client = _client(detail={"detail": {"status": "ready"}}, recent={"gcodeList": ["cube.gcode"]})
    client.RECONCILE_INTERVAL_SECONDS = 0

    assert client.start_print("cube.gcode") is False
    assert len(client.http.print_calls) == 1


@pytest.mark.parametrize(
    ("initial", "action", "updated", "method"),
    [
        ("printing", "pause", "paused", "pause_print"),
        ("paused", "continue", "printing", "resume_print"),
        ("printing", "cancel", "ready", "stop_print"),
    ],
)
def test_creator5_job_controls_precheck_send_once_and_reconcile(initial, action, updated, method):
    client = _client(detail={"detail": {"status": initial, "printFileName": "cube.gcode"}})
    client.http.control_update = lambda _command, _args: {"status": updated, "printFileName": "cube.gcode"}

    assert getattr(client, method)() is True
    assert client.http.control_calls == [("jobCtl_cmd", {"jobID": "", "action": action})]


def test_creator5_job_control_does_not_send_action_when_state_precondition_fails():
    client = _client(detail={"detail": {"status": "ready"}})

    assert client.pause_print() is False
    assert client.http.control_calls == []


def test_creator5_upload_sends_material_station_headers_and_keeps_start_separate(tmp_path):
    source = tmp_path / "multi.gcode"
    source.write_text("G28\n", encoding="ascii")
    client = _client()

    assert client.upload_file(source, "/multi.gcode", tool_count=3) is True
    assert client.http.upload_calls == [
        (
            source,
            {
                "remote_filename": "multi.gcode",
                "leveling_before_print": False,
                "extra_headers": {
                    "useMatlStation": "true",
                    "gcodeToolCnt": "3",
                    "flowCalibration": "false",
                    "timeLapseVideo": "false",
                },
            },
        )
    ]


@pytest.mark.parametrize("tool_count", [0, 5])
def test_creator5_upload_rejects_tool_count_outside_four_tool_contract(tmp_path, tool_count):
    source = tmp_path / "cube.gcode"
    source.write_text("G28\n", encoding="ascii")
    client = _client()

    with pytest.raises(ValueError, match="tool_count must be 1-4"):
        client.upload_file(source, "cube.gcode", tool_count=tool_count)
    assert client.http.upload_calls == []
