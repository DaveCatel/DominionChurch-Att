import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UserAvatar(Base):
    """A member's profile photo, kept in the database rather than on the server's disk
    (hosts like Render wipe the disk on every restart)."""

    __tablename__ = "user_avatars"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )

    # random and unguessable; it is part of the photo's web address and changes with every upload
    token: Mapped[str] = mapped_column(String(40), nullable=False)

    content_type: Mapped[str] = mapped_column(String(30), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_user_avatars_token", "token", unique=True),)
