"""Direct FlashForge Adventurer 5M family provider.

Status field names follow the Print-Farm-Controller adapter and remain subject
to verification against physical printer firmware.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlsplit

from backend.app.services.bambu_mqtt import NozzleInfo, PrintOptions
from backend.app.services.flashforge.errors import FlashForgeTransportError
from backend.app.services.flashforge.http import FlashForgeHttpClient, _safe_filename
from backend.app.services.flashforge.normalize import parse_m661_file_list
from backend.app.services.flashforge.secrets import decrypt_check_code
from backend.app.services.flashforge.tcp import FlashForgeTcpClient
from backend.app.services.printer_providers.flashforge_contract import (
    FLASHFORGE_AD5M_PROVIDER,
    contract_for,
    validate_flashforge_options,
)


@dataclass
class FlashForgePrinterState:
    connected: bool = False
    state: str = "unknown"
    current_print: str | None = None
    subtask_name: str | None = None
    progress: float = 0.0
    remaining_time: int = 0
    layer_num: int = 0
    total_layers: int = 0
    temperatures: dict[str, Any] = field(default_factory=dict)
    raw_status: dict[str, Any] = field(default_factory=dict)
    raw_data: dict[str, Any] = field(default_factory=dict)
    gcode_file: str | None = None
    subtask_id: str | None = None
    hms_errors: list[Any] = field(default_factory=list)
    kprofiles: list[Any] = field(default_factory=list)
    sdcard: bool = False
    store_to_sdcard: bool = False
    timelapse: bool = False
    ipcam: bool = False
    wifi_signal: int | None = None
    wired_network: bool = False
    door_open: bool = False
    nozzles: list[Any] = field(default_factory=lambda: [NozzleInfo()])
    print_options: PrintOptions = field(default_factory=PrintOptions)
    stg_cur: int = -1
    stg: list[int] = field(default_factory=list)
    airduct_mode: int = 0
    speed_level: int = 2
    chamber_light: bool = False
    active_extruder: int = 0
    tray_now: int = 255
    last_loaded_tray: int = -1
    ams_status_main: int = 0
    ams_status_sub: int = 0
    mc_print_sub_stage: int = 0
    ams_mapping: list[Any] = field(default_factory=list)
    ams_extruder_map: dict[str, int] = field(default_factory=dict)
    last_ams_update: float = 0.0
    printable_objects: dict[str, str] = field(default_factory=dict)
    skipped_objects: list[Any] = field(default_factory=list)
    cooling_fan_speed: int | None = None
    big_fan1_speed: int | None = None
    big_fan2_speed: int | None = None
    heatbreak_fan_speed: int | None = None
    tray_change_log: list[Any] = field(default_factory=list)
    firmware_version: str | None = None
    developer_mode: bool | None = None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _map_state(value: Any) -> str:
    raw = str(value or "unknown").strip()
    normalized = raw.lower().replace(" ", "_")
    return {
        "ready": "IDLE",
        "idle": "IDLE",
        "printing": "RUNNING",
        "running": "RUNNING",
        "paused": "PAUSE",
        "pause": "PAUSE",
        "finished": "FINISH",
        "finish": "FINISH",
        "complete": "FINISH",
        "completed": "FINISH",
        "error": "FAILED",
        "failed": "FAILED",
        "alarm": "FAILED",
    }.get(normalized, raw or "unknown")


def _detail_payload(response: dict[str, Any]) -> dict[str, Any]:
    detail = response.get("detail")
    if not isinstance(detail, dict):
        raise FlashForgeTransportError("FlashForge detail response did not include printer status")
    return detail


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


class FlashForgeAd5mPrinterClient:
    """Synchronous AD5M provider used by PrinterManager's provider boundary."""

    RECONCILE_ATTEMPTS = 4
    RECONCILE_INTERVAL_SECONDS = 0.35

    def __init__(
        self,
        *,
        host: str,
        model: str,
        serial_number: str,
        check_code: str,
        http_port: int | None = None,
        camera_port: int | None = None,
        tcp_port: int | None = None,
        timeout: float = 8.0,
        on_state_change: Any | None = None,
        on_print_start: Any | None = None,
        on_print_complete: Any | None = None,
        on_bed_temp_update: Any | None = None,
        http_client: FlashForgeHttpClient | None = None,
        tcp_client: FlashForgeTcpClient | None = None,
    ) -> None:
        self.contract, self.model = contract_for(FLASHFORGE_AD5M_PROVIDER, model)
        options = validate_flashforge_options(
            FLASHFORGE_AD5M_PROVIDER,
            self.model,
            {
                key: value
                for key, value in {
                    "http_port": http_port,
                    "camera_port": camera_port,
                    "tcp_port": tcp_port,
                }.items()
                if value is not None
            },
        )
        self.host = host
        self.camera_port = options["camera_port"]
        self.serial_number = str(serial_number).strip()
        self.http = http_client or FlashForgeHttpClient(
            host=host,
            provider=FLASHFORGE_AD5M_PROVIDER,
            model=self.model,
            serial_number=self.serial_number,
            check_code=check_code,
            http_port=options["http_port"],
            timeout=timeout,
        )
        self.tcp = tcp_client or FlashForgeTcpClient(
            host=host, provider=FLASHFORGE_AD5M_PROVIDER, model=self.model, port=options["tcp_port"]
        )
        self.http_port = options["http_port"]
        self.tcp_port = options["tcp_port"]
        self.state = FlashForgePrinterState()
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
            detail = _detail_payload(response)
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
        safe_detail = _public_payload(detail)
        self.state.raw_status = safe_detail
        self.state.raw_data = {"detail": safe_detail, "response": _public_payload({key: value for key, value in response.items() if key != "detail"})}
        self.state.state = _map_state(detail.get("status"))
        self.state.firmware_version = str(detail.get("firmwareVersion") or "") or None
        filename = str(detail.get("printFileName") or "").strip() or None
        self.state.gcode_file = filename
        self.state.current_print = filename if self.state.state in {"RUNNING", "PAUSE"} else None
        self.state.subtask_name = filename
        self.state.progress = min(100.0, max(0.0, (_number(detail.get("printProgress")) or 0.0) * (100 if (_number(detail.get("printProgress")) or 0) <= 1 else 1)))
        self.state.layer_num = int(_number(detail.get("printLayer")) or 0)
        self.state.total_layers = int(_number(detail.get("targetPrintLayer")) or 0)
        estimated = _number(detail.get("estimatedTime"))
        self.state.remaining_time = max(0, int(math.ceil(estimated / 60))) if estimated is not None else 0
        nozzle = _number(detail.get("rightTemp"))
        nozzle_target = _number(detail.get("rightTargetTemp"))
        bed = _number(detail.get("platTemp"))
        bed_target = _number(detail.get("platTargetTemp"))
        self.state.temperatures = {
            **({"nozzle": nozzle} if nozzle is not None else {}),
            **({"nozzle_target": nozzle_target} if nozzle_target is not None else {}),
            **({"nozzle_heating": nozzle_target > nozzle + 1} if nozzle is not None and nozzle_target is not None else {}),
            **({"bed": bed} if bed is not None else {}),
            **({"bed_target": bed_target} if bed_target is not None else {}),
            **({"bed_heating": bed_target > bed + 1} if bed is not None and bed_target is not None else {}),
        }
        self.state.cooling_fan_speed = _optional_int(detail.get("coolingFanSpeed", detail.get("coolingFan")))
        self.state.big_fan1_speed = _optional_int(detail.get("chamberFanSpeed", detail.get("chamberFan")))
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
        if previous is not None and previous not in {"RUNNING", "PAUSE"} and current == "RUNNING" and self.on_print_start:
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

    def list_files(self, path: str = "/", *, storage: str | None = None) -> list[dict[str, Any]]:  # noqa: ARG002
        if _is_nested_remote_path(path):
            raise ValueError("FlashForge AD5M only supports the printer root directory")
        if storage:
            raise ValueError("FlashForge AD5M does not expose selectable file storage")
        self.state.raw_data.pop("file_listing", None)
        try:
            names = parse_m661_file_list(self.tcp.list_files_raw())
            complete = True
            source = "tcp-m661"
        except Exception:
            response = self.http.gcode_list()
            names = _recent_files(response)
            complete = False
            source = "http-recent"
        self.state.raw_data["file_listing"] = {"complete": complete, "source": source}
        return [{"name": name, "type": "file", "size": None, "modified": None, "path": f"/{name}"} for name in names]

    def upload_file(
        self,
        local_path: Path,
        remote_path: str,
        *,
        overwrite: bool = False,  # noqa: ARG002 - conflict policy is enforced by the route before upload
        storage: str | None = None,
    ) -> bool:
        if storage:
            raise ValueError("FlashForge AD5M does not expose selectable file storage")
        filename = _safe_remote_filename(remote_path)
        self.http.upload_gcode(local_path, remote_filename=filename, leveling_before_print=False)
        return True

    def start_print(self, filename: str, plate_id: int = 1, **kwargs: Any) -> bool:  # noqa: ARG002
        if kwargs.get("storage"):
            raise ValueError("FlashForge AD5M does not expose selectable file storage")
        if kwargs.get("ams_mapping") is not None or kwargs.get("print_platform_type") is not None:
            raise ValueError("FlashForge AD5M does not support AMS mapping or platform selection")
        target = _safe_remote_filename(filename)
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
        if not any(_same_filename(entry.get("name"), target) for entry in files):
            return False

        leveling_before_print = kwargs.get("bed_levelling", True)
        try:
            self.http.print_gcode(target, levelingBeforePrint=bool(leveling_before_print))
        except Exception:
            return self._reconcile_print_state("RUNNING", target)
        return self._reconcile_print_state("RUNNING", target)

    def pause_print(self) -> bool:
        return self._job_action("pause", allowed={"RUNNING"}, expected={"PAUSE"})

    def resume_print(self) -> bool:
        return self._job_action("continue", allowed={"PAUSE"}, expected={"RUNNING"})

    def stop_print(self) -> bool:
        return self._job_action("cancel", allowed={"RUNNING", "PAUSE"}, expected={"IDLE", "FINISH", "FAILED"})

    def set_nozzle_temperature(self, target: int) -> bool:
        return self._set_temperature(
            "rightNozzle", "nozzle_target", target, maximum=self.contract.nozzle_max_c
        )

    def set_bed_temperature(self, target: int) -> bool:
        return self._set_temperature("platform", "bed_target", target, maximum=self.contract.bed_max_c)

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

    def set_fan_speed(self, fan: str, speed: int) -> bool:
        if isinstance(speed, bool) or not isinstance(speed, int) or not 0 <= speed <= 100:
            raise ValueError("FlashForge fan speed must be 0-100 percent")
        normalized = str(fan or "").strip().lower().replace("-", "_")
        fan_fields = {
            "part": ("coolingFan", "cooling_fan_speed"),
            "model": ("coolingFan", "cooling_fan_speed"),
            "model_fan": ("coolingFan", "cooling_fan_speed"),
            "cooling": ("coolingFan", "cooling_fan_speed"),
            "chamber": ("chamberFan", "big_fan1_speed"),
            "box": ("chamberFan", "big_fan1_speed"),
            "box_fan": ("chamberFan", "big_fan1_speed"),
        }
        if normalized not in fan_fields:
            raise ValueError("FlashForge AD5M supports only cooling and chamber fans")
        command_field, status_key = fan_fields[normalized]
        try:
            self.request_status_update()
        except Exception:
            return False
        if self.state.state not in {"IDLE", "RUNNING", "PAUSE", "FINISH"}:
            return False
        try:
            self.http.control("printerCtl_cmd", {command_field: speed})
        except Exception:
            return self._reconcile_numeric_status(status_key, speed)
        return self._reconcile_numeric_status(status_key, speed)

    def _set_temperature(self, field: str, status_key: str, target: int, *, maximum: int) -> bool:
        if isinstance(target, bool) or not isinstance(target, int) or not 0 <= target <= maximum:
            raise ValueError(f"FlashForge {field} target must be 0-{maximum} C")
        try:
            self.request_status_update()
        except Exception:
            return False
        if self.state.state not in {"IDLE", "RUNNING", "PAUSE", "FINISH"}:
            return False
        try:
            self.http.control("temperatureCtl_cmd", {field: target})
        except Exception:
            return self._reconcile_temperature(status_key, target)
        return self._reconcile_temperature(status_key, target)

    def _reconcile_temperature(self, status_key: str, target: int) -> bool:
        return self._reconcile_numeric_status(status_key, target)

    def _reconcile_numeric_status(self, status_key: str, target: int) -> bool:
        for attempt in range(self.RECONCILE_ATTEMPTS):
            try:
                self.request_status_update()
            except Exception:
                return False
            observed = _number(self.state.temperatures.get(status_key))
            if observed is None:
                observed = _number(getattr(self.state, status_key, None))
            if observed is not None and abs(observed - target) <= 1:
                return True
            if attempt + 1 < self.RECONCILE_ATTEMPTS:
                time.sleep(self.RECONCILE_INTERVAL_SECONDS)
        return False

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
            return self._reconcile_state(expected)
        return self._reconcile_state(expected)

    def _reconcile_print_state(self, expected_state: str, filename: str) -> bool:
        for attempt in range(self.RECONCILE_ATTEMPTS):
            try:
                self.request_status_update()
            except Exception:
                return False
            observed = self.state.gcode_file or self.state.current_print
            if self.state.state == expected_state and _same_filename(observed, filename):
                return True
            if attempt + 1 < self.RECONCILE_ATTEMPTS:
                time.sleep(self.RECONCILE_INTERVAL_SECONDS)
        return False

    def _reconcile_state(self, expected: set[str]) -> bool:
        for attempt in range(self.RECONCILE_ATTEMPTS):
            try:
                self.request_status_update()
            except Exception:
                return False
            if self.state.state in expected:
                return True
            if attempt + 1 < self.RECONCILE_ATTEMPTS:
                time.sleep(self.RECONCILE_INTERVAL_SECONDS)
        return False


def _optional_int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _safe_remote_filename(value: str) -> str:
    normalized = str(value or "").replace("\\", "/")
    parts = [part for part in PurePosixPath(normalized).parts if part not in {"/", "."}]
    if ".." in parts:
        raise ValueError("Invalid FlashForge remote path")
    if len(parts) != 1:
        raise ValueError("FlashForge AD5M only supports files in the printer root directory")
    return _safe_filename(normalized)


def _is_nested_remote_path(value: str) -> bool:
    normalized = str(value or "").replace("\\", "/")
    return len([part for part in PurePosixPath(normalized).parts if part not in {"/", "."}]) > 0


def _same_filename(left: Any, right: Any) -> bool:
    left_name = str(left or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    right_name = str(right or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    return bool(left_name and right_name and left_name.casefold() == right_name.casefold())


def _recent_files(response: dict[str, Any]) -> list[str]:
    values = response.get("gcodeList")
    if isinstance(values, list):
        return [str(value).strip() for value in values if str(value or "").strip()]
    values = response.get("gcodeListDetail")
    if isinstance(values, list):
        return [str(row.get("gcodeFileName") or "").strip() for row in values if isinstance(row, dict) and row.get("gcodeFileName")]
    return []


def create_flashforge_ad5m_client(printer: Any, **callbacks: Any) -> FlashForgeAd5mPrinterClient:
    raw_options = getattr(printer, "provider_options", None)
    options = json.loads(raw_options) if isinstance(raw_options, str) and raw_options else raw_options or {}
    if not isinstance(options, dict):
        raise ValueError("FlashForge provider_options must be an object")
    return FlashForgeAd5mPrinterClient(
        host=getattr(printer, "ip_address", ""),
        model=getattr(printer, "model", None),
        serial_number=getattr(printer, "serial_number", ""),
        check_code=decrypt_check_code(getattr(printer, "auth_token", None)),
        http_port=options.get("http_port"),
        camera_port=options.get("camera_port"),
        tcp_port=options.get("tcp_port"),
        on_state_change=callbacks.get("on_state_change"),
        on_print_start=callbacks.get("on_print_start"),
        on_print_complete=callbacks.get("on_print_complete"),
        on_bed_temp_update=callbacks.get("on_bed_temp_update"),
    )
