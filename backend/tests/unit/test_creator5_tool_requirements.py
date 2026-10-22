from zipfile import ZipFile

import pytest
from pydantic import ValidationError

from backend.app.schemas.printer import PrinterStatus
from backend.app.services.flashforge.creator5_tool_requirements import (
    extract_creator5_required_tools,
    extract_creator5_tool_metadata,
    validate_creator5_mapping_completeness,
)
from backend.app.services.flashforge.normalize import normalize_creator5_material_slots


def _write_3mf(path, entries):
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path


def test_extracts_explicit_tool_commands_and_ignores_comments(tmp_path):
    source = tmp_path / "tools.gcode"
    source.write_text("; T3 is only a comment\nG1 X10 ; T2\nT0\nN42 T1\n", encoding="utf-8")

    assert extract_creator5_required_tools(source) == {0, 1}


def test_extracts_tool_indices_from_positive_filament_usage_metadata(tmp_path):
    source = tmp_path / "tools.gcode"
    source.write_text("; filament used [g] = 1.2, 0, 3.4\n", encoding="utf-8")

    assert extract_creator5_required_tools(source) == {0, 2}


def test_unions_explicit_commands_with_positive_usage_metadata(tmp_path):
    source = tmp_path / "tools.gcode"
    source.write_text("; filament used [g] = 1.2, 0, 3.4\nT0\n", encoding="utf-8")

    assert extract_creator5_required_tools(source) == {0, 2}


def test_uses_single_tool_metadata_as_reliable_zero_tool_fallback(tmp_path):
    source = tmp_path / "single.gcode"
    source.write_text("; filament_type = PLA\n", encoding="utf-8")

    assert extract_creator5_required_tools(source) == {0}


def test_extracts_tool_material_and_color_by_logical_tool_index(tmp_path):
    source = tmp_path / "materials.gcode"
    source.write_text(
        "; filament_type = PLA;PETG\n; filament_colour = #F82D29;0x167A4B\nT0\nT1\n",
        encoding="utf-8",
    )

    assert extract_creator5_tool_metadata(source) == [
        {"tool_id": 0, "material_name": "PLA", "tool_material_color": "#F82D29"},
        {"tool_id": 1, "material_name": "PETG", "tool_material_color": "#167A4B"},
    ]


def test_material_slot_normalizer_exposes_only_valid_slots_and_fields():
    raw = [
        {"slotId": 2, "materialName": " PETG ", "materialColor": "#00aa11", "serialNumber": "secret"},
        {"slotId": 2, "materialName": "PLA", "materialColor": "#FFFFFF"},
        {"slotId": 5, "materialName": "ABS", "materialColor": "#000000"},
        {"slotId": 1, "materialName": "Unknown", "materialColor": "red"},
    ]

    assert normalize_creator5_material_slots(raw) == [
        {"slot_id": 2, "material_name": "PETG", "material_color": "#00AA11"},
    ]


def test_creator5_material_slots_status_schema_enforces_safe_values():
    response = PrinterStatus(
        id=1,
        name="Creator 5",
        connected=True,
        creator5_material_slots=[{"slot_id": 1, "material_name": "PLA", "material_color": "#FFFFFF"}],
    )
    assert response.creator5_material_slots[0].slot_id == 1

    with pytest.raises(ValidationError):
        PrinterStatus(
            id=1,
            name="Creator 5",
            connected=True,
            creator5_material_slots=[{"slot_id": 5, "material_name": "PLA", "material_color": "red"}],
        )


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("T4\n", "outside tool IDs 0-3"),
        ("; filament_type = PLA;PETG\n", "ambiguous tool usage"),
        ("G1 X1\n", "no readable logical tool usage"),
    ],
)
def test_rejects_out_of_range_or_ambiguous_tool_use(tmp_path, content, message):
    source = tmp_path / "invalid.gcode"
    source.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        extract_creator5_required_tools(source)


def test_selects_the_requested_1_based_plate_from_3mf(tmp_path):
    source = _write_3mf(
        tmp_path / "plates.3mf",
        {
            "Metadata/plate_1.gcode": "T0\n",
            "Metadata/plate_2.gcode": "T1\nT2\n",
        },
    )

    assert extract_creator5_required_tools(source, plate_id=1) == {0}
    assert extract_creator5_required_tools(source, plate_id=2) == {1, 2}
    with pytest.raises(ValueError, match="select a plate"):
        extract_creator5_required_tools(source)


def test_rejects_plate_entry_above_16_mib(tmp_path):
    source = _write_3mf(
        tmp_path / "large.3mf",
        {"Metadata/plate_1.gcode": b"T0\n" + b";" * (16 * 1024 * 1024)},
    )

    with pytest.raises(ValueError, match="16 MiB"):
        extract_creator5_required_tools(source, plate_id=1)


def test_mapping_must_cover_exactly_the_required_gcode_tools():
    mappings = [{"toolId": 0}, {"toolId": 2}]

    validate_creator5_mapping_completeness(mappings, {0, 2})
    with pytest.raises(ValueError, match="must match required G-code tools"):
        validate_creator5_mapping_completeness(mappings, {0, 1, 2})
    with pytest.raises(ValueError, match="must match required G-code tools"):
        validate_creator5_mapping_completeness([{"toolId": 0}, {"toolId": 1}], {0})
