"""Direct HTTP status and recent-file provider for FlashForge Creator 5."""

from __future__ import annotations

import json
import math
import re
import time
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from backend.app.services.bambu_mqtt import NozzleInfo, PrinterState
from backend.app.services.flashforge.http import FlashForgeHttpClient
from backend.app.services.flashforge.secrets import decrypt_check_code
from backend.app.services.printer_providers.flashforge_contract import (
    FLASHFORGE_CREATOR5_PROVIDER,
    contract_for,
    validate_flashforge_options,
)


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _safe_root_filename(value: Any) -> str:
    normalized = str(value or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.parent not in {PurePosixPath("."), PurePosixPath("/")}:
        raise ValueError("FlashForge Creator 5 only supports files in the printer root directory")
    name = path.name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("Invalid FlashForge filename")
    if PurePosixPath(name).suffix.lower() not in {".gcode", ".gx", ".g", ".3mf"}:
        raise ValueError("Unsupported FlashForge print file extension")
    return name


def _status(value: Any) -> str:
    raw = str(value or "unknown").strip()
    normalized = raw.lower().replace(" ", "_")
    return {
        "ready": "IDLE",
        "standby": "IDLE",
        "idle": "IDLE",
        "printing": "RUNNING",
        "running": "RUNNING",
        "paused": "PAUSE",
        "pause": "PAUSE",
        "complete": "FINISH",
        "completed": "FINISH",
        "finished": "FINISH",
        "finish": "FINISH",
        "error": "FAILED",
        "failed": "FAILED",
        "alarm": "FAILED",
    }.get(normalized, raw or "unknown")


def _recent_files(response: dict[str, Any]) -> list[str]:
    values = response.get("gcodeList")
    if isinstance(values, list):
        names = values
    else:
        values = response.get("gcodeListDetail")
        names = (
            [row.get("gcodeFileName") for row in values if isinstance(row, dict)] if isinstance(values, list) else []
        )
    return [str(name).strip() for name in names if str(name or "").strip()]


def _creator5_material_mappings(value: Any) -> list[dict[str, Any]] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not 2 <= len(value) <= 4:
        raise ValueError("Creator 5 material mappings require 2-4 entries")
    required = {"toolId", "slotId", "materialName", "toolMaterialColor", "slotMaterialColor"}
    mappings: list[dict[str, Any]] = []
    tool_ids: set[int] = set()
    slot_ids: set[int] = set()
    for entry in value:
        if not isinstance(entry, dict) or set(entry) != required:
            raise ValueError("Creator 5 material mapping has an invalid shape")
        tool_id = entry["toolId"]
        slot_id = entry["slotId"]
        material = entry["materialName"]
        if isinstance(tool_id, bool) or not isinstance(tool_id, int) or not 0 <= tool_id <= 3:
            raise ValueError("Creator 5 toolId must be between 0 and 3")
        if isinstance(slot_id, bool) or not isinstance(slot_id, int) or not 1 <= slot_id <= 4:
            raise ValueError("Creator 5 slotId must be between 1 and 4")
        if tool_id in tool_ids:
            raise ValueError("Creator 5 material mappings cannot repeat toolId")
        if slot_id in slot_ids:
            raise ValueError("Creator 5 material mappings cannot assign one slotId to multiple tools")
        if not isinstance(material, str) or not material.strip() or len(material) > 32:
            raise ValueError("Creator 5 materialName is invalid")
        for color_key in ("toolMaterialColor", "slotMaterialColor"):
            if not isinstance(entry[color_key], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", entry[color_key]):
                raise ValueError(f"Creator 5 {color_key} must be a six-digit hex color")
        tool_ids.add(tool_id)
        slot_ids.add(slot_id)
        mappings.append({**entry, "materialName": material.strip()})
    return sorted(mappings, key=lambda mapping: mapping["toolId"])


def _public_payload(value: Any) -> Any:
    if isinstance(value, dict):
        secret_keys = {"checkcode", "serialnumber", "serial_number", "auth_token", "access_code"}
        return {
            key: _public_payload(item)
            for key, item in value.items()
            if str(key).replace("-", "_").lower() not in secret_keys
        }
    if isinstance(value, list):
        return [_public_payload(item) for item in value]
    return value


class FlashForgeCreator5PrinterClient:
    """Creator 5 status, recent files, and verified temperature controls."""

    RECONCILE_ATTEMPTS = 4
    RECONCILE_INTERVAL_SECONDS = 0.35
    FILAMENT_MATERIALS = frozenset({
        "PLA", "PETG", "PLA-CF", "PETG-CF", "ABS", "ASA", "SILK", "PET-CF",
        "PAHT-CF", "S-PAHT", "S-Multi", "PA-CF", "HIPS", "PVA", "TPU-90A",
        "TPU-95A", "TPU-64D", "PC", "PA", "PC-ABS", "PPS-CF",
    })
    FILAMENT_COLORS = frozenset({
        "#FFFFFF", "#FFF245", "#DEF578", "#21CC3D", "#167A4B", "#156682",
        "#24E4A0", "#7BD9F0", "#4CAAF8", "#2E54DD", "#48358C", "#A341F7",
        "#F435F6", "#D5B4DE", "#FA6173", "#F82D29", "#805003", "#F9903B",
        "#FCEBD7", "#D5C5A1", "#B17C38", "#8C8C89", "#BEBEBE", "#1B1B1B",
    })

    def __init__(
        self,
        *,
        host: str,
        model: str,
        serial_number: str,
        check_code: str,
        http_port: int | None = None,
        camera_port: int | None = None,
        timeout: float = 8.0,
        on_state_change: Any | None = None,
        on_print_start: Any | None = None,
        on_print_complete: Any | None = None,
        on_bed_temp_update: Any | None = None,
        http_client: FlashForgeHttpClient | None = None,
    ) -> None:
        self.contract, self.model = contract_for(FLASHFORGE_CREATOR5_PROVIDER, model)
        options = validate_flashforge_options(
            FLASHFORGE_CREATOR5_PROVIDER,
            self.model,
            {
                key: value
                for key, value in {"http_port": http_port, "camera_port": camera_port}.items()
                if value is not None
            },
        )
        self.host = host
        self.camera_port = options["camera_port"]
        self.http_port = options["http_port"]
        self.http = http_client or FlashForgeHttpClient(
            host=host,
            provider=FLASHFORGE_CREATOR5_PROVIDER,
            model=self.model,
            serial_number=serial_number,
            check_code=check_code,
            http_port=self.http_port,
            timeout=timeout,
        )
        self.state = PrinterState()
        self.state.nozzles = [NozzleInfo() for _ in range(self.contract.tool_count)]
        self.state.active_extruder = -1
        self.on_state_change = on_state_change
        self.on_print_start = on_print_start
        self.on_print_complete = on_print_complete
        self.on_bed_temp_update = on_bed_temp_update
        self._last_state: str | None = None
        self._has_status_sample = False
        self._last_bed_temp: float | None = None

    def connect(self) -> None:
        try:
            self.request_status_update()
        except Exception:
            self.http.close()
            raise

    def disconnect(self, timeout: float = 0) -> None:  # noqa: ARG002
        self.state.connected = False
        self.http.close()

    def check_staleness(self) -> bool:
        try:
            self.request_status_update()
        except Exception:
            self.state.connected = False
        return self.state.connected

    def request_status_update(self) -> bool:
        previous = self._last_state if self._has_status_sample else None
        try:
            response = self.http.detail()
            detail = response.get("detail")
            if not isinstance(detail, dict):
                raise ValueError("FlashForge detail response did not include printer status")
            self._apply_detail(detail, response)
            self.state.connected = True
            self._emit_status(previous)
            self._last_state = self.state.state
            self._has_status_sample = True
            return True
        except Exception:
            self.state.connected = False
            raise

    def _apply_detail(self, detail: dict[str, Any], response: dict[str, Any]) -> None:
        self.state.raw_status = _public_payload(detail)
        self.state.raw_data = {
            "detail": _public_payload(detail),
            "response": _public_payload({key: value for key, value in response.items() if key != "detail"}),
        }
        self.state.state = _status(detail.get("status"))
        self.state.firmware_version = str(detail.get("firmwareVersion") or "") or None
        filename = str(detail.get("printFileName") or "").strip() or None
        self.state.gcode_file = filename
        self.state.current_print = filename if self.state.state in {"RUNNING", "PAUSE"} else None
        self.state.subtask_name = filename
        progress = _number(detail.get("printProgress"))
        self.state.progress = (
            min(100.0, max(0.0, progress * (100 if progress <= 1 else 1))) if progress is not None else 0.0
        )
        self.state.layer_num = int(_number(detail.get("printLayer")) or 0)
        self.state.total_layers = int(_number(detail.get("targetPrintLayer")) or 0)
        estimated = _number(detail.get("estimatedTime"))
        self.state.remaining_time = max(0, int(math.ceil(estimated / 60))) if estimated is not None else 0

        temps = detail.get("nozzleTemps") if isinstance(detail.get("nozzleTemps"), list) else []
        targets = detail.get("nozzleTargetTemps") if isinstance(detail.get("nozzleTargetTemps"), list) else []
        if not temps:
            temps = [detail.get("rightTemp")]
        if not targets:
            targets = [detail.get("rightTargetTemp")]
        nozzle_temperatures: dict[str, Any] = {}
        active_candidates = []
        for index in range(self.contract.tool_count):
            suffix = "" if index == 0 else f"_{index + 1}"
            actual = _number(temps[index]) if index < len(temps) else None
            target = _number(targets[index]) if index < len(targets) else None
            if actual is not None:
                nozzle_temperatures[f"nozzle{suffix}"] = actual
            if target is not None:
                nozzle_temperatures[f"nozzle{suffix}_target"] = target
                if target > 0:
                    active_candidates.append(index)
            if actual is not None and target is not None:
                nozzle_temperatures[f"nozzle{suffix}_heating"] = target > actual + 1
        self.state.temperatures = nozzle_temperatures
        self.state.active_extruder = active_candidates[0] if len(active_candidates) == 1 else -1

        bed = _number(detail.get("platTemp"))
        bed_target = _number(detail.get("platTargetTemp"))
        if bed is not None:
            self.state.temperatures["bed"] = bed
        if bed_target is not None:
            self.state.temperatures["bed_target"] = bed_target
        if bed is not None and bed_target is not None:
            self.state.temperatures["bed_heating"] = bed_target > bed + 1

        material = detail.get("matlStationInfo")
        current_slot = detail.get("currentSlot")
        if current_slot is None and isinstance(material, dict):
            current_slot = material.get("currentSlot")
        self.state.raw_data["creator5_material_station"] = {
            "current_slot": current_slot,
            "slot_infos": material.get("slotInfos", []) if isinstance(material, dict) else detail.get("slotInfos", []),
        }
        self.state.cooling_fan_speed = _optional_int(detail.get("coolingFanSpeed", detail.get("coolingFan")))
        self.state.big_fan1_speed = _optional_int(detail.get("chamberFanSpeed", detail.get("chamberFan")))
        if self.model == "Creator 5 Pro":
            chamber = _number(detail.get("chamberTemp"))
            chamber_target = _number(detail.get("chamberTargetTemp"))
            if chamber is not None:
                self.state.temperatures["chamber"] = chamber
            if chamber_target is not None:
                self.state.temperatures["chamber_target"] = chamber_target
            if chamber is not None and chamber_target is not None:
                self.state.temperatures["chamber_heating"] = chamber_target > chamber + 1
        self.state.ipcam = bool(detail.get("cameraStreamUrl"))

    def _emit_status(self, previous: str | None) -> None:
        if self.on_state_change:
            self.on_state_change(self.state)
        bed = self.state.temperatures.get("bed")
        if isinstance(bed, int | float) and bed != self._last_bed_temp:
            self._last_bed_temp = float(bed)
            if self.on_bed_temp_update:
                self.on_bed_temp_update(float(bed))
        current = self.state.state
        if (
            previous is not None
            and previous not in {"RUNNING", "PAUSE"}
            and current == "RUNNING"
            and self.on_print_start
        ):
            self.on_print_start(self._lifecycle_payload())
        elif previous in {"RUNNING", "PAUSE"} and current not in {"RUNNING", "PAUSE"} and self.on_print_complete:
            payload = self._lifecycle_payload()
            payload["status"] = "completed" if current == "FINISH" else "failed" if current == "FAILED" else "stopped"
            self.on_print_complete(payload)

    def _lifecycle_payload(self) -> dict[str, Any]:
        return {
            "filename": self.state.gcode_file or "Unknown",
            "subtask_name": self.state.gcode_file or "Unknown",
            "progress": self.state.progress,
            "remaining_time": self.state.remaining_time * 60 if self.state.remaining_time else None,
            "status": self.state.state,
        }

    def set_nozzle_temperature(self, target: int, extruder: int = 0) -> bool:
        if not 0 <= extruder < self.contract.tool_count:
            raise ValueError("Creator 5 nozzle index must be 0-3")
        if not 0 <= target <= self.contract.nozzle_max_c:
            raise ValueError(f"Nozzle temperature must be 0-{self.contract.nozzle_max_c}°C")
        args = {"nozzles": [-200] * self.contract.tool_count}
        args["nozzles"][extruder] = target
        return self._set_temperature(args, f"nozzle{'' if extruder == 0 else f'_{extruder + 1}'}_target", target)

    def set_bed_temperature(self, target: int) -> bool:
        if not 0 <= target <= self.contract.bed_max_c:
            raise ValueError(f"Bed temperature must be 0-{self.contract.bed_max_c}°C")
        return self._set_temperature({"platform": target}, "bed_target", target)

    def set_chamber_temperature(self, target: int) -> bool:
        maximum = self.contract.chamber_max_c
        if maximum is None:
            raise ValueError("Chamber temperature control is only supported by Creator 5 Pro")
        if not 0 <= target <= maximum:
            raise ValueError(f"Chamber temperature must be 0-{maximum}°C for Creator 5 Pro")
        return self._set_temperature({"chamber": target}, "chamber_target", target)

    def activate_camera(self) -> str | None:
        try:
            self.request_status_update()
        except Exception:
            return None
        if self.state.state not in {"IDLE", "RUNNING", "PAUSE", "FINISH"}:
            return None

        command_accepted = False
        try:
            self.http.control("streamCtrl_cmd", {"action": "open"})
            command_accepted = True
        except Exception:
            pass

        try:
            self.request_status_update()
        except Exception:
            return self._fallback_camera_url() if command_accepted else None

        camera_url = self._validated_status_camera_url()
        if camera_url:
            return camera_url
        return self._fallback_camera_url() if command_accepted else None

    def _validated_status_camera_url(self) -> str | None:
        value = str(self.state.raw_status.get("cameraStreamUrl") or "").strip()
        if not value:
            return None
        try:
            parsed = urlsplit(value)
            host = parsed.hostname
            port = parsed.port or (80 if parsed.scheme == "http" else 443 if parsed.scheme == "https" else None)
            expected_host = urlsplit(f"//{self.host}").hostname
        except ValueError:
            return None
        if (
            parsed.scheme != "http"
            or not host
            or host.lower() != str(expected_host or "").lower()
            or port != self.camera_port
            or not parsed.path.startswith("/")
            or parsed.username is not None
            or parsed.password is not None
        ):
            return None
        return value

    def _fallback_camera_url(self) -> str:
        host = str(urlsplit(f"//{self.host}").hostname or self.host).strip("[]")
        if ":" in host:
            host = f"[{host}]"
        return f"http://{host}:{self.camera_port}/?action=stream"

    def set_filament_config(
        self,
        tool_index: int,
        *,
        material: str | None = None,
        color: str | None = None,
    ) -> bool:
        if not 0 <= tool_index < self.contract.tool_count:
            raise ValueError("Creator 5 tool index must be 0-3")
        if material is None and color is None:
            raise ValueError("Choose a filament material, color, or both")
        try:
            self.request_status_update()
        except Exception:
            return False
        if self.state.state != "IDLE":
            raise ValueError("Creator 5 filament configuration can only be changed while the printer is idle")

        slot = self._material_slot(tool_index)
        current_material = _clean_text(slot.get("materialName", slot.get("materialType", slot.get("mt"))))
        current_color = _clean_text(slot.get("materialColor", slot.get("color", slot.get("rgb"))))
        selected_material = (
            self._allowlisted_value(material, self.FILAMENT_MATERIALS) if material is not None else current_material
        )
        selected_color = (
            self._allowlisted_value(color, self.FILAMENT_COLORS, upper=True) if color is not None else current_color
        )
        if selected_material is None:
            raise ValueError("Choose a supported Creator 5 filament type")
        if selected_color is None:
            raise ValueError("Choose a supported Creator 5 filament color")

        try:
            self.http.control("msConfig_cmd", {"slot": tool_index + 1, "mt": selected_material, "rgb": selected_color})
        except Exception:
            pass

        for attempt in range(3):
            if attempt:
                time.sleep(0.2 * attempt)
            try:
                self.request_status_update()
            except Exception:
                continue
            observed = self._material_slot(tool_index)
            observed_material = _clean_text(
                observed.get("materialName", observed.get("materialType", observed.get("mt")))
            )
            observed_color = _clean_text(
                observed.get("materialColor", observed.get("color", observed.get("rgb")))
            )
            if (
                observed_material is not None
                and observed_material.casefold() == selected_material.casefold()
                and observed_color is not None
                and observed_color.upper() == selected_color.upper()
            ):
                return True
        return False

    @staticmethod
    def _allowlisted_value(value: str, allowed: frozenset[str], *, upper: bool = False) -> str | None:
        candidate = str(value).strip()
        if upper:
            candidate = candidate.upper()
        return next((item for item in allowed if item.upper() == candidate.upper()), None)

    def _material_slot(self, tool_index: int) -> dict[str, Any]:
        slots = self.state.raw_data.get("creator5_material_station", {}).get("slot_infos", [])
        if not isinstance(slots, list):
            return {}
        for array_index, slot in enumerate(slots):
            if not isinstance(slot, dict):
                continue
            try:
                slot_id = int(slot.get("slotId", slot.get("slot", array_index + 1)))
            except (TypeError, ValueError):
                continue
            if slot_id == tool_index + 1:
                return slot
        return {}

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        if kwargs.get("storage"):
            raise ValueError("FlashForge Creator 5 does not expose selectable file storage")
        if kwargs.get("ams_mapping") is not None or kwargs.get("print_platform_type") is not None:
            raise ValueError("FlashForge Creator 5 tool mapping is unavailable for printer-local files")
        material_mappings = _creator5_material_mappings(kwargs.get("creator5_material_mappings"))
        target = _safe_root_filename(filename)
        try:
            self.request_status_update()
        except Exception:
            return False
        if self.state.state not in {"IDLE", "FINISH", "FAILED"}:
            return False
        try:
            files = self.list_files()
        except Exception:
            return False
        if not any(_safe_root_filename(entry.get("name", "")).casefold() == target.casefold() for entry in files):
            return False

        try:
            options: dict[str, Any] = {
                "levelingBeforePrint": bool(kwargs.get("bed_levelling", True)),
                "flowCalibration": bool(kwargs.get("flow_cali", False)),
                "timeLapseVideo": bool(kwargs.get("timelapse", False)),
            }
            if material_mappings is not None:
                options["materialMappings"] = material_mappings
            self.http.print_gcode(target, **options)
        except Exception:
            pass
        return self._reconcile_print_state("RUNNING", target)

    def pause_print(self) -> bool:
        return self._job_action("pause", allowed={"RUNNING"}, expected={"PAUSE"})

    def resume_print(self) -> bool:
        return self._job_action("continue", allowed={"PAUSE"}, expected={"RUNNING"})

    def stop_print(self) -> bool:
        return self._job_action("cancel", allowed={"RUNNING", "PAUSE"}, expected={"IDLE", "FINISH", "FAILED"})

    def _job_action(self, action: str, *, allowed: set[str], expected: set[str]) -> bool:
        try:
            self.request_status_update()
        except Exception:
            return False
        if self.state.state not in allowed:
            return False
        try:
            self.http.control("jobCtl_cmd", {"jobID": "", "action": action})
        except Exception:
            pass
        for attempt in range(self.RECONCILE_ATTEMPTS):
            if attempt:
                time.sleep(self.RECONCILE_INTERVAL_SECONDS)
            try:
                self.request_status_update()
            except Exception:
                continue
            if self.state.state in expected:
                return True
        return False

    def _reconcile_print_state(self, expected_state: str, filename: str) -> bool:
        for attempt in range(self.RECONCILE_ATTEMPTS):
            if attempt:
                time.sleep(self.RECONCILE_INTERVAL_SECONDS)
            try:
                self.request_status_update()
            except Exception:
                continue
            if self.state.state == expected_state and (self.state.gcode_file or "").casefold() == filename.casefold():
                return True
        return False

    def _set_temperature(self, args: dict[str, Any], status_key: str, target: int) -> bool:
        try:
            self.request_status_update()
        except Exception:
            return False
        if self.state.state not in {"IDLE", "RUNNING", "PAUSE", "FINISH"}:
            return False
        try:
            self.http.control("temperatureCtl_cmd", args)
        except Exception:
            pass

        for attempt in range(self.RECONCILE_ATTEMPTS):
            try:
                self.request_status_update()
            except Exception:
                return False
            observed = _number(self.state.temperatures.get(status_key))
            if observed is not None and abs(observed - target) <= 0.5:
                return True
            if attempt + 1 < self.RECONCILE_ATTEMPTS:
                time.sleep(self.RECONCILE_INTERVAL_SECONDS)
        return False

    def list_files(self, path: str = "/", *, storage: str | None = None) -> list[dict[str, Any]]:
        parts = [part for part in PurePosixPath(str(path or "/").replace("\\", "/")).parts if part not in {"/", "."}]
        if parts:
            raise ValueError("FlashForge Creator 5 only exposes the printer root file list")
        if storage:
            raise ValueError("FlashForge Creator 5 does not expose selectable file storage")
        self.state.raw_data.pop("file_listing", None)
        response = self.http.gcode_list()
        self.state.raw_data["file_listing"] = {"complete": False, "source": "http-recent"}
        return [
            {"name": name, "type": "file", "size": None, "modified": None, "path": f"/{name}"}
            for name in _recent_files(response)
        ]

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        *,
        overwrite: bool = False,  # noqa: ARG002 - conflict policy is enforced by the route before upload
        storage: str | None = None,
        tool_count: int = 1,
    ) -> bool:
        if storage:
            raise ValueError("FlashForge Creator 5 does not expose selectable file storage")
        if not 1 <= tool_count <= self.contract.tool_count:
            raise ValueError("Creator 5 upload tool_count must be 1-4")
        filename = _safe_root_filename(remote_path)
        self.http.upload_gcode(
            local_path,
            remote_filename=filename,
            leveling_before_print=False,
            extra_headers={
                "useMatlStation": "true",
                "gcodeToolCnt": str(tool_count),
                "flowCalibration": "false",
                "timeLapseVideo": "false",
            },
        )
        return True

    def download_file(self, remote_path: str) -> bytes | None:  # noqa: ARG002
        return None

    def delete_file(self, remote_path: str, *, storage: str | None = None) -> bool:  # noqa: ARG002
        return False


def _optional_int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def create_flashforge_creator5_client(printer: Any, **callbacks: Any) -> FlashForgeCreator5PrinterClient:
    raw_options = getattr(printer, "provider_options", None)
    options = json.loads(raw_options) if isinstance(raw_options, str) and raw_options else raw_options or {}
    if not isinstance(options, dict):
        raise ValueError("FlashForge provider_options must be an object")
    return FlashForgeCreator5PrinterClient(
        host=getattr(printer, "ip_address", ""),
        model=getattr(printer, "model", None),
        serial_number=getattr(printer, "serial_number", ""),
        check_code=decrypt_check_code(getattr(printer, "auth_token", None)),
        http_port=options.get("http_port"),
        camera_port=options.get("camera_port"),
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
