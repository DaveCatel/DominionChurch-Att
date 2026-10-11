import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Passkey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A member's fingerprint / face check-in on one phone. Only the public half of the
    key is stored; the private half never leaves the phone."""

    __tablename__ = "passkeys"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # base64url of the id the phone gave the key
    credential_id: Mapped[str] = mapped_column(String(512), nullable=False)

    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)  # DER
    alg: Mapped[int] = mapped_column(Integer, nullable=False)  # -7 ES256, -257 RS256
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_passkeys_credential_id", "credential_id", unique=True),
        Index("ix_passkeys_user_id", "user_id"),
    )
