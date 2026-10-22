import pytest

from backend.app.services.printer_providers.flashforge_contract import (
    CAP_BED_LEVELING,
    CAP_BED_LEVELING_BEFORE_PRINT,
    CAP_CHAMBER_TEMPERATURE,
    CAP_TOOL_TEMPERATURES,
    FLASHFORGE_AD5M_PROVIDER,
    FLASHFORGE_CREATOR5_PROVIDER,
    capability_snapshot,
    contract_for,
    validate_flashforge_config,
)


def _config(**overrides):
    value = {
        "name": "Workshop FlashForge",
        "provider": FLASHFORGE_AD5M_PROVIDER,
        "model": "Adventurer 5M Pro",
        "host": "http://192.168.1.60/",
        "serial_number": "SN-5M",
        "check_code": "LAN-CODE",
    }
    value.update(overrides)
    return value


def test_ad5m_contract_exposes_single_tool_and_tcp_file_capability():
    contract, model = contract_for(FLASHFORGE_AD5M_PROVIDER, "adventurer 5m pro")

    assert model == "Adventurer 5M Pro"
    assert contract.tcp_port == 8899
    assert contract.tool_count == 1
    assert contract.nozzle_max_c == 265
    assert contract.bed_max_c == 110
    assert CAP_TOOL_TEMPERATURES not in contract.capabilities


def test_creator5_contract_has_four_tools_and_no_tcp_capability():
    contract, model = contract_for(FLASHFORGE_CREATOR5_PROVIDER, "creator 5")

    assert model == "Creator 5"
    assert contract.tcp_port is None
    assert contract.tool_count == 4
    assert CAP_TOOL_TEMPERATURES in contract.capabilities
    assert CAP_CHAMBER_TEMPERATURE not in contract.capabilities


def test_creator5_pro_contract_default_is_four_tool_pro_model():
    contract, model = contract_for(FLASHFORGE_CREATOR5_PROVIDER)

    assert model == "Creator 5 Pro"
    assert contract.tool_count == 4
    assert contract.chamber_max_c == 65
    assert CAP_CHAMBER_TEMPERATURE in contract.capabilities
    pro = capability_snapshot(FLASHFORGE_CREATOR5_PROVIDER, "Creator 5 Pro")
    assert pro["capabilities"][CAP_CHAMBER_TEMPERATURE] == "implemented"


def test_runtime_capabilities_separate_implemented_partial_and_reference_only_features():
    ad5m = capability_snapshot(FLASHFORGE_AD5M_PROVIDER, "Adventurer 5M")
    creator5 = capability_snapshot(FLASHFORGE_CREATOR5_PROVIDER, "Creator 5")
    connector = capability_snapshot(FLASHFORGE_AD5M_PROVIDER, "Adventurer 5M", direct_transport=False)

    assert ad5m["capabilities"]["status"] == "implemented"
    assert ad5m["capabilities"]["local_files"] == "partial"
    assert ad5m["capabilities"]["nozzle_temperature"] == "implemented"
    assert ad5m["capabilities"]["cooling_fan"] == "implemented"
    assert ad5m["capabilities"]["chamber_fan"] == "implemented"
    assert ad5m["capabilities"]["camera"] == "implemented"
    assert ad5m["capabilities"]["filtration"] == "planned"
    assert ad5m["capabilities"][CAP_BED_LEVELING] == "planned"
    assert ad5m["capabilities"][CAP_BED_LEVELING_BEFORE_PRINT] == "implemented"
    assert "camera_stream" not in ad5m["unavailable_operations"]
    assert ad5m["hardware_verified"] is False
    assert creator5["provider_implemented"] is True
    assert creator5["capabilities"]["status"] == "implemented"
    assert creator5["capabilities"]["local_files"] == "partial"
    assert creator5["capabilities"]["nozzle_temperature"] == "implemented"
    assert creator5["capabilities"]["tool_temperatures"] == "implemented"
    assert creator5["capabilities"]["bed_temperature"] == "implemented"
    assert creator5["capabilities"]["material_status"] == "implemented"
    assert creator5["capabilities"]["filament_type_control"] == "implemented"
    assert creator5["capabilities"]["filament_color_control"] == "implemented"
    assert creator5["capabilities"]["file_upload"] == "implemented"
    assert creator5["capabilities"]["print_local_file"] == "implemented"
    assert creator5["capabilities"]["job_control"] == "implemented"
    assert creator5["capabilities"]["camera"] == "implemented"
    assert all(
        state == "planned"
        for key, state in creator5["capabilities"].items()
        if key not in {
            "status",
            "local_files",
            "nozzle_temperature",
            "tool_temperatures",
            "bed_temperature",
            "material_status",
            "filament_type_control",
            "filament_color_control",
            "file_upload",
            "print_local_file",
            "job_control",
            "camera",
            "bed_leveling_before_print",
            "flow_calibration_before_print",
            "time_lapse_before_print",
        }
    )
    assert connector["capabilities"]["status"] == "implemented"
    assert connector["capabilities"]["local_files"] == "partial"
    assert connector["capabilities"]["file_upload"] == "implemented"
    assert connector["capabilities"]["print_local_file"] == "implemented"
    assert connector["capabilities"]["job_control"] == "implemented"
    assert connector["capabilities"]["nozzle_temperature"] == "implemented"
    assert connector["capabilities"]["bed_temperature"] == "implemented"
    assert connector["capabilities"]["cooling_fan"] == "unavailable"
    assert connector["capabilities"]["camera"] == "unavailable"
    assert "camera" in connector["unavailable_operations"]


def test_creator5_connector_capabilities_are_model_specific():
    creator5 = capability_snapshot(FLASHFORGE_CREATOR5_PROVIDER, "Creator 5", direct_transport=False)
    creator5_pro = capability_snapshot(FLASHFORGE_CREATOR5_PROVIDER, "Creator 5 Pro", direct_transport=False)

    assert creator5["capabilities"]["tool_temperatures"] == "implemented"
    assert "chamber_temperature" not in creator5["capabilities"]
    assert creator5_pro["capabilities"]["chamber_temperature"] == "implemented"


def test_validate_config_normalizes_host_and_defaults_ports():
    normalized = validate_flashforge_config(_config())

    assert normalized["host"] == "192.168.1.60"
    assert normalized["ip_address"] == "192.168.1.60"
    assert normalized["http_port"] == 8898
    assert normalized["camera_port"] == 8080
    assert normalized["tcp_port"] == 8899


def test_validate_config_accepts_creator5_camel_case_fields_without_tcp():
    normalized = validate_flashforge_config(
        {
            "name": "Creator",
            "provider": FLASHFORGE_CREATOR5_PROVIDER,
            "model": "creator 5 pro",
            "host": "192.168.1.61",
            "serialNumber": "C5-SN",
            "checkCode": "C5-CODE",
            "httpPort": 9000,
            "cameraPort": 9001,
        }
    )

    assert normalized["model"] == "Creator 5 Pro"
    assert normalized["http_port"] == 9000
    assert normalized["camera_port"] == 9001
    assert "tcp_port" not in normalized


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"provider": "flashforge_creator5", "model": "Adventurer 5M"}, "Model must be one of"),
        ({"provider": "flashforge_ad5m", "model": "Creator 5"}, "Model must be one of"),
        ({"provider": "flashforge_creator5", "model": "Creator 5", "tcp_port": 8899}, "does not support"),
        ({"http_port": 0}, "HTTP port must be 1-65535"),
        ({"host": "http://192.168.1.60/path"}, "invalid characters"),
        ({"check_code": ""}, "serial_number and check_code are required"),
    ],
)
def test_validate_config_rejects_invalid_model_port_host_or_secret(overrides, message):
    with pytest.raises(ValueError, match=message):
        validate_flashforge_config(_config(**overrides))
