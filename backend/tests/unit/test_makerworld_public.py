import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.database import Base
from backend.app.models.makerworld_public import MakerWorldPublicDownload
from backend.app.models.settings import Settings
from backend.app.services.makerworld_public import finish_download, public_stats, record_visit, reserve_download


def _completed_download(day: str) -> MakerWorldPublicDownload:
    return MakerWorldPublicDownload(
        id=str(uuid4()),
        day=day,
        completed=True,
        expires_at=datetime(2026, 11, 6),
    )


@pytest.mark.asyncio
async def test_visits_and_stats_are_public_and_reads_do_not_count_visits(async_client, db_session):
    db_session.add(Settings(key="auth_enabled", value="true"))
    await db_session.commit()
    for expected in (1, 2):
        response = await async_client.post("/api/v1/makerworld/public/china/visit")
        assert response.status_code == 200, response.text
        assert response.json()["total_visits"] == expected
        assert response.headers["cache-control"] == "no-store"
    response = await async_client.get("/api/v1/makerworld/public/china/stats")
    assert response.status_code == 200, response.text
    assert response.json()["total_visits"] == 2
    assert response.json()["total_downloads"] == 0
    assert response.json()["remaining_downloads"] == 20


@pytest.mark.asyncio
async def test_global_limit_rejects_21st_download_before_calling_makerworld(async_client, db_session):
    fixed_now = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    db_session.add_all([_completed_download("2026-11-05") for _ in range(20)])
    await db_session.commit()
    with (
        patch("backend.app.services.makerworld_public._now", return_value=fixed_now),
        patch("backend.app.api.routes.makerworld._build_service", AsyncMock()) as build,
    ):
        response = await async_client.post("/api/v1/makerworld/public/china/download", json={"model_id": 123})
        stats = (await async_client.get("/api/v1/makerworld/public/china/stats")).json()
    assert response.status_code == 429, response.text
    assert int(response.headers["retry-after"]) == 7 * 3600
    assert "20" in response.json()["detail"]
    assert stats["downloads_today"] == 20
    assert stats["remaining_downloads"] == 0
    build.assert_not_awaited()


@pytest.mark.asyncio
async def test_failed_download_returns_its_reserved_slot(async_client, db_session):
    with patch(
        "backend.app.api.routes.makerworld.download_instance",
        AsyncMock(side_effect=HTTPException(502, "upstream failed")),
    ):
        response = await async_client.post("/api/v1/makerworld/public/china/download", json={"model_id": 123})
    assert response.status_code == 502
    assert await db_session.scalar(select(func.count()).select_from(MakerWorldPublicDownload)) == 0
    stats = (await async_client.get("/api/v1/makerworld/public/china/stats")).json()
    assert stats["total_downloads"] == 0
    assert stats["remaining_downloads"] == 20


@pytest.mark.asyncio
async def test_day_rolls_over_at_vietnam_midnight_and_totals_persist(db_session):
    before_midnight = datetime(2026, 11, 5, 16, 59, 59, tzinfo=timezone.utc)
    with patch("backend.app.services.makerworld_public._now", return_value=before_midnight):
        await record_visit(db_session)
        reservation = await reserve_download(db_session)
        pending = await public_stats(db_session)
        assert pending.downloads_today == 0
        assert pending.remaining_downloads == 19
        await finish_download(db_session, reservation, success=True)
        assert (await public_stats(db_session)).downloads_today == 1
    with patch("backend.app.services.makerworld_public._now", return_value=before_midnight + timedelta(seconds=1)):
        stats = await public_stats(db_session)
    assert stats.downloads_today == 0
    assert stats.remaining_downloads == 20
    assert stats.total_downloads == 1
    assert stats.total_visits == 1
    assert stats.resets_at.isoformat() == "2026-11-07T00:00:00+07:00"


@pytest.mark.asyncio
async def test_expired_reservations_are_released(db_session):
    now = datetime(2026, 11, 5, 10, tzinfo=timezone.utc)
    db_session.add(
        MakerWorldPublicDownload(
            id=str(uuid4()),
            day="2026-11-05",
            completed=False,
            expires_at=now.replace(tzinfo=None) - timedelta(seconds=1),
        )
    )
    await db_session.commit()
    with patch("backend.app.services.makerworld_public._now", return_value=now):
        await reserve_download(db_session)
        assert (await public_stats(db_session)).remaining_downloads == 19
        assert await db_session.scalar(select(func.count()).select_from(MakerWorldPublicDownload)) == 1


@pytest.mark.asyncio
async def test_concurrent_reservations_cannot_exceed_global_limit(tmp_path):
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp_path / 'makerworld.db').as_posix()}", connect_args={"timeout": 15}
    )
    sessions = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with sessions() as db:
            day = datetime.now(timezone(timedelta(hours=7))).date().isoformat()
            db.add_all([_completed_download(day) for _ in range(19)])
            await db.commit()

        async def reserve():
            async with sessions() as db:
                try:
                    return await reserve_download(db)
                except HTTPException as error:
                    return error.status_code

        results = await asyncio.gather(reserve(), reserve(), reserve())
        assert results.count(429) == 2
        async with sessions() as db:
            stats = await public_stats(db)
            assert stats.remaining_downloads == 0
            assert stats.downloads_today == 19
    finally:
        await engine.dispose()
