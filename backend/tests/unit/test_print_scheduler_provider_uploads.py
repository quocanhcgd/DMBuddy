from pathlib import Path
from zipfile import ZipFile

import pytest

from backend.app.services import print_scheduler as ps
from backend.app.services.print_scheduler import PrintScheduler


class FakeProviderClient:
    def __init__(self):
        self.uploads: list[tuple[Path, str]] = []
        self.deletes: list[str] = []

    def upload_file(self, local_path: Path, remote_path: str) -> bool:
        self.uploads.append((local_path, remote_path))
        return True

    def delete_file(self, remote_path: str) -> bool:
        self.deletes.append(remote_path)
        return True


class FakeCreator5ProviderClient(FakeProviderClient):
    def upload_file(self, local_path: Path, remote_path: str, *, tool_count: int = 1) -> bool:
        self.uploads.append((local_path, remote_path, tool_count))
        return True


def test_scheduler_remote_filename_preserves_gcode_for_moonraker_providers():
    scheduler = PrintScheduler()

    assert scheduler._remote_filename_for_provider("Cable Holder.gcode", "fluidd") == "Cable_Holder.gcode"
    assert scheduler._remote_filename_for_provider("Cable Holder.gcode", "mainsail") == "Cable_Holder.gcode"
    assert scheduler._remote_filename_for_provider("Cable Holder.gcode", "klipper") == "Cable_Holder.gcode"


def test_scheduler_remote_filename_keeps_bambu_3mf_rewrite():
    scheduler = PrintScheduler()

    assert scheduler._remote_filename_for_provider("Cable Holder.gcode.3mf", "bambu") == "Cable_Holder.3mf"
    assert scheduler._remote_filename_for_provider("Cable Holder.3mf", "bambu") == "Cable_Holder.3mf"


@pytest.mark.asyncio
async def test_scheduler_provider_upload_uses_connected_client_not_bambu_ftp(monkeypatch, tmp_path):
    scheduler = PrintScheduler()
    local_file = tmp_path / "Cable Holder.gcode"
    local_file.write_text("G28\n", encoding="utf-8")
    client = FakeProviderClient()

    monkeypatch.setattr(ps.printer_manager, "get_client", lambda printer_id: client)

    async def fail_bambu_upload(*args, **kwargs):  # pragma: no cover - assertion path
        raise AssertionError("Bambu FTP upload must not be used for Moonraker queue dispatch")

    monkeypatch.setattr(ps, "upload_file_async", fail_bambu_upload)

    uploaded = await scheduler._upload_file_for_provider(
        printer_id=42,
        provider="fluidd",
        printer_name="K2 Plus",
        printer_ip="192.0.2.10",
        printer_access_code="unused",
        file_path=local_file,
        remote_path="/Cable_Holder.gcode",
        printer_model="Creality K2 Plus",
        ftp_retry_enabled=True,
        ftp_retry_count=3,
        ftp_retry_delay=0,
        ftp_timeout=1,
        operation_name="Upload print to K2 Plus",
    )

    assert uploaded is True
    assert client.uploads == [(local_file, "/Cable_Holder.gcode")]


@pytest.mark.asyncio
async def test_scheduler_provider_delete_uses_connected_client_not_bambu_ftp(monkeypatch):
    scheduler = PrintScheduler()
    client = FakeProviderClient()
    monkeypatch.setattr(ps.printer_manager, "get_client", lambda printer_id: client)

    async def fail_bambu_delete(*args, **kwargs):  # pragma: no cover - assertion path
        raise AssertionError("Bambu FTP delete must not be used for Moonraker queue dispatch")

    monkeypatch.setattr(ps, "delete_file_async", fail_bambu_delete)

    await scheduler._delete_remote_file_for_provider(
        printer_id=42,
        provider="fluidd",
        printer_ip="192.0.2.10",
        printer_access_code="unused",
        remote_path="/Cable_Holder.gcode",
        printer_model="Creality K2 Plus",
        ftp_timeout=1,
    )

    assert client.deletes == ["/Cable_Holder.gcode"]


def test_creator5_tool_count_comes_from_used_slicer_slots(tmp_path):
    source = tmp_path / "multi.3mf"
    config = (
        '<config><filament id="1" used_g="10" type="PLA" color="#FFFFFF" />'
        '<filament id="3" used_g="5" type="PETG" color="#000000" /></config>'
    )
    with ZipFile(source, "w") as archive:
        archive.writestr("Metadata/slice_info.config", config)

    assert ps._creator5_tool_count_from_file(source, None) == 2
    assert ps._creator5_tool_count_from_file(tmp_path / "plain.gcode", None) == 1


@pytest.mark.asyncio
async def test_scheduler_creator5_upload_passes_metadata_tool_count(monkeypatch, tmp_path):
    scheduler = PrintScheduler()
    local_file = tmp_path / "multi.3mf"
    local_file.write_bytes(b"PK")
    client = FakeCreator5ProviderClient()
    monkeypatch.setattr(ps.printer_manager, "get_client", lambda printer_id: client)

    uploaded = await scheduler._upload_file_for_provider(
        printer_id=42,
        provider="flashforge_creator5",
        printer_name="Creator 5 Pro",
        printer_ip="192.0.2.11",
        printer_access_code="unused",
        file_path=local_file,
        remote_path="/multi.3mf",
        printer_model="Creator 5 Pro",
        ftp_retry_enabled=False,
        ftp_retry_count=0,
        ftp_retry_delay=0,
        ftp_timeout=1,
        operation_name="Upload print to Creator 5 Pro",
        tool_count=2,
    )

    assert uploaded is True
    assert client.uploads == [(local_file, "/multi.3mf", 2)]
