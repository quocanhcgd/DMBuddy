from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import case, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.makerworld_public import MakerWorldPublicCounter, MakerWorldPublicDownload
from backend.app.schemas.makerworld import MakerWorldPublicStats

DAILY_DOWNLOAD_LIMIT = 20
VIETNAM_TIME = timezone(timedelta(hours=7))


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _ensure_counter(db: AsyncSession, day: str):
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert

    await db.execute(
        insert(MakerWorldPublicCounter)
        .values(key="china", visits=0, total_downloads=0, daily_day=day, daily_reserved=0)
        .on_conflict_do_nothing()
    )
    await db.execute(
        update(MakerWorldPublicCounter)
        .where(
            MakerWorldPublicCounter.key == "china",
            MakerWorldPublicCounter.daily_day != day,
        )
        .values(daily_day=day, daily_reserved=0)
    )
    counter = await db.scalar(select(MakerWorldPublicCounter).where(MakerWorldPublicCounter.key == "china"))
    existing_today = (
        await db.scalar(
            select(func.count())
            .select_from(MakerWorldPublicDownload)
            .where(
                MakerWorldPublicDownload.day == day,
                MakerWorldPublicDownload.completed.is_(True),
            )
        )
        or 0
    )
    if counter.daily_reserved == 0 and existing_today:
        await db.execute(
            update(MakerWorldPublicCounter)
            .where(MakerWorldPublicCounter.key == "china")
            .values(daily_reserved=existing_today)
        )
        counter.daily_reserved = existing_today
    return counter


async def public_stats(db: AsyncSession) -> MakerWorldPublicStats:
    now = _now()
    local_now = now.astimezone(VIETNAM_TIME)
    day = local_now.date().isoformat()
    midnight = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    counter = await _ensure_counter(db, day)
    total_downloads = await db.scalar(
        select(func.count()).select_from(MakerWorldPublicDownload).where(MakerWorldPublicDownload.completed.is_(True))
    )
    downloads_today = (
        await db.scalar(
            select(func.count())
            .select_from(MakerWorldPublicDownload)
            .where(
                MakerWorldPublicDownload.day == day,
                MakerWorldPublicDownload.completed.is_(True),
            )
        )
        or 0
    )
    return MakerWorldPublicStats(
        total_visits=counter.visits,
        total_downloads=total_downloads or 0,
        downloads_today=downloads_today,
        daily_limit=DAILY_DOWNLOAD_LIMIT,
        remaining_downloads=max(0, DAILY_DOWNLOAD_LIMIT - counter.daily_reserved),
        resets_at=midnight,
    )


async def record_visit(db: AsyncSession) -> MakerWorldPublicStats:
    local_now = _now().astimezone(VIETNAM_TIME)
    await _ensure_counter(db, local_now.date().isoformat())
    await db.execute(
        update(MakerWorldPublicCounter)
        .where(MakerWorldPublicCounter.key == "china")
        .values(visits=MakerWorldPublicCounter.visits + 1)
    )
    await db.commit()
    return await public_stats(db)


async def reserve_download(db: AsyncSession) -> str:
    now = _now()
    day = now.astimezone(VIETNAM_TIME).date().isoformat()
    await _ensure_counter(db, day)
    expired = (
        await db.scalar(
            select(func.count())
            .select_from(MakerWorldPublicDownload)
            .where(
                MakerWorldPublicDownload.day == day,
                MakerWorldPublicDownload.completed.is_(False),
                MakerWorldPublicDownload.expires_at <= now.replace(tzinfo=None),
            )
        )
        or 0
    )
    if expired:
        await db.execute(
            delete(MakerWorldPublicDownload).where(
                MakerWorldPublicDownload.day == day,
                MakerWorldPublicDownload.completed.is_(False),
                MakerWorldPublicDownload.expires_at <= now.replace(tzinfo=None),
            )
        )
        await db.execute(
            update(MakerWorldPublicCounter)
            .where(MakerWorldPublicCounter.key == "china")
            .values(
                daily_reserved=case(
                    (
                        MakerWorldPublicCounter.daily_reserved > expired,
                        MakerWorldPublicCounter.daily_reserved - expired,
                    ),
                    else_=0,
                ),
            )
        )
        await _ensure_counter(db, day)
    result = await db.execute(
        update(MakerWorldPublicCounter)
        .where(
            MakerWorldPublicCounter.key == "china",
            MakerWorldPublicCounter.daily_day == day,
            MakerWorldPublicCounter.daily_reserved < DAILY_DOWNLOAD_LIMIT,
        )
        .values(daily_reserved=MakerWorldPublicCounter.daily_reserved + 1)
    )
    if result.rowcount != 1:
        await db.rollback()
        local_now = now.astimezone(VIETNAM_TIME)
        midnight = (local_now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        retry_after = max(1, int((midnight - now).total_seconds()))
        raise HTTPException(
            status_code=429,
            detail="Trang đã đạt giới hạn 20 lượt tải hôm nay. Vui lòng quay lại sau 00:00 giờ Việt Nam.",
            headers={"Retry-After": str(retry_after)},
        )
    reservation_id = str(uuid4())
    db.add(
        MakerWorldPublicDownload(
            id=reservation_id,
            day=day,
            completed=False,
            expires_at=(now + timedelta(hours=1)).replace(tzinfo=None),
        )
    )
    await db.commit()
    return reservation_id


async def finish_download(db: AsyncSession, reservation_id: str, *, success: bool) -> None:
    if success:
        await db.execute(
            update(MakerWorldPublicDownload)
            .where(
                MakerWorldPublicDownload.id == reservation_id,
            )
            .values(completed=True)
        )
        await db.execute(
            update(MakerWorldPublicCounter)
            .where(MakerWorldPublicCounter.key == "china")
            .values(
                total_downloads=MakerWorldPublicCounter.total_downloads + 1,
            )
        )
    else:
        await db.execute(delete(MakerWorldPublicDownload).where(MakerWorldPublicDownload.id == reservation_id))
        await db.execute(
            update(MakerWorldPublicCounter)
            .where(MakerWorldPublicCounter.key == "china")
            .values(
                daily_reserved=case(
                    (MakerWorldPublicCounter.daily_reserved > 0, MakerWorldPublicCounter.daily_reserved - 1),
                    else_=0,
                ),
            )
        )
    await db.commit()
