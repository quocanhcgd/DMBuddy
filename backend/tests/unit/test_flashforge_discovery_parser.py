"""Pure parser tests for inferred FlashForge discovery responses."""

from flashforge_discovery import parse_discovery_response, parse_m115_response


def _modern_packet(*, name: str, product_id: int, product_type: int = 0, status: int = 0, event_port: int = 8898) -> bytes:
    packet = bytearray(276)
    packet[: len(name.encode())] = name.encode()
    packet[0x84:0x86] = (8899).to_bytes(2, "big")
    packet[0x86:0x88] = (0x0102).to_bytes(2, "big")
    packet[0x88:0x8A] = product_id.to_bytes(2, "big")
    packet[0x8A:0x8C] = status.to_bytes(2, "big")
    packet[0x8C:0x8E] = product_type.to_bytes(2, "big")
    packet[0x8E:0x90] = event_port.to_bytes(2, "big")
    packet[0x90] = 1
    packet[0x92:0x92 + 8] = b"SN-1234\0"
    return bytes(packet)


def test_parse_modern_ad5m_maps_identity_and_ports():
    result = parse_discovery_response(_modern_packet(name="AD5M Pro", product_id=0x0024, status=1), "192.168.1.20")

    assert result is not None
    assert result.adapter_type == "flashforge_ad5m"
    assert result.model == "Adventurer 5M Pro"
    assert result.serial_number == "SN-1234"
    assert result.command_port == 8899
    assert result.http_port == 8898
    assert result.camera_port == 8080
    assert result.status == "busy"
    assert result.lan_mode is True


def test_parse_modern_creator5_does_not_promote_command_port_to_capability():
    result = parse_discovery_response(_modern_packet(name="Creator", product_id=0x0029), "10.0.0.8")

    assert result is not None
    assert result.adapter_type == "flashforge_creator5"
    assert result.model == "Creator 5 Pro"
    assert result.command_port == 8899
    assert result.http_port == 8898


def test_parse_legacy_packet_keeps_unknown_model_and_missing_fields_unknown():
    packet = bytearray(140)
    packet[: len(b"Legacy Printer")] = b"Legacy Printer"
    packet[0x84:0x86] = (8899).to_bytes(2, "big")
    packet[0x88:0x8A] = (0x9999).to_bytes(2, "big")
    result = parse_discovery_response(bytes(packet), "192.168.1.21")

    assert result is not None
    assert result.protocol == "legacy"
    assert result.model == "Unknown"
    assert result.serial_number == ""
    assert result.http_port is None
    assert result.camera_port is None
    assert result.adapter_type is None


def test_parser_rejects_short_or_partial_packets():
    assert parse_discovery_response(b"x" * 139, "192.168.1.22") is None


def test_parse_m115_accepts_only_flashforge_ad5m():
    response = "Machine Type: FlashForge Adventurer 5M Pro\nMachine Name: Lab A\nFirmware: 2.7.1\nSN: FF-42\nok\n"
    result = parse_m115_response(response, "192.168.1.23")

    assert result is not None
    assert result.protocol == "tcp-m115"
    assert result.model == "Adventurer 5M Pro"
    assert result.name == "Lab A"
    assert result.firmware_version == "2.7.1"


def test_parse_m115_rejects_non_flashforge_or_non_ad5m():
    assert parse_m115_response("Machine Type: Bambu X1\nSN: 1\n", "192.168.1.24") is None
    assert parse_m115_response("Machine Type: FlashForge Creator 5\nSN: 1\n", "192.168.1.24") is None
