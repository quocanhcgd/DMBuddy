"""Bounded parsing of logical Creator 5 tools used by a queued print file."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

_MAX_EMBEDDED_GCODE_BYTES = 16 * 1024 * 1024
_MAX_PLAIN_GCODE_BYTES = 64 * 1024 * 1024
_MAX_ZIP_ENTRIES = 10_000
_MAX_TOOL_ID = 3
_PLATE_GCODE_RE = re.compile(r"^Metadata/plate_(\d+)\.gcode$", re.IGNORECASE)


def _split_values(value: str) -> list[str]:
    return [part.strip().strip("'\"") for part in re.split(r"[;,]", value) if part.strip()]


def _tool_ids_from_gcode(text: str) -> tuple[set[int], set[int], dict[str, list[str]]]:
    explicit_tools: set[int] = set()
    weighted_tools: set[int] = set()
    metadata: dict[str, list[str]] = {}

    for line in text.splitlines():
        config = re.match(r"^\s*;?\s*([^:=]+?)\s*[:=]\s*(.*?)\s*$", line)
        if config:
            key = config.group(1).strip().lower()
            metadata.setdefault(key, _split_values(config.group(2)))

        code = line.split(";", 1)[0].strip()
        command = re.match(r"^(?:N\d+\s+)?T(\d+)(?:\s|$)", code, re.IGNORECASE)
        if command:
            explicit_tools.add(int(command.group(1)))

    weights = metadata.get("filament used [g]") or metadata.get("filament_used_g") or []
    for index, value in enumerate(weights):
        try:
            if float(value) > 0:
                weighted_tools.add(index)
        except (TypeError, ValueError):
            continue

    return explicit_tools, weighted_tools, metadata


def _validate_tool_ids(tool_ids: set[int]) -> set[int]:
    if not tool_ids:
        raise ValueError("Creator 5 queue file does not identify any required logical tools")
    if any(tool_id < 0 or tool_id > _MAX_TOOL_ID for tool_id in tool_ids):
        raise ValueError("Creator 5 queue file references a logical tool outside tool IDs 0-3")
    return tool_ids


def _required_tools_from_text(text: str) -> set[int]:
    explicit, weighted, metadata = _tool_ids_from_gcode(text)
    evidenced_tools = explicit | weighted
    if evidenced_tools:
        return _validate_tool_ids(evidenced_tools)

    detected_count = max(
        len(metadata.get("filament_type", [])),
        len(metadata.get("filament_types", [])),
        len(metadata.get("filament_colour", [])),
        len(metadata.get("filament_color", [])),
        len(metadata.get("extruder_colour", [])),
        len(metadata.get("extruder_color", [])),
        len(metadata.get("nozzle_diameter", [])),
        len(metadata.get("nozzle_diameters", [])),
        len(metadata.get("filament_settings_id", [])),
        len(metadata.get("filament_settings_ids", [])),
        len(metadata.get("filament_preset", [])),
        len(metadata.get("filament_presets", [])),
        len(metadata.get("filament_vendor", [])),
        len(metadata.get("filament_vendors", [])),
    )
    if detected_count == 1:
        return {0}
    if detected_count > 1:
        raise ValueError("Creator 5 queue file has ambiguous tool usage; refusing material mappings")
    raise ValueError("Creator 5 queue file has no readable logical tool usage; refusing material mappings")


def _read_gcode_text(file_path: Path, plate_id: int | None) -> str:
    """Read a bounded standalone G-code file or one selected 3MF plate."""
    suffix = file_path.suffix.lower()
    if suffix in {".gcode", ".gx", ".g"}:
        size = file_path.stat().st_size
        if size > _MAX_PLAIN_GCODE_BYTES:
            raise ValueError("Creator 5 G-code exceeds the 64 MiB tool-inspection limit")
        return file_path.read_text(encoding="utf-8", errors="replace")
    if suffix != ".3mf":
        raise ValueError("Creator 5 material mappings require a supported G-code or 3MF file")

    try:
        with zipfile.ZipFile(file_path) as archive:
            entries = archive.infolist()
            if len(entries) > _MAX_ZIP_ENTRIES:
                raise ValueError("Creator 5 3MF contains too many ZIP entries to inspect safely")
            plates = [(entry, _PLATE_GCODE_RE.fullmatch(entry.filename)) for entry in entries]
            plates = [(entry, match) for entry, match in plates if match]
            if plate_id is not None:
                selected = [(entry, match) for entry, match in plates if int(match.group(1)) == plate_id]
                if len(selected) != 1:
                    raise ValueError(f"Creator 5 3MF does not contain one unambiguous G-code entry for plate {plate_id}")
            elif len(plates) == 1:
                selected = plates
            elif not plates:
                raise ValueError("Creator 5 3MF does not contain embedded plate G-code")
            else:
                raise ValueError("Creator 5 3MF has multiple plates; select a plate before mapping tools")

            entry = selected[0][0]
            if entry.file_size > _MAX_EMBEDDED_GCODE_BYTES:
                raise ValueError("Creator 5 embedded plate G-code exceeds the 16 MiB inspection limit")
            with archive.open(entry) as embedded:
                content = embedded.read(_MAX_EMBEDDED_GCODE_BYTES + 1)
            if len(content) > _MAX_EMBEDDED_GCODE_BYTES:
                raise ValueError("Creator 5 embedded plate G-code exceeds the 16 MiB inspection limit")
            return content.decode("utf-8", errors="replace")
    except (zipfile.BadZipFile, OSError, RuntimeError, EOFError, NotImplementedError) as exc:
        raise ValueError("Creator 5 queue file is not a readable 3MF archive") from exc


def extract_creator5_tool_metadata(file_path: Path, plate_id: int | None = None) -> list[dict[str, object]]:
    """Return logical tool IDs with material/color metadata when the G-code has it.

    3MF plate selection follows Printbuddy's 1-based ``plate_id`` contract.
    Embedded G-code is read with a strict uncompressed-size bound. A multi-plate
    archive without an explicit plate selection is rejected as ambiguous.
    """
    text = _read_gcode_text(file_path, plate_id)
    required_tools = _required_tools_from_text(text)
    _, _, metadata = _tool_ids_from_gcode(text)
    material_values = metadata.get("filament_type") or metadata.get("filament_types") or []
    color_values = (
        metadata.get("filament_colour")
        or metadata.get("filament_color")
        or metadata.get("extruder_colour")
        or metadata.get("extruder_color")
        or []
    )

    def value_for(values: list[str], tool_id: int) -> str | None:
        if tool_id < len(values):
            value = values[tool_id].strip()
            return value if value and len(value) <= 32 else None
        if len(values) == 1:
            value = values[0].strip()
            return value if value and len(value) <= 32 else None
        return None

    def color_for(tool_id: int) -> str | None:
        raw = value_for(color_values, tool_id)
        if not raw:
            return None
        normalized = raw.strip()
        if normalized.lower().startswith("0x"):
            normalized = normalized[2:]
        normalized = normalized.removeprefix("#").upper()
        if re.fullmatch(r"[0-9A-F]{8}", normalized):
            normalized = normalized[-6:]
        return f"#{normalized}" if re.fullmatch(r"[0-9A-F]{6}", normalized) else None

    return [
        {
            "tool_id": tool_id,
            "material_name": value_for(material_values, tool_id),
            "tool_material_color": color_for(tool_id),
        }
        for tool_id in sorted(required_tools)
    ]


def extract_creator5_required_tools(file_path: Path, plate_id: int | None = None) -> set[int]:
    """Return the zero-based logical tool IDs actually evidenced by the file."""
    return {int(tool["tool_id"]) for tool in extract_creator5_tool_metadata(file_path, plate_id)}


def validate_creator5_mapping_completeness(mappings: list[dict], required_tool_ids: set[int]) -> None:
    """Require a one-to-one mapping for exactly the logical tools used by G-code."""
    mapped_tool_ids = {entry["toolId"] for entry in mappings}
    if mapped_tool_ids != required_tool_ids:
        required = ", ".join(str(tool_id) for tool_id in sorted(required_tool_ids))
        mapped = ", ".join(str(tool_id) for tool_id in sorted(mapped_tool_ids))
        raise ValueError(f"Creator 5 material mappings must match required G-code tools [{required}]; received [{mapped}]")
