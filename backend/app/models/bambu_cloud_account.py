from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.core.database import Base


class BambuCloudAccount(Base):
    """A stored Bambu Cloud credential.

    ``user_id`` is nullable because installations with authentication disabled
    use one shared (global) owner; global accounts are shared MakerWorld
    connectors. Tokens are intentionally kept separate from
    ``users`` so a user can connect accounts from both Bambu regions.
    """

    __tablename__ = "bambu_cloud_accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    region: Mapped[str] = mapped_column(String(10), nullable=False, default="global")
    access_token: Mapped[str] = mapped_column(String(2000), nullable=False)
    is_default: Mapped[bool] = mapped_column(default=False, nullable=False)
    makerworld_shared: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
