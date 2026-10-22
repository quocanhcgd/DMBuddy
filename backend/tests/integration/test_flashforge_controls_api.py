"""API range and provider dispatch tests for FlashForge controls."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class _FakeTemperatureClient:
    def __init__(self) -> None:
        self.nozzle_targets: list[int] = []
        self.bed_targets: list[int] = []
        self.chamber_targets: list[int] = []
        self.filament_configs: list[tuple[int, str | None, str | None]] = []
        self.fan_targets: list[tuple[str, int]] = []

    def set_nozzle_temperature(self, target: int, extruder: int | None = None) -> bool:
        self.nozzle_targets.append((target, extruder))
        return True

    def set_bed_temperature(self, target: int) -> bool:
        self.bed_targets.append(target)
        return True

    def set_chamber_temperature(self, target: int) -> bool:
        self.chamber_targets.append(target)
        return True

    def set_filament_config(
        self,
        tool_index: int,
        *,
        material: str | None = None,
        color: str | None = None,
    ) -> bool:
        self.filament_configs.append((tool_index, material, color))
        return True

    def set_fan_speed(self, fan: str, speed: int) -> bool:
        self.fan_targets.append((fan, speed))
        return True


class _FakeCalibrationClient:
    def __init__(self) -> None:
        from types import SimpleNamespace

        self.state = SimpleNamespace(connected=True)
        self.calibration_calls: list[dict[str, bool]] = []

    def start_calibration(self, **options: bool) -> bool:
        self.calibration_calls.append(options)
        return True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flashforge_temperature_routes_enforce_model_ranges(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    client = _FakeTemperatureClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_client", lambda _printer_id: client)

    nozzle_ok = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/nozzle", params={"target": 265})
    nozzle_high = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/nozzle", params={"target": 266})
    bed_ok = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/bed", params={"target": 110})
    bed_high = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/bed", params={"target": 111})

    assert nozzle_ok.status_code == 200
    assert nozzle_high.status_code == 400
    assert bed_ok.status_code == 200
    assert bed_high.status_code == 400
    assert client.nozzle_targets == [(265, None)]
    assert client.bed_targets == [110]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_connector_temperature_timeout_returns_delivery_unknown_without_retry(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    from unittest.mock import AsyncMock

    from backend.app.api.routes import printers as printer_routes
    from backend.app.services.connector_gateway import ConnectorRequestDeliveryUnknown

    printer = await printer_factory(
        provider="flashforge_ad5m", model="Adventurer 5M",
        connection_mode="connector", connector_id="connector-uncertain",
    )
    request = AsyncMock(side_effect=[
        ConnectorRequestDeliveryUnknown("temperature-request-1"),
        {
            "request_id": "status-readback-1", "status": "completed", "connected": True,
            "state": "IDLE", "telemetry": {"state": "IDLE", "temperatures": {"nozzle_target": 210.0}},
        },
    ])
    monkeypatch.setattr(printer_routes.connector_gateway, "request", request)

    response = await async_client.post(
        f"/api/v1/printers/{printer.id}/temperature/nozzle", params={"target": 210}
    )

    assert response.status_code == 504
    assert response.json()["detail"]["outcome"] == "delivery_unknown"
    assert response.json()["detail"]["request_id"] == "temperature-request-1"
    assert response.json()["detail"]["reconciliation"] == {
        "status": "observed", "connected": True, "state": "IDLE", "temperatures": {"nozzle_target": 210.0}
    }
    assert request.await_count == 2
    assert request.await_args_list[1].args[1] == "printer.status.request"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creator5_temperature_routes_dispatch_tool_index_and_enforce_ranges(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_creator5", model="Creator 5")
    client = _FakeTemperatureClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_client", lambda _printer_id: client)

    nozzle_ok = await async_client.post(
        f"/api/v1/printers/{printer.id}/temperature/nozzle", params={"target": 310, "extruder": 3}
    )
    nozzle_high = await async_client.post(
        f"/api/v1/printers/{printer.id}/temperature/nozzle", params={"target": 321, "extruder": 3}
    )
    bed_ok = await async_client.post(f"/api/v1/printers/{printer.id}/temperature/bed", params={"target": 120})

    assert nozzle_ok.status_code == 200
    assert nozzle_high.status_code == 400
    assert bed_ok.status_code == 200
    assert client.nozzle_targets == [(310, 3)]
    assert client.bed_targets == [120]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creator5_chamber_route_is_pro_only_and_enforces_model_limit(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    standard = await printer_factory(provider="flashforge_creator5", model="Creator 5")
    pro = await printer_factory(provider="flashforge_creator5", model="Creator 5 Pro")
    client = _FakeTemperatureClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_client", lambda _printer_id: client)

    unsupported = await async_client.post(
        f"/api/v1/printers/{standard.id}/temperature/chamber", params={"target": 45}
    )
    supported = await async_client.post(
        f"/api/v1/printers/{pro.id}/temperature/chamber", params={"target": 65}
    )
    over_limit = await async_client.post(
        f"/api/v1/printers/{pro.id}/temperature/chamber", params={"target": 66}
    )

    assert unsupported.status_code == 400
    assert supported.status_code == 200
    assert over_limit.status_code == 400
    assert client.chamber_targets == [65]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_creator5_filament_config_route_dispatches_tool_and_rejects_other_providers(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    creator5 = await printer_factory(provider="flashforge_creator5", model="Creator 5")
    ad5m = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    client = _FakeTemperatureClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_client", lambda _printer_id: client)

    supported = await async_client.post(
        f"/api/v1/printers/{creator5.id}/filament-config",
        json={"tool_index": 2, "material": "PETG", "color": "#F82D29"},
    )
    unsupported = await async_client.post(
        f"/api/v1/printers/{ad5m.id}/filament-config",
        json={"tool_index": 0, "material": "PLA"},
    )

    assert supported.status_code == 200
    assert supported.json()["slot"] == 3
    assert supported.json()["verified"] is True
    assert unsupported.status_code == 400
    assert client.filament_configs == [(2, "PETG", "#F82D29")]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flashforge_fan_route_dispatches_supported_alias_and_rejects_aux(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    client = _FakeTemperatureClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_client", lambda _printer_id: client)

    supported = await async_client.post(
        f"/api/v1/printers/{printer.id}/fan-speed", params={"fan": "cooling", "speed": 65}
    )
    unsupported = await async_client.post(
        f"/api/v1/printers/{printer.id}/fan-speed", params={"fan": "aux", "speed": 65}
    )

    assert supported.status_code == 200
    assert unsupported.status_code == 400
    assert client.fan_targets == [("cooling", 65)]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_flashforge_standalone_calibration_is_rejected(
    async_client: AsyncClient,
    printer_factory,
    monkeypatch: pytest.MonkeyPatch,
):
    printer = await printer_factory(provider="flashforge_ad5m", model="Adventurer 5M")
    client = _FakeCalibrationClient()

    from backend.app.api.routes import printers as printer_routes

    monkeypatch.setattr(printer_routes.printer_manager, "get_client", lambda _printer_id: client)

    response = await async_client.post(f"/api/v1/printers/{printer.id}/calibration", params={"bed_leveling": True})

    assert response.status_code == 400
    assert "only supported before print" in response.json()["detail"]
    assert client.calibration_calls == []
