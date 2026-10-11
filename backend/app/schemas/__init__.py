import re
import uuid
from datetime import date, datetime, time
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    field_validator,
    model_validator,
)

from app.models import User


def normalize_phone(value: str) -> str:
    return re.sub(r"[^\d+]", "", value)


def _check_password(value: str) -> str:
    if len(value.encode()) > 72:
        raise ValueError("Password is too long (max 72 bytes)")
    return value


# ---------- auth / users ----------
class SignupIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: EmailStr
    phone: str = Field(max_length=30)
    password: str = Field(min_length=8)
    # optional: departments the person asks to join (an admin approves each one)
    department_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = normalize_phone(v)
        if len(re.sub(r"\D", "", v)) < 7:
            raise ValueError("Enter a valid phone number")
        return v

    _pw = field_validator("password")(_check_password)


class LoginIn(BaseModel):
    identifier: str = Field(min_length=3)  # email or phone
    password: str


class RefreshIn(BaseModel):
    refresh_token: str


class DepartmentOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None


class DepartmentAdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    is_active: bool


class DepartmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class DepartmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    is_active: bool | None = None


class MembershipAdminOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    department_id: uuid.UUID
    department_name: str
    status: str
    is_primary: bool
    joined_at: datetime
    reviewed_at: datetime | None
    reviewed_by: uuid.UUID | None


class UserOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    profile_photo_url: str | None
    role: str
    timezone: str


def user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        full_name=u.full_name,
        email=u.email,
        phone=u.phone,
        profile_photo_url=u.profile_photo_url,
        role=u.role.name,
        timezone=u.church.timezone,
    )


class AuthOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


class TokensOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = normalize_phone(v)
        if len(re.sub(r"\D", "", v)) < 7:
            raise ValueError("Enter a valid phone number")
        return v


# ---------- services ----------
class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    service_type: Literal["SERVICE", "MEETING", "EVENT"] = "SERVICE"
    is_recurring: bool = True
    day_of_week: int | None = Field(default=None, ge=0, le=6)  # 0 = Monday ... 6 = Sunday
    start_time: time
    end_time: time | None = None
    # one-off events (e.g. a youth conference): first and last day
    start_date: date | None = None
    end_date: date | None = None
    # empty = open to everyone; otherwise only active members of these departments
    department_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    # how clock-in is checked: NONE, CODE (the code on the screen at church), CODE_LOCATION
    verification_mode: Literal["NONE", "CODE", "CODE_LOCATION"] = "CODE_LOCATION"
    passkey_mode: Literal["OFF", "IF_ENROLLED", "REQUIRED"] = "OFF"

    @model_validator(mode="after")
    def _check(self):
        if self.end_time is not None and self.end_time <= self.start_time:
            raise ValueError("End time must be after start time")
        if self.is_recurring:
            if self.day_of_week is None:
                raise ValueError("Pick the day of the week for a recurring service")
        else:
            if self.start_date is None:
                raise ValueError("Pick a date for a one-off event")
            if self.end_date is None:
                self.end_date = self.start_date
            if self.end_date < self.start_date:
                raise ValueError("End date must not be before the start date")
            if (self.end_date - self.start_date).days > 30:
                raise ValueError("An event can span at most 31 days")
        return self


class ServiceUpdate(BaseModel):
    """Every field is optional; only the ones sent are changed."""

    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    service_type: Literal["SERVICE", "MEETING", "EVENT"] | None = None
    is_active: bool | None = None
    # schedule: changing these regenerates upcoming sessions nobody has clocked in to yet
    day_of_week: int | None = Field(default=None, ge=0, le=6)  # recurring services only
    start_time: time | None = None
    end_time: time | None = None  # send null to remove the end time
    start_date: date | None = None  # one-off events only
    end_date: date | None = None
    # replaces who may attend; an empty list opens the service to everyone
    department_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    verification_mode: Literal["NONE", "CODE", "CODE_LOCATION"] | None = None
    passkey_mode: Literal["OFF", "IF_ENROLLED", "REQUIRED"] | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    description: str | None
    service_type: str
    is_recurring: bool
    day_of_week: int | None
    default_start_time: time | None
    default_end_time: time | None
    is_active: bool
    # filled in by the admin endpoints
    department_ids: list[uuid.UUID] = Field(default_factory=list)  # empty = open to everyone
    verification_mode: str = "NONE"
    passkey_mode: str = "OFF"
    first_date: date | None = None  # one-off events: first and last day
    last_date: date | None = None
    attendance_count: int = 0  # clock-ins ever recorded; above 0 the service cannot be deleted


class OccurrenceAdminOut(BaseModel):
    id: uuid.UUID
    name: str
    service_date: date
    start_time: datetime
    end_time: datetime | None
    status: str
    attendee_count: int


class AttendeeOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    clock_in: datetime
    clock_out: datetime | None


# ---------- attendance ----------
class ClockIn(BaseModel):
    occurrence_id: uuid.UUID
    device_time: datetime | None = None
    # proof of presence, needed when the service checks it
    code: str | None = Field(default=None, max_length=20)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=1_000_000)
    device_token: str | None = Field(default=None, max_length=100)
    # the fingerprint / face confirmation from the phone (see app/services/passkeys.py)
    passkey: dict | None = None


class ServiceCard(BaseModel):
    occurrence_id: uuid.UUID
    name: str
    description: str | None
    service_type: str
    service_date: date
    start_time: datetime
    end_time: datetime | None
    opens_at: datetime
    # upcoming | open | clocked_in | completed | missed
    state: str
    clock_in: datetime | None
    clock_out: datetime | None
    # tells the app whether to ask for the check-in code and the location
    verification_mode: str = "NONE"
    # NONE: nothing to do, ASSERT: confirm with fingerprint/face, ENROLL: set one up first
    passkey_step: str = "NONE"


class TodayOut(BaseModel):
    server_time: datetime
    timezone: str
    today: list[ServiceCard]
    upcoming: list[ServiceCard]


class HistoryItem(BaseModel):
    occurrence_id: uuid.UUID
    name: str
    service_date: date
    clock_in: datetime
    clock_out: datetime | None


class MemberAttendanceOut(BaseModel):
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    times_attended: int
    last_attended: date


class MemberAttendanceReport(BaseModel):
    # sessions of the chosen service held in the period (counted up to today)
    sessions: int
    members: list[MemberAttendanceOut]


# ---------- a member's own department memberships ----------
class MyDepartmentOut(BaseModel):
    department_id: uuid.UUID
    name: str
    description: str | None
    status: Literal["PENDING", "ACTIVE", "REJECTED"]


class DepartmentRequestIn(BaseModel):
    department_ids: list[uuid.UUID] = Field(min_length=1, max_length=20)
