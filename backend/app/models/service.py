import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin, TimestampMixin

class ServiceTemplate(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "service_templates"

    church_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("churches.id", ondelete="CASCADE"),
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    service_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    day_of_week: Mapped[int | None] = mapped_column(
        SmallInteger,
        nullable=True,
    )

    default_start_time: Mapped[time | None] = mapped_column(
        Time,
        nullable=True,
    )

    default_end_time: Mapped[time | None] = mapped_column(
        Time,
        nullable=True,
    )

    # NONE = anyone logged in can clock in, CODE = must enter the code shown at church,
    # CODE_LOCATION = the code plus a check that the phone is at the church
    verification_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="NONE",
        server_default="NONE",
    )

    # fingerprint / face check at clock-in: OFF, IF_ENROLLED (needed only for members who
    # have set one up) or REQUIRED (everyone must set one up first)
    passkey_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="OFF",
        server_default="OFF",
    )

    is_recurring: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )

    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    church = relationship(
        "Church",
        back_populates="service_templates",
    )

    occurrences = relationship(
        "ServiceOccurrence",
        back_populates="service_template",
        cascade="all, delete-orphan",
    )

    participants = relationship(
        "ServiceParticipant",
        back_populates="service_template",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint(
            "day_of_week IS NULL OR "
            "(day_of_week >= 0 AND day_of_week <= 6)",
            name="ck_service_day_of_week",
        ),
        Index(
            "ix_service_templates_church_id",
            "church_id",
        ),
    )


class ServiceOccurrence(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "service_occurrences"

    service_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "service_templates.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    service_date: Mapped[date] = mapped_column(
        Date,
        nullable=False,
    )

    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )

    end_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="SCHEDULED",
    )

    service_template = relationship(
        "ServiceTemplate",
        back_populates="occurrences",
    )

    attendance_records = relationship(
        "AttendanceRecord",
        back_populates="service_occurrence",
    )

    __table_args__ = (
        UniqueConstraint(
            "service_template_id",
            "service_date",
            name="uq_service_occurrence_date",
        ),
        Index(
            "ix_service_occurrences_service_date",
            "service_date",
        ),
    )


class ServiceParticipant(
    UUIDPrimaryKeyMixin,
    TimestampMixin,
    Base,
):
    __tablename__ = "service_participants"

    service_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            "service_templates.id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )

    department_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("departments.id", ondelete="CASCADE"),
        nullable=True,
    )

    service_template = relationship(
        "ServiceTemplate",
        back_populates="participants",
    )

    user = relationship("User")

    department = relationship("Department")

    __table_args__ = (
        CheckConstraint(
            "(user_id IS NOT NULL) OR "
            "(department_id IS NOT NULL)",
            name="ck_service_participant_target",
        ),
    )