"""Read-only catalog of Creality Print presets bundled with the application."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/creality-profiles", tags=["Creality Profiles"])
PROFILE_ROOT = Path(__file__).resolve().parents[3] / "data" / "creality-profiles"
KINDS = {"printer": "machine", "process": "process", "filament": "filament"}


@lru_cache(maxsize=1)
def _catalog() -> dict[str, list[dict]]:
    catalog: dict[str, list[dict]] = {kind: [] for kind in KINDS}
    for public_kind, directory in KINDS.items():
        root = PROFILE_ROOT / directory
        for path in sorted(root.glob("*.json")):
            try:
                setting = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            name = str(setting.get("name") or path.stem)
            catalog[public_kind].append({
                "id": f"{public_kind}:{path.name}",
                "name": name,
                "inherits": setting.get("inherits"),
                "printer": _printer_name(name, setting),
                "nozzles": _nozzles(setting),
                "setting": setting,
            })
    return catalog


def _printer_name(name: str, setting: dict) -> str | None:
    printer_model = str(setting.get("printer_model") or "").strip()
    if printer_model:
        return re.sub(r"^Creality\s+", "", printer_model, flags=re.IGNORECASE)

    for value in (name, str(setting.get("inherits") or "")):
        if "@Creality " in value:
            printer = value.split("@Creality ", 1)[1].strip()
            return re.sub(r"\s+\d+(?:\.\d+)?(?:\s*mm)?(?:\s+nozzle)?$", "", printer, flags=re.IGNORECASE)
        if "@SPARKX " in value:
            printer = "SPARKX " + value.split("@SPARKX ", 1)[1].strip()
            return re.sub(r"\s+\d+(?:\.\d+)?(?:\s*mm)?(?:\s+nozzle)?$", "", printer, flags=re.IGNORECASE)
        if value.startswith("Creality "):
            printer = value.removeprefix("Creality ").removesuffix(" model").strip()
            return re.sub(r"\s+\d+(?:\.\d+)?(?:\s*mm)?(?:\s+nozzle)?$", "", printer, flags=re.IGNORECASE)
    return None


def _nozzles(setting: dict) -> list[str]:
    values = setting.get("nozzle_diameter", [])
    if not isinstance(values, list):
        values = [values]
    return sorted({str(value) for value in values if value not in (None, "")})


@router.get("")
async def list_creality_profiles(
    kind: str | None = Query(None, pattern="^(printer|process|filament)$"),
    printer: str | None = None,
    nozzle: str | None = None,
    search: str | None = None,
):
    catalog = _catalog()
    kinds = [kind] if kind else list(KINDS)
    profiles = [item for selected in kinds for item in catalog[selected]]
    if printer:
        profiles = [item for item in profiles if (item["printer"] or "").casefold() == printer.casefold()]
    if nozzle:
        profiles = [item for item in profiles if nozzle in item["nozzles"]]
    if search:
        term = search.casefold()
        profiles = [item for item in profiles if term in item["name"].casefold() or term in str(item["printer"] or "").casefold()]
    printers = sorted({item["printer"] for entries in catalog.values() for item in entries if item["printer"]})
    return {
        "profiles": [{key: value for key, value in item.items() if key != "setting"} for item in profiles],
        "printers": printers,
        "counts": {selected: len(catalog[selected]) for selected in KINDS},
        "license": "AGPL-3.0",
        "source": "https://github.com/CrealityOfficial/CrealityPrint",
    }


@router.get("/detail")
async def get_creality_profile(
    profile_id: str,
):
    for entries in _catalog().values():
        for item in entries:
            if item["id"] == profile_id:
                return item
    raise HTTPException(404, "Creality profile not found")
