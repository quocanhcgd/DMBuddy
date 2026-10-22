"""Pure FlashForge LAN discovery packet parsers.

The wire layout is inferred from the Print-Farm-Controller reference project.
This module deliberately has no network side effects so its parsing contract can
be tested independently before discovery sockets are enabled.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

MODERN_SIZE = 276
LEGACY_SIZE = 140
DEFAULT_COMMAND_PORT = 8899
DEFAULT_HTTP_PORT = 8898
DEFAULT_CAMERA_PORT = 8080

MODERN_MODELS = {
    0x0023: "Adventurer 5M",
    0x0024: "Adventurer 5M Pro",
    0x0026: "AD5X",
    0x0028: "Creator 5",
    0x0029: "Creator 5 Pro",
}


@dataclass(frozen=True)
class FlashForgeDiscoveryResult:
    """Sanitized identity and endpoint data from one discovery response."""

    protocol: str
    adapter_type: str | None
    manufacturer: str
    name: str
    host: str
    serial_number: str
    model: str
    command_port: int | None
    http_port: int | None
    camera_port: int | None
    vendor_id: int | None
    product_id: int | None
    product_type: int | None
    status: str
    lan_mode: bool | None
    firmware_version: str | None = None

    def to_dict(self) -> dict[str, object | None]:
        return asdict(self)


def _clean_string(packet: bytes, start: int, end: int) -> str:
    value = packet[start:end].split(b"\0", 1)[0]
    return value.decode("utf-8", errors="replace").strip()


def _status_name(code: int) -> str:
    return {0: "ready", 1: "busy", 2: "error"}.get(code, "unknown")


def _modern_model(name: str, product_id: int, product_type: int) -> str:
    if product_id in MODERN_MODELS:
        return MODERN_MODELS[product_id]
    upper = name.upper()
    if product_type == 0x5A02 or "ADVENTURER 5M" in upper or "AD5M" in upper:
        return "Adventurer 5M Pro" if "PRO" in upper else "Adventurer 5M"
    if upper == "AD5X":
        return "AD5X"
    return "Unknown"


def _legacy_model(name: str, product_id: int) -> str:
    upper = name.upper()
    if (
        "ADVENTURER 4" in upper
        or "ADVENTURER4" in upper
        or "AD4" in upper
        or product_id in {0x0016, 0x001E}
    ):
        return "Adventurer 4"
    if (
        "ADVENTURER 3" in upper
        or "ADVENTURER3" in upper
        or "AD3" in upper
        or product_id == 0x0008
    ):
        return "Adventurer 3"
    return "Unknown"


def _adapter_type(model: str) -> str | None:
    if model in {"Adventurer 5M", "Adventurer 5M Pro"}:
        return "flashforge_ad5m"
    if model in {"Creator 5", "Creator 5 Pro"}:
        return "flashforge_creator5"
    return None


def parse_discovery_response(packet: bytes, remote_address: str) -> FlashForgeDiscoveryResult | None:
    """Parse an inferred FlashForge UDP response.

    Packets shorter than the legacy 140-byte layout are ignored. A modern
    response is selected only when at least 276 bytes are available, matching
    the reference parser and avoiding partial-field reads.
    """

    if not isinstance(packet, bytes) or len(packet) < LEGACY_SIZE:
        return None

    if len(packet) >= MODERN_SIZE:
        name = _clean_string(packet, 0x00, 0x84)
        command_port = int.from_bytes(packet[0x84:0x86], "big")
        vendor_id = int.from_bytes(packet[0x86:0x88], "big")
        product_id = int.from_bytes(packet[0x88:0x8A], "big")
        status_code = int.from_bytes(packet[0x8A:0x8C], "big")
        product_type = int.from_bytes(packet[0x8C:0x8E], "big")
        event_port = int.from_bytes(packet[0x8E:0x90], "big")
        lan_mode = packet[0x90] == 1
        serial_number = _clean_string(packet, 0x92, 0x92 + 128)
        model = _modern_model(name, product_id, product_type)
        return FlashForgeDiscoveryResult(
            protocol="modern",
            adapter_type=_adapter_type(model),
            manufacturer="FlashForge",
            name=name or f"FlashForge {remote_address}",
            host=remote_address,
            serial_number=serial_number,
            model=model,
            command_port=command_port,
            # The reference calls this field eventPort and uses it as HTTP.
            http_port=event_port or DEFAULT_HTTP_PORT,
            camera_port=DEFAULT_CAMERA_PORT,
            vendor_id=vendor_id,
            product_id=product_id,
            product_type=product_type,
            status=_status_name(status_code),
            lan_mode=lan_mode,
        )

    name = _clean_string(packet, 0x00, 0x80)
    command_port = int.from_bytes(packet[0x84:0x86], "big")
    vendor_id = int.from_bytes(packet[0x86:0x88], "big")
    product_id = int.from_bytes(packet[0x88:0x8A], "big")
    status_code = int.from_bytes(packet[0x8A:0x8C], "big")
    model = _legacy_model(name, product_id)
    return FlashForgeDiscoveryResult(
        protocol="legacy",
        adapter_type=None,
        manufacturer="FlashForge",
        name=name or f"FlashForge {remote_address}",
        host=remote_address,
        serial_number="",
        model=model,
        command_port=command_port,
        http_port=None,
        camera_port=None,
        vendor_id=vendor_id,
        product_id=product_id,
        product_type=None,
        status=_status_name(status_code),
        lan_mode=None,
    )


def _m115_field(response: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}\s*:\s*(.+)$", response, re.IGNORECASE | re.MULTILINE)
    return match.group(1).strip() if match else ""


def parse_m115_response(response: str, host: str, *, command_port: int = DEFAULT_COMMAND_PORT) -> FlashForgeDiscoveryResult | None:
    """Parse the bounded TCP ``~M115`` fallback used for AD5M discovery."""

    text = str(response or "")
    if not re.search(r"Machine Type\s*:", text, re.IGNORECASE) or not re.search(r"\bSN\s*:", text, re.IGNORECASE):
        return None
    machine_type = _m115_field(text, "Machine Type")
    serial_number = _m115_field(text, "SN")
    if not serial_number or not re.search("flashforge", machine_type, re.IGNORECASE):
        return None
    if "ADVENTURER 5M" not in machine_type.upper():
        return None
    model = "Adventurer 5M Pro" if "PRO" in machine_type.upper() else "Adventurer 5M"
    firmware_version = _m115_field(text, "Firmware") or None
    name = _m115_field(text, "Machine Name") or model
    return FlashForgeDiscoveryResult(
        protocol="tcp-m115",
        adapter_type="flashforge_ad5m",
        manufacturer="FlashForge",
        name=name,
        host=host,
        serial_number=serial_number,
        model=model,
        command_port=command_port,
        http_port=DEFAULT_HTTP_PORT,
        camera_port=DEFAULT_CAMERA_PORT,
        vendor_id=None,
        product_id=None,
        product_type=None,
        status="unknown",
        lan_mode=None,
        firmware_version=firmware_version,
    )


__all__ = [
    "DEFAULT_CAMERA_PORT",
    "DEFAULT_COMMAND_PORT",
    "DEFAULT_HTTP_PORT",
    "FlashForgeDiscoveryResult",
    "LEGACY_SIZE",
    "MODERN_SIZE",
    "parse_discovery_response",
    "parse_m115_response",
]
