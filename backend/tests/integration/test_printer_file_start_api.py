"""Regression tests for direct printer-file start endpoint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from httpx import AsyncClient


class _FakeProviderClient:
    def __init__(self) -> None:
        self.started_paths: list[str] = []
        self.uploaded_paths: list[str] = []
        self.upload_overwrite_flags: list[bool] = []
        self.files: list[dict[str, object]] = []
        self.upload_exception: Exception | None = None
        self.list_files_calls = 0
        self.reveal_file_after_list_calls: int | None = None
        self.revealed_file: dict[str, object] | None = None
        self.preserve_files_on_upload = False
        self.deleted_paths: list[str] = []
        self.start_options: list[dict[str, object]] = []
        self.file_info: dict[str, object] | None = None
        self.file_info_paths: list[str] = []
        self.upload_tool_counts: list[int | None] = []
        self.state = SimpleNamespace(raw_data={})

    def get_file_info(self, path: str) -> dict[str, object] | None:
        self.file_info_paths.append(path)
        return self.file_info

    def start_print(self, path: str, **kwargs) -> bool:
        self.started_paths.append(path)
        self.start_options.append(kwargs)
        return True

    def upload_file(
        self,
        local_path,
        remote_path: str,
        *,
        overwrite: bool = False,
        storage: str | None = None,
        tool_count: int | None = None,
    ) -> bool:  # noqa: ARG002
        self.uploaded_paths.append(remote_path)
        self.upload_overwrite_flags.append(overwrite)
        self.upload_tool_counts.append(tool_count)
        if self.upload_exception is not None:
            raise self.upload_exception
        if self.preserve_files_on_upload:
            return True
        self.files.append(
            {
                "name": remote_path.rsplit("/", 1)[-1],
                "path": remote_path,
                "type": "file",
                "size": local_path.stat().st_size,
            }
        )
        return True

    def list_files(self, _path: str = "/", *, storage: str | None = None) -> list[dict[str, object]]:  # noqa: ARG002
        self.list_files_calls += 1
        if (
            self.reveal_file_after_list_calls is not None
            and self.revealed_file is not None
            and self.list_files_calls >= self.reveal_file_after_list_calls
        ):
            self.files = [self.revealed_file]
        return self.files

    def delete_file(self, remote_path: str, *, storage: str | None = None) -> bool:  # noqa: ARG002
        self.deleted_paths.append(remote_path)
        normalized = "/" + remote_path.strip("/")
        self.files = [
            file
            for file in self.files
            if "/" + str(file.get("path") or file.get("name") or "").strip("/") != normalized
        ]
        return True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_printer_files_delegates_elegoo_cc1_to_provider_client(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()
    fake_client.files = [
        {
            "name": "USB Folder",
            "path": "/usb/USB Folder",
            "type": "directory",
            "size": 0,
            "modified": None,
        },
        {
            "name": "benchy.gcode",
            "path": "/usb/benchy.gcode",
            "type": "file",
            "size": 123456,
            "modified": None,
        },
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.get(f"/api/v1/printers/{printer.id}/files", params={"path": "/"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "/"
    assert payload["files"] == [
        {
            "name": "USB Folder",
            "path": "/usb/USB Folder",
            "type": "directory",
            "size": 0,
            "modified": None,
            "is_directory": True,
            "mtime": None,
        },
        {
            "name": "benchy.gcode",
            "path": "/usb/benchy.gcode",
            "type": "file",
            "size": 123456,
            "modified": None,
            "is_directory": False,
            "mtime": None,
        },
    ]
    assert fake_client.list_files_calls == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_flashforge_ad5m_rejects_nested_directory(
    async_client: AsyncClient,
    printer_factory,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")

    response = await async_client.get(
        f"/api/v1/printers/{printer.id}/files", params={"path": "/Metadata"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "FlashForge AD5M only supports files in the printer root directory"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_flashforge_ad5m_exposes_recent_only_warning(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    fake_client = _FakeProviderClient()
    fake_client.state.raw_data["file_listing"] = {"complete": False, "source": "http-recent"}

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.get(f"/api/v1/printers/{printer.id}/files")

    assert response.status_code == 200
    assert response.json()["listing"] == {
        "completeness": "recent_only",
        "source": "http-recent",
        "warning": "The printer returned recent files only; a full listing is unavailable while TCP M661 cannot be reached.",
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flashforge_capabilities_report_runtime_and_reference_states(
    async_client: AsyncClient,
    printer_factory,
):
    ad5m = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    creator5 = await printer_factory(provider="flashforge_creator5", model="Creator 5")

    ad5m_response = await async_client.get(f"/api/v1/printers/{ad5m.id}/capabilities")
    creator5_response = await async_client.get(f"/api/v1/printers/{creator5.id}/capabilities")

    assert ad5m_response.status_code == 200
    assert ad5m_response.json()["capabilities"]["local_files"] == "partial"
    assert ad5m_response.json()["capabilities"]["status"] == "implemented"
    assert ad5m_response.json()["capabilities"]["bed_leveling"] == "planned"
    assert ad5m_response.json()["capabilities"]["bed_leveling_before_print"] == "implemented"
    assert ad5m_response.json()["hardware_verified"] is False
    assert creator5_response.status_code == 200
    assert creator5_response.json()["provider_implemented"] is True
    assert creator5_response.json()["capabilities"]["status"] == "implemented"
    assert creator5_response.json()["capabilities"]["local_files"] == "partial"
    assert creator5_response.json()["capabilities"]["nozzle_temperature"] == "implemented"
    assert creator5_response.json()["capabilities"]["tool_temperatures"] == "implemented"
    assert creator5_response.json()["capabilities"]["bed_temperature"] == "implemented"
    assert creator5_response.json()["capabilities"]["material_status"] == "implemented"
    assert creator5_response.json()["capabilities"]["filament_type_control"] == "implemented"
    assert creator5_response.json()["capabilities"]["filament_color_control"] == "implemented"
    assert creator5_response.json()["capabilities"]["file_upload"] == "implemented"
    assert creator5_response.json()["capabilities"]["print_local_file"] == "implemented"
    assert creator5_response.json()["capabilities"]["job_control"] == "implemented"

    creator5_pro = await printer_factory(provider="flashforge_creator5", model="Creator 5 Pro")
    creator5_pro_response = await async_client.get(f"/api/v1/printers/{creator5_pro.id}/capabilities")
    assert creator5_pro_response.status_code == 200
    assert creator5_pro_response.json()["capabilities"]["chamber_temperature"] == "implemented"

    connector_ad5m = await printer_factory(
        provider="flashforge_ad5m", model="Adventurer 5M", connection_mode="connector", connector_id="cap-connector"
    )
    connector_ad5m_response = await async_client.get(f"/api/v1/printers/{connector_ad5m.id}/capabilities")
    assert connector_ad5m_response.status_code == 200
    connector_caps = connector_ad5m_response.json()["capabilities"]
    assert connector_caps["status"] == "implemented"
    assert connector_caps["file_upload"] == "implemented"
    assert connector_caps["job_control"] == "implemented"
    assert connector_caps["camera"] == "unavailable"

    connector_creator5 = await printer_factory(
        provider="flashforge_creator5", model="Creator 5 Pro",
        connection_mode="connector", connector_id="cap-connector",
    )
    connector_creator5_response = await async_client.get(f"/api/v1/printers/{connector_creator5.id}/capabilities")
    assert connector_creator5_response.status_code == 200
    assert connector_creator5_response.json()["capabilities"]["chamber_temperature"] == "implemented"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creator5_status_and_file_routes_expose_four_tools_and_recent_only_listing(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    from backend.app.services.printer_providers.flashforge_creator5 import FlashForgeCreator5PrinterClient

    class _Http:
        def detail(self):
            return {
                "detail": {
                    "status": "ready",
                    "nozzleTemps": [201, 202, 203, 204],
                    "nozzleTargetTemps": [0, 210, 0, 0],
                    "currentSlot": 3,
                    "platTemp": 55,
                    "platTargetTemp": 60,
                }
            }

        def gcode_list(self):
            return {"gcodeList": ["recent.gcode"]}

        def close(self):
            pass

    printer = await printer_factory(provider="flashforge_creator5", model="Creator 5")
    client = FlashForgeCreator5PrinterClient(
        host="creator.local",
        model="Creator 5",
        serial_number="C5-SN",
        check_code="secret",
        http_client=_Http(),
    )
    client.request_status_update()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_status", lambda _printer_id: client.state)
    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: client)

    status = await async_client.get(f"/api/v1/printers/{printer.id}/status")
    files = await async_client.get(f"/api/v1/printers/{printer.id}/files")

    assert status.status_code == 200
    assert status.json()["temperatures"]["nozzle_4"] == 204
    assert status.json()["active_extruder"] == 1
    assert len(status.json()["nozzles"]) == 4
    assert files.status_code == 200
    assert files.json()["files"][0]["name"] == "recent.gcode"
    assert files.json()["listing"]["completeness"] == "recent_only"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_delegates_to_provider_client(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/Love Paw Print.gcode"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "path": "/Love Paw Print.gcode"}
    assert fake_client.started_paths == ["/Love Paw Print.gcode"]
    assert fake_client.start_options == [{}]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_flashforge_ad5m_rejects_nested_path_and_unsupported_options(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    nested = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start", params={"path": "/Metadata/cube.gcode"}
    )
    mapped = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/cube.gcode", "ams_mapping": [1]},
    )

    assert nested.status_code == 400
    assert nested.json()["detail"] == "FlashForge AD5M only supports files in the printer root directory"
    assert mapped.status_code == 400
    assert mapped.json()["detail"] == "FlashForge AD5M does not support AMS mapping or platform selection"
    assert fake_client.started_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_passes_elegoo_cc1_start_options_to_provider(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={
            "path": "/local/Love Paw Print.gcode",
            "bed_levelling": "true",
            "print_platform_type": "1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"status": "started", "path": "/local/Love Paw Print.gcode"}
    assert fake_client.started_paths == ["/local/Love Paw Print.gcode"]
    assert fake_client.start_options == [{"bed_levelling": True, "print_platform_type": 1}]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_passes_ams_mapping_to_provider(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="moonraker", model="Creality K2 Plus")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode", "ams_mapping": [1, -1, -1, -1]},
    )

    assert response.status_code == 200
    assert fake_client.started_paths == ["/local/Love Paw Print.gcode"]
    assert fake_client.start_options == [{"ams_mapping": [1, -1, -1, -1]}]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_registers_elegoo_direct_print_estimated_weight(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()
    fake_client.file_info = {
        "path": "/local/Love Paw Print.gcode",
        "estimated_weight_grams": 9.79,
        "estimated_time_seconds": 2608,
    }
    registered: list[tuple[int, str, float, int | None]] = []

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(
        printer_routes.direct_print_tracking,
        "register_direct_print_metadata",
        lambda printer_id, filename, estimated_weight_grams, estimated_time_seconds=None: registered.append(
            (printer_id, filename, estimated_weight_grams, estimated_time_seconds)
        ),
    )

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode"},
    )

    assert response.status_code == 200
    assert fake_client.file_info_paths == ["/local/Love Paw Print.gcode"]
    assert registered == [(printer.id, "/local/Love Paw Print.gcode", 9.79, 2608)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_does_not_register_metadata_when_start_fails(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")
    fake_client = _FakeProviderClient()
    fake_client.file_info = {"estimated_weight_grams": 9.79}
    fake_client.start_print = lambda path, **kwargs: False
    registered: list[object] = []

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(
        printer_routes.direct_print_tracking,
        "register_direct_print_metadata",
        lambda *args, **kwargs: registered.append((args, kwargs)),
    )

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode"},
    )

    assert response.status_code == 500
    assert registered == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_start_printer_file_rejects_invalid_print_platform_type(async_client: AsyncClient, printer_factory):
    printer = await printer_factory(provider="elegoo_sdcp", model="Elegoo Centauri Carbon")

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start",
        params={"path": "/local/Love Paw Print.gcode", "print_platform_type": "2"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_prusalink_firmware_file_delegates_to_provider_client(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/firmware/upload",
        params={"path": "/"},
        files={"file": ("core-one-6.3.0.bbf", b"prusa firmware", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/core-one-6.3.0.bbf",
        "filename": "core-one-6.3.0.bbf",
        "firmware": True,
    }
    assert fake_client.uploaded_paths == ["/core-one-6.3.0.bbf"]
    assert fake_client.started_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_firmware_file_rejects_non_prusalink_provider(
    async_client: AsyncClient,
    printer_factory,
):
    printer = await printer_factory(provider="bambu", model="Bambu Lab P1S")

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/firmware/upload",
        files={"file": ("core-one-6.3.0.bbf", b"prusa firmware", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Firmware upload is only supported for PrusaLink printers"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_prusalink_firmware_file_rejects_non_bbf_extension(
    async_client: AsyncClient,
    printer_factory,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/firmware/upload",
        files={"file": ("core-one-6.3.0.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported firmware file type. Upload a .bbf file."


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_delegates_to_provider_client(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.upload_overwrite_flags == [False]
    assert fake_client.started_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creator5_upload_passes_explicit_tool_count_to_provider(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_creator5", model="Creator 5")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"tool_count": 3},
        files={"file": ("multi.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "uploaded"
    assert fake_client.uploaded_paths == ["/multi.gcode"]
    assert fake_client.upload_tool_counts == [3]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_flashforge_ad5m_rejects_nested_directory_before_upload(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    fake_client = _FakeProviderClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/Metadata"},
        files={"file": ("cube.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "FlashForge AD5M only supports files in the printer root directory"
    assert fake_client.uploaded_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_reconciles_provider_timeout_when_file_appears(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.upload_exception = httpx.ReadTimeout("printer still writing to USB")
    fake_client.reveal_file_after_list_calls = 2
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 4,
    }

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
        "reconciled": True,
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.started_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_waits_for_provider_file_to_appear_after_timeout(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.upload_exception = httpx.ReadTimeout("printer still writing to USB")
    fake_client.reveal_file_after_list_calls = 3
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 4,
    }

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(printer_routes, "PROVIDER_UPLOAD_RECONCILE_INTERVAL_SECONDS", 0)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
        "reconciled": True,
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.upload_overwrite_flags == [False]
    assert fake_client.list_files_calls == 3


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_rejects_zero_byte_provider_placeholder(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.preserve_files_on_upload = True
    fake_client.reveal_file_after_list_calls = 2
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 0,
    }

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(printer_routes, "PROVIDER_UPLOAD_RECONCILE_INTERVAL_SECONDS", 0)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 502
    assert "0-byte placeholder" in response.json()["detail"]
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_reports_zero_byte_placeholder_on_conflict(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    import httpx

    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    request = httpx.Request("PUT", "http://printer/api/v1/files/usb/Shoe_horn_thicker.gcode")
    response = httpx.Response(409, request=request)
    fake_client.upload_exception = httpx.HTTPStatusError("Conflict", request=request, response=response)
    fake_client.reveal_file_after_list_calls = 2
    fake_client.revealed_file = {
        "name": "Shoe_horn_thicker.gcode",
        "path": "/Shoe_horn_thicker.gcode",
        "type": "file",
        "size": 0,
    }

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/", "overwrite": "true"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert "0-byte placeholder" in response.json()["detail"]
    assert fake_client.upload_overwrite_flags == [True]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_renames_existing_provider_file_when_requested(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 4},
        {"name": "Shoe_horn_thicker(1).gcode", "path": "/Shoe_horn_thicker(1).gcode", "type": "file", "size": 4},
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/", "conflict_strategy": "rename"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker(2).gcode",
        "filename": "Shoe_horn_thicker(2).gcode",
        "renamed": True,
        "original_filename": "Shoe_horn_thicker.gcode",
    }
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker(2).gcode"]
    assert fake_client.deleted_paths == []
    assert fake_client.upload_overwrite_flags == [False]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_delete_replaces_existing_provider_file_when_requested(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 4}
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)
    monkeypatch.setattr(printer_routes, "PROVIDER_UPLOAD_RECONCILE_INTERVAL_SECONDS", 0)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/", "conflict_strategy": "delete_replace"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "uploaded",
        "path": "/Shoe_horn_thicker.gcode",
        "filename": "Shoe_horn_thicker.gcode",
        "replaced": True,
    }
    assert fake_client.deleted_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.uploaded_paths == ["/Shoe_horn_thicker.gcode"]
    assert fake_client.upload_overwrite_flags == [False]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_upload_printer_file_reports_existing_provider_file_without_strategy(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="prusalink", model="Prusa CORE One")
    fake_client = _FakeProviderClient()
    fake_client.files = [
        {"name": "Shoe_horn_thicker.gcode", "path": "/Shoe_horn_thicker.gcode", "type": "file", "size": 4}
    ]

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: fake_client)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("Shoe_horn_thicker.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 409
    assert "already exists" in response.json()["detail"]
    assert fake_client.uploaded_paths == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connector_start_delivery_unknown_includes_read_only_reconciliation(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import AsyncMock

    from backend.app.api.routes import printers as printer_routes
    from backend.app.services.connector_gateway import ConnectorRequestDeliveryUnknown

    printer = await printer_factory(
        provider="flashforge_ad5m", model="Adventurer 5M",
        connection_mode="connector", connector_id="connector-start-unknown",
    )
    request = AsyncMock(side_effect=[
        ConnectorRequestDeliveryUnknown("start-request-1"),
        {
            "request_id": "status-readback-1", "status": "completed", "connected": True,
            "state": "RUNNING", "telemetry": {"state": "RUNNING", "filename": "cube.gcode", "progress": 0.0},
        },
    ])
    monkeypatch.setattr(printer_routes.connector_gateway, "request", request)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/start", params={"path": "/cube.gcode"}
    )

    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["outcome"] == "delivery_unknown"
    assert detail["request_id"] == "start-request-1"
    assert detail["reconciliation"]["status"] == "observed"
    assert detail["reconciliation"]["state"] == "RUNNING"
    assert detail["reconciliation"]["filename"] == "cube.gcode"
    assert request.await_count == 2
    assert request.await_args_list[1].args[1] == "printer.status.request"


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("provider", "completeness", "source", "files", "expected_listing_status"),
    [
        (
            "flashforge_ad5m",
            "complete",
            "tcp-m661",
            [{"name": "part.gcode", "path": "/part.gcode", "size": None}],
            "observed",
        ),
        (
            "flashforge_creator5",
            "recent_only",
            "http-recent",
            [{"name": "part.gcode", "path": "/part.gcode", "size": None}],
            "observed",
        ),
        ("flashforge_creator5", "recent_only", "http-recent", [], "not_observed"),
    ],
)
async def test_connector_upload_delivery_unknown_reports_file_observation_without_confirmation(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    completeness: str,
    source: str,
    files: list[dict[str, object]],
    expected_listing_status: str,
):
    from backend.app.api.routes import printers as printer_routes
    from backend.app.services.printer_transport import ConnectorDeliveryUnknownError

    printer = await printer_factory(
        provider=provider,
        model="Adventurer 5M" if provider == "flashforge_ad5m" else "Creator 5",
        connection_mode="connector",
        connector_id=f"connector-upload-unknown-{provider}",
    )

    async def upload_file(*_args, **_kwargs):
        raise ConnectorDeliveryUnknownError("upload-request-1")

    async def list_files(*_args, **_kwargs):
        return {
            "status": "completed",
            "completeness": completeness,
            "source": source,
            "files": files,
        }

    monkeypatch.setattr(printer_routes.ConnectorPrinterTransport, "upload_file", upload_file)
    monkeypatch.setattr(printer_routes.ConnectorPrinterTransport, "files", list_files)
    monkeypatch.setattr(printer_routes, "_provider_for_printer", lambda _printer: None)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/files/upload",
        params={"path": "/"},
        files={"file": ("part.gcode", b"G28\n", "application/octet-stream")},
    )

    assert response.status_code == 504
    detail = response.json()["detail"]
    assert detail["outcome"] == "delivery_unknown"
    assert detail["request_id"] == "upload-request-1"
    assert detail["reconciliation"]["status"] == expected_listing_status
    assert detail["reconciliation"]["completeness"] == completeness
    assert detail["reconciliation"]["source"] == source
    assert detail["reconciliation"]["integrity"] == "unverified"
