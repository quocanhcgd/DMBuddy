"""Pure FlashForge response normalization helpers."""

from __future__ import annotations

import re

_PRINTABLE_EXTENSIONS = (".gcode", ".gx", ".g", ".3mf")


def parse_m661_file_list(response: str | bytes | None) -> list[str]:
    """Parse modern delimiter responses and legacy line-based M661 listings."""

    if isinstance(response, bytes):
        text = response.decode("utf-8", errors="replace")
    else:
        text = str(response or "")

    files: list[str] = []
    seen: set[str] = set()

    def add(value: str) -> None:
        candidate = value.replace("\0", "").strip()
        candidate = re.sub(r"^/data/", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^0:/user/", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"^/data/user/", "", candidate, flags=re.IGNORECASE).strip()
        if not candidate or not candidate.lower().endswith(_PRINTABLE_EXTENSIONS) or candidate in seen:
            return
        seen.add(candidate)
        files.append(candidate)

    for segment in text.split("::"):
        data_index = segment.find("/data/")
        if data_index < 0:
            continue
        tail = segment[data_index:]
        add(re.split(r"[\r\n\0]", tail, maxsplit=1)[0])

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if (
            not line
            or "::" in line
            or line.lower() == "ok"
            or re.fullmatch(r"CMD\s+M661\s+Received\.?", line, flags=re.IGNORECASE)
            or re.match(r"^info_list\.size\s*:", line, flags=re.IGNORECASE)
        ):
            continue
        add(line)

    return files


def normalize_creator5_material_slots(value: object) -> list[dict[str, int | str]]:
    """Expose only the four bounded material fields needed by queue mapping."""
    if not isinstance(value, list):
        return []
    slots: list[dict[str, int | str]] = []
    seen: set[int] = set()
    for entry in value[:4]:
        if not isinstance(entry, dict):
            continue
        slot_id = entry.get("slotId")
        material = entry.get("materialName")
        color = entry.get("materialColor")
        if (
            isinstance(slot_id, int)
            and not isinstance(slot_id, bool)
            and 1 <= slot_id <= 4
            and slot_id not in seen
            and isinstance(material, str)
            and 0 < len(material.strip()) <= 32
            and isinstance(color, str)
            and re.fullmatch(r"#[0-9A-Fa-f]{6}", color.strip())
        ):
            slots.append({"slot_id": slot_id, "material_name": material.strip(), "material_color": color.strip().upper()})
            seen.add(slot_id)
    return sorted(slots, key=lambda slot: int(slot["slot_id"]))
