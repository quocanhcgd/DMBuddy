from datetime import datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class MakerWorldPublicCounter(Base):
    __tablename__ = "makerworld_public_counters"

    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    visits: Mapped[int] = mapped_column(Integer, default=0)
    total_downloads: Mapped[int] = mapped_column(Integer, default=0)
    daily_day: Mapped[str] = mapped_column(String(10), default="")
    daily_reserved: Mapped[int] = mapped_column(Integer, default=0)


class MakerWorldPublicDownload(Base):
    __tablename__ = "makerworld_public_downloads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    day: Mapped[str] = mapped_column(String(10), index=True)
    completed: Mapped[bool] = mapped_column(default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
