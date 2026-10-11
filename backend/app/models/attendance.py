import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin


class AttendanceRecord(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "attendance_records"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    service_occurrence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "service_occurrences.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    device_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "user_devices.id",
            ondelete="SET NULL",
        ),
        nullable=True,
    )

    clock_in: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    clock_out: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    clock_in_source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    clock_out_source: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
    )

    clock_in_device_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    clock_out_device_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    clock_in_server_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    clock_out_server_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # what the phone reported at clock-in (only when the service checks location)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)

    # comma separated reasons an admin should look at this record, for example
    # "FAR_FROM_VENUE,NEW_DEVICE"; review_status is OK, NEEDS_REVIEW or APPROVED
    verification_flags: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # true when the member confirmed this check-in with their fingerprint / face
    passkey_verified: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="OK",
        server_default="OK",
    )

    sync_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="SYNCED",
    )

    user = relationship(
        "User",
        back_populates="attendance_records",
    )

    service_occurrence = relationship(
        "ServiceOccurrence",
        back_populates="attendance_records",
    )

    device = relationship(
        "UserDevice",
        back_populates="attendance_records",
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "service_occurrence_id",
            name="uq_attendance_user_occurrence",
        ),
        Index(
            "ix_attendance_user_id",
            "user_id",
        ),
        Index(
            "ix_attendance_occurrence_id",
            "service_occurrence_id",
        ),
        Index(
            "ix_attendance_clock_in",
            "clock_in",
        ),
    )