import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.deps import require_admin
from app.models import (
    AttendanceRecord,
    ServiceOccurrence,
    ServiceTemplate,
    User,
    UserDevice,
)
from app.services.checkin import WINDOW_SECONDS, current_code

router = APIRouter(prefix="/checkin", tags=["check-in (admin)"])


# ---------- shapes ----------
class CodeOut(BaseModel):
    code: str
    seconds_left: int
    window_seconds: int
    service_name: str
    service_date: date
    start_time: datetime
    verification_mode: str
    passkey_mode: str  # REQUIRED = fingerprint only: the code is not accepted
    attendee_count: int


class ChurchLocation(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    radius_m: int = Field(default=200, ge=20, le=5000)

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.latitude is None) != (self.longitude is None):
            raise ValueError("Give both latitude and longitude, or neither")
        return self


class ReviewItem(BaseModel):
    occurrence_id: uuid.UUID
    service_name: str
    service_date: date
    user_id: uuid.UUID
    full_name: str
    phone: str | None
    clock_in: datetime
    flags: list[str]
    distance_m: int | None
    accuracy_m: float | None
    ip_address: str | None
    device_name: str | None


class ReviewKey(BaseModel):
    occurrence_id: uuid.UUID
    user_id: uuid.UUID


class ReviewApproveIn(BaseModel):
    items: list[ReviewKey] = Field(min_length=1, max_length=500)


# ---------- the code on the projector ----------
@router.get("/occurrences/{occurrence_id}/code", response_model=CodeOut)
def live_code(
    occurrence_id: uuid.UUID, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """What the check-in screen at church shows right now. It changes every 30 seconds."""
    row = db.execute(
        select(ServiceOccurrence, ServiceTemplate)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(ServiceOccurrence.id == occurrence_id, ServiceTemplate.church_id == admin.church_id)
    ).first()
    if row is None:
        raise HTTPException(404, "Service not found")
    occ, template = row
    if occ.status == "CANCELLED":
        raise HTTPException(400, "This session was cancelled")

    code, seconds_left = current_code(occ.id)
    attendees = (
        db.scalar(
            select(func.count(AttendanceRecord.id)).where(
                AttendanceRecord.service_occurrence_id == occ.id
            )
        )
        or 0
    )
    return CodeOut(
        code=code,
        seconds_left=seconds_left,
        window_seconds=WINDOW_SECONDS,
        service_name=template.name,
        service_date=occ.service_date,
        start_time=occ.start_time,
        verification_mode=template.verification_mode,
        passkey_mode=template.passkey_mode,
        attendee_count=attendees,
    )


# ---------- where the church is ----------
@router.get("/church-location", response_model=ChurchLocation)
def get_church_location(admin: User = Depends(require_admin)):
    church = admin.church
    return ChurchLocation(
        latitude=church.latitude, longitude=church.longitude, radius_m=church.geofence_radius_m
    )


@router.put("/church-location", response_model=ChurchLocation)
def set_church_location(
    body: ChurchLocation, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    church = admin.church
    church.latitude = body.latitude
    church.longitude = body.longitude
    church.geofence_radius_m = body.radius_m
    db.commit()
    return ChurchLocation(
        latitude=church.latitude, longitude=church.longitude, radius_m=church.geofence_radius_m
    )


# ---------- check-ins that look doubtful ----------
def _review_base():
    return (
        select(AttendanceRecord)
        .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(AttendanceRecord.review_status == "NEEDS_REVIEW")
    )


@router.get("/review/count")
def review_count(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    count = db.scalar(
        select(func.count(AttendanceRecord.id))
        .select_from(AttendanceRecord)
        .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(
            AttendanceRecord.review_status == "NEEDS_REVIEW",
            ServiceTemplate.church_id == admin.church_id,
        )
    )
    return {"count": count or 0}


@router.get("/review", response_model=list[ReviewItem])
def review_list(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.execute(
        select(
            AttendanceRecord,
            User,
            ServiceOccurrence,
            ServiceTemplate.name,
            UserDevice.device_name,
        )
        .join(User, User.id == AttendanceRecord.user_id)
        .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .outerjoin(UserDevice, UserDevice.id == AttendanceRecord.device_id)
        .where(
            AttendanceRecord.review_status == "NEEDS_REVIEW",
            ServiceTemplate.church_id == admin.church_id,
        )
        .order_by(AttendanceRecord.clock_in.desc())
        .limit(300)
    ).all()
    return [
        ReviewItem(
            occurrence_id=occ.id,
            service_name=service_name,
            service_date=occ.service_date,
            user_id=user.id,
            full_name=user.full_name,
            phone=user.phone,
            clock_in=record.clock_in,
            flags=[f for f in (record.verification_flags or "").split(",") if f],
            distance_m=record.distance_m,
            accuracy_m=record.accuracy_m,
            ip_address=record.ip_address,
            device_name=device_name,
        )
        for record, user, occ, service_name, device_name in rows
    ]


@router.post("/review/approve")
def review_approve(
    body: ReviewApproveIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """The admin looked and the check-in is fine. (To reject one, remove the attendance
    from the Attendance tab.)"""
    approved = 0
    for key in body.items:
        record = db.scalar(
            _review_base().where(
                AttendanceRecord.user_id == key.user_id,
                AttendanceRecord.service_occurrence_id == key.occurrence_id,
                ServiceTemplate.church_id == admin.church_id,
            )
        )
        if record is not None:
            record.review_status = "APPROVED"
            approved += 1
    db.commit()
    return {"approved": approved}
