"""FlashForge provider/model contract.

This module contains validation and capability metadata only. Network protocol
implementation belongs in provider clients and low-level FlashForge services.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from types import MappingProxyType
from typing import Any

FLASHFORGE_AD5M_PROVIDER = "flashforge_ad5m"
FLASHFORGE_CREATOR5_PROVIDER = "flashforge_creator5"
FLASHFORGE_PROVIDERS = frozenset({FLASHFORGE_AD5M_PROVIDER, FLASHFORGE_CREATOR5_PROVIDER})

AD5M_MODELS = frozenset({"Adventurer 5M", "Adventurer 5M Pro"})
CREATOR5_MODELS = frozenset({"Creator 5", "Creator 5 Pro"})

DEFAULT_HTTP_PORT = 8898
DEFAULT_TCP_PORT = 8899
DEFAULT_CAMERA_PORT = 8080

CAP_STATUS = "status"
CAP_LOCAL_FILES = "local_files"
CAP_FILE_UPLOAD = "file_upload"
CAP_FILE_DELETE = "file_delete"
CAP_PRINT_LOCAL_FILE = "print_local_file"
CAP_JOB_CONTROL = "job_control"
CAP_NOZZLE_TEMPERATURE = "nozzle_temperature"
CAP_TOOL_TEMPERATURES = "tool_temperatures"
CAP_BED_TEMPERATURE = "bed_temperature"
CAP_COOLING_FAN = "cooling_fan"
CAP_CHAMBER_FAN = "chamber_fan"
CAP_FILTRATION = "filtration"
CAP_BED_LEVELING = "bed_leveling"
CAP_BED_LEVELING_BEFORE_PRINT = "bed_leveling_before_print"
CAP_CAMERA = "camera"
CAP_CHAMBER_TEMPERATURE = "chamber_temperature"
CAP_MATERIAL_STATUS = "material_status"
CAP_FILAMENT_TYPE_CONTROL = "filament_type_control"
CAP_FILAMENT_COLOR_CONTROL = "filament_color_control"
CAP_PRINT_TOOL_MAPPING = "print_tool_mapping"
CAP_FLOW_CALIBRATION = "flow_calibration_before_print"
CAP_TIMELAPSE = "time_lapse_before_print"


@dataclass(frozen=True, slots=True)
class FlashForgeContract:
    """Immutable protocol/capability facts for one FlashForge model family."""

    provider: str
    models: frozenset[str]
    default_model: str
    http_port: int
    camera_port: int
    tcp_port: int | None
    tool_count: int
    nozzle_max_c: int
    bed_max_c: int
    chamber_max_c: int | None
    capabilities: frozenset[str]
    read_only_capabilities: frozenset[str] = frozenset()

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def is_read_only(self, capability: str) -> bool:
        return capability in self.read_only_capabilities


_AD5M_CAPABILITIES = frozenset({
    CAP_STATUS, CAP_LOCAL_FILES, CAP_FILE_UPLOAD, CAP_PRINT_LOCAL_FILE,
    CAP_JOB_CONTROL, CAP_NOZZLE_TEMPERATURE, CAP_BED_TEMPERATURE,
    CAP_COOLING_FAN, CAP_CHAMBER_FAN, CAP_FILTRATION, CAP_BED_LEVELING,
    CAP_BED_LEVELING_BEFORE_PRINT, CAP_CAMERA,
})

_CREATOR5_CAPABILITIES = frozenset({
    CAP_STATUS, CAP_LOCAL_FILES, CAP_FILE_UPLOAD, CAP_PRINT_LOCAL_FILE,
    CAP_JOB_CONTROL, CAP_NOZZLE_TEMPERATURE, CAP_TOOL_TEMPERATURES,
    CAP_BED_TEMPERATURE, CAP_BED_LEVELING, CAP_BED_LEVELING_BEFORE_PRINT,
    CAP_CAMERA, CAP_MATERIAL_STATUS,
    CAP_FILAMENT_TYPE_CONTROL, CAP_FILAMENT_COLOR_CONTROL, CAP_PRINT_TOOL_MAPPING,
    CAP_FLOW_CALIBRATION, CAP_TIMELAPSE,
})

_CREATOR5_PRO_CAPABILITIES = _CREATOR5_CAPABILITIES | {CAP_CHAMBER_TEMPERATURE}

CONTRACTS: Mapping[str, FlashForgeContract] = MappingProxyType({
    FLASHFORGE_AD5M_PROVIDER: FlashForgeContract(
        provider=FLASHFORGE_AD5M_PROVIDER, models=AD5M_MODELS,
        default_model="Adventurer 5M Pro", http_port=DEFAULT_HTTP_PORT,
        camera_port=DEFAULT_CAMERA_PORT, tcp_port=DEFAULT_TCP_PORT, tool_count=1,
        nozzle_max_c=265, bed_max_c=110, chamber_max_c=None, capabilities=_AD5M_CAPABILITIES,
    ),
    FLASHFORGE_CREATOR5_PROVIDER: FlashForgeContract(
        provider=FLASHFORGE_CREATOR5_PROVIDER, models=CREATOR5_MODELS,
        default_model="Creator 5 Pro", http_port=DEFAULT_HTTP_PORT,
        camera_port=DEFAULT_CAMERA_PORT, tcp_port=None, tool_count=4,
        nozzle_max_c=320, bed_max_c=120, chamber_max_c=None,
        capabilities=_CREATOR5_CAPABILITIES,
    ),
})

_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]+$")


def _validate_port(value: Any, label: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} port must be 1-65535")
    return port


def normalize_flashforge_host(value: Any) -> str:
    """Normalize a host without accepting a URL or path."""

    host = str(value or "").strip()
    host = re.sub(r"^https?://", "", host, flags=re.IGNORECASE).rstrip("/")
    if not host or not _HOST_RE.fullmatch(host):
        raise ValueError("FlashForge host/IP contains invalid characters")
    return host


def contract_for(provider: Any, model: Any = None) -> tuple[FlashForgeContract, str]:
    """Return the contract and canonical model for a provider/model pair."""

    provider_name = str(provider or "").strip().lower()
    contract = CONTRACTS.get(provider_name)
    if contract is None:
        raise ValueError(f"Unsupported FlashForge provider: {provider!r}")
    requested_model = str(model or contract.default_model).strip()
    canonical_model = next(
        (candidate for candidate in contract.models if candidate.lower() == requested_model.lower()), None
    )
    if canonical_model is None:
        allowed = ", ".join(sorted(contract.models))
        raise ValueError(f"Model must be one of: {allowed}")
    if provider_name == FLASHFORGE_CREATOR5_PROVIDER and canonical_model == "Creator 5 Pro":
        contract = replace(
            contract,
            chamber_max_c=65,
            capabilities=_CREATOR5_PRO_CAPABILITIES,
        )
    return contract, canonical_model


def validate_flashforge_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """Validate and normalize provider-neutral FlashForge connection fields."""

    if not isinstance(config, Mapping):
        raise ValueError("FlashForge configuration must be an object")
    contract, model = contract_for(config.get("provider"), config.get("model"))
    host = normalize_flashforge_host(config.get("host", config.get("ip_address")))
    name = str(config.get("name") or "").strip()
    serial_number = str(config.get("serial_number", config.get("serialNumber")) or "").strip()
    check_code = str(config.get("check_code", config.get("checkCode")) or "").strip()
    if not name:
        raise ValueError("FlashForge name is required")
    if not serial_number or not check_code:
        raise ValueError("FlashForge serial_number and check_code are required")

    http_port = _validate_port(config.get("http_port", config.get("httpPort", contract.http_port)), "HTTP")
    camera_port = _validate_port(config.get("camera_port", config.get("cameraPort", contract.camera_port)), "Camera")
    normalized: dict[str, Any] = {
        "name": name, "host": host, "ip_address": host,
        "serial_number": serial_number, "check_code": check_code,
        "provider": contract.provider, "model": model,
        "http_port": http_port, "camera_port": camera_port,
    }
    raw_tcp = config.get("tcp_port", config.get("tcpPort"))
    if contract.tcp_port is None:
        if raw_tcp is not None:
            raise ValueError("Creator 5 series does not support a TCP command port")
    else:
        normalized["tcp_port"] = _validate_port(raw_tcp if raw_tcp is not None else contract.tcp_port, "TCP command")
    return normalized


def validate_flashforge_options(provider: Any, model: Any, raw_options: Any) -> dict[str, int]:
    """Validate the non-secret, model-specific options persisted as JSON."""

    contract, _ = contract_for(provider, model)
    if raw_options in (None, ""):
        options: dict[str, Any] = {}
    elif isinstance(raw_options, Mapping):
        options = dict(raw_options)
    elif isinstance(raw_options, str):
        import json

        try:
            parsed = json.loads(raw_options)
        except (TypeError, ValueError) as exc:
            raise ValueError("FlashForge provider_options must be valid JSON") from exc
        if not isinstance(parsed, dict):
            raise ValueError("FlashForge provider_options must be a JSON object")
        options = parsed
    else:
        raise ValueError("FlashForge provider_options must be a JSON object")

    allowed = {"http_port", "camera_port"}
    if contract.tcp_port is not None:
        allowed.add("tcp_port")
    unknown = set(options) - allowed
    if unknown:
        if contract.tcp_port is None and "tcp_port" in unknown:
            raise ValueError("Creator 5 series does not support a TCP command port")
        raise ValueError(f"Unknown FlashForge provider_options: {', '.join(sorted(unknown))}")

    normalized = {
        "http_port": _validate_port(options.get("http_port", contract.http_port), "HTTP"),
        "camera_port": _validate_port(options.get("camera_port", contract.camera_port), "Camera"),
    }
    if contract.tcp_port is not None:
        normalized["tcp_port"] = _validate_port(options.get("tcp_port", contract.tcp_port), "TCP command")
    return normalized


def capability_snapshot(provider: Any, model: Any, *, direct_transport: bool = True) -> dict[str, Any]:
    """Describe implemented behavior separately from protocol-reference claims."""

    contract, canonical_model = contract_for(provider, model)
    capabilities = dict.fromkeys(sorted(contract.capabilities), "planned")
    provider_implemented = contract.provider in {FLASHFORGE_AD5M_PROVIDER, FLASHFORGE_CREATOR5_PROVIDER}

    if contract.provider == FLASHFORGE_AD5M_PROVIDER and direct_transport:
        implemented = {
            CAP_STATUS,
            CAP_FILE_UPLOAD,
            CAP_PRINT_LOCAL_FILE,
            CAP_JOB_CONTROL,
            CAP_BED_LEVELING_BEFORE_PRINT,
            CAP_CAMERA,
        }
        capabilities.update(dict.fromkeys(implemented, "implemented"))
        capabilities[CAP_LOCAL_FILES] = "partial"
        for name in {CAP_NOZZLE_TEMPERATURE, CAP_BED_TEMPERATURE}:
            if name in capabilities:
                capabilities[name] = "implemented"
        for name in {CAP_COOLING_FAN, CAP_CHAMBER_FAN}:
            if name in capabilities:
                capabilities[name] = "implemented"
    elif contract.provider == FLASHFORGE_CREATOR5_PROVIDER and direct_transport:
        for name in {
            CAP_FILE_UPLOAD,
            CAP_PRINT_LOCAL_FILE,
            CAP_JOB_CONTROL,
            CAP_BED_LEVELING_BEFORE_PRINT,
            CAP_FLOW_CALIBRATION,
            CAP_TIMELAPSE,
        }:
            if name in capabilities:
                capabilities[name] = "implemented"
        capabilities[CAP_STATUS] = "implemented"
        capabilities[CAP_LOCAL_FILES] = "partial"
        capabilities[CAP_NOZZLE_TEMPERATURE] = "implemented"
        capabilities[CAP_TOOL_TEMPERATURES] = "implemented"
        capabilities[CAP_BED_TEMPERATURE] = "implemented"
        capabilities[CAP_CAMERA] = "implemented"
        for name in {CAP_MATERIAL_STATUS, CAP_FILAMENT_TYPE_CONTROL, CAP_FILAMENT_COLOR_CONTROL}:
            if name in capabilities:
                capabilities[name] = "implemented"
        if CAP_CHAMBER_TEMPERATURE in capabilities:
            capabilities[CAP_CHAMBER_TEMPERATURE] = "implemented"

    if not direct_transport:
        capabilities = dict.fromkeys(capabilities, "unavailable")
        connector_implemented = {
            CAP_STATUS,
            CAP_LOCAL_FILES,
            CAP_FILE_UPLOAD,
            CAP_PRINT_LOCAL_FILE,
            CAP_JOB_CONTROL,
            CAP_NOZZLE_TEMPERATURE,
            CAP_BED_TEMPERATURE,
            CAP_BED_LEVELING_BEFORE_PRINT,
        }
        if contract.provider == FLASHFORGE_CREATOR5_PROVIDER:
            connector_implemented.add(CAP_TOOL_TEMPERATURES)
        if contract.chamber_max_c is not None:
            connector_implemented.add(CAP_CHAMBER_TEMPERATURE)
        for name in connector_implemented:
            if name in capabilities:
                capabilities[name] = "implemented"
        capabilities[CAP_LOCAL_FILES] = "partial"

    return {
        "provider": contract.provider,
        "model": canonical_model,
        "provider_implemented": provider_implemented,
        "transport": "direct" if direct_transport else "connector",
        "protocol_evidence": "source_inferred",
        "hardware_verified": False,
        "capabilities": capabilities,
        "unavailable_operations": [
            "file_delete",
            "directory_navigation",
            "storage_selection",
            "ams_mapping",
            "print_platform_selection",
        ] if direct_transport else [
            "camera",
            "fan_control",
            "filtration",
            "material_configuration",
            "file_delete",
            "directory_navigation",
            "storage_selection",
            "ams_mapping",
            "print_platform_selection",
        ],
    }
