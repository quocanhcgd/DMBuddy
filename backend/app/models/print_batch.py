from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.core.database import Base


class PrintBatch(Base):
    """Batch grouping for multiple queue items created from the same file."""

    __tablename__ = "print_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))

    # Source file (one of these)
    archive_id: Mapped[int | None] = mapped_column(ForeignKey("print_archives.id", ondelete="SET NULL"), nullable=True)
    library_file_id: Mapped[int | None] = mapped_column(
        ForeignKey("library_files.id", ondelete="SET NULL"), nullable=True
    )

    # Total requested quantity (for display — actual items may differ if cancelled)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    # Status: active, completed, cancelled
    status: Mapped[str] = mapped_column(String(20), default="active")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # User tracking
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    archive: Mapped["PrintArchive | None"] = relationship()
    library_file: Mapped["LibraryFile | None"] = relationship()
    created_by: Mapped["User | None"] = relationship()
    queue_items: Mapped[list["PrintQueueItem"]] = relationship(back_populates="batch")


from backend.app.models.archive import PrintArchive  # noqa: E402
from backend.app.models.library import LibraryFile  # noqa: E402
from backend.app.models.print_queue import PrintQueueItem  # noqa: E402
from backend.app.models.user import User  # noqa: E402
