import pytest
from pydantic import ValidationError

from backend.app.schemas.print_queue import PrintQueueItemCreate


def _mapping(tool_id: int, slot_id: int) -> dict:
    return {
        "toolId": tool_id,
        "slotId": slot_id,
        "materialName": "PLA",
        "toolMaterialColor": "#FFFFFF",
        "slotMaterialColor": "#FFFFFF",
    }


def test_creator5_queue_mapping_accepts_upstream_shape_and_keeps_tool_slot_indices_distinct():
    item = PrintQueueItemCreate(
        printer_id=1,
        archive_id=10,
        creator5_material_mappings=[_mapping(0, 3), _mapping(1, 1)],
    )

    assert [entry.model_dump(by_alias=True) for entry in item.creator5_material_mappings] == [
        _mapping(0, 3),
        _mapping(1, 1),
    ]


@pytest.mark.parametrize(
    "mappings",
    [
        [_mapping(0, 1)],
        [_mapping(0, 1), _mapping(0, 2)],
        [_mapping(0, 1), _mapping(1, 1)],
        [_mapping(0, 0), _mapping(1, 2)],
        [_mapping(0, 1), {**_mapping(1, 2), "extra": True}],
    ],
)
def test_creator5_queue_mapping_rejects_incomplete_duplicate_or_out_of_contract_data(mappings):
    with pytest.raises(ValidationError):
        PrintQueueItemCreate(archive_id=10, creator5_material_mappings=mappings)


def test_creator5_mapping_cannot_be_combined_with_bambu_ams_mapping():
    with pytest.raises(ValidationError, match="cannot be combined"):
        PrintQueueItemCreate(
            archive_id=10,
            ams_mapping=[1, 2],
            creator5_material_mappings=[_mapping(0, 1), _mapping(1, 2)],
        )
