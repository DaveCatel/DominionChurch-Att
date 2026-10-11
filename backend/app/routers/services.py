import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.deps import require_admin
from app.models import (
    AttendanceRecord,
    Department,
    ServiceOccurrence,
    ServiceParticipant,
    ServiceTemplate,
    User,
)
from app.schemas import (
    AttendeeOut,
    MemberAttendanceOut,
    MemberAttendanceReport,
    OccurrenceAdminOut,
    ServiceCreate,
    ServiceOut,
    ServiceUpdate,
)
from app.services.scheduling import build_occurrence, church_tz, ensure_occurrences

router = APIRouter(prefix="/services", tags=["services (admin)"])


class AttendeeRow(AttendeeOut):
    # ONLINE = the member clocked in themselves, ADMIN = marked present by an admin
    source: str
    # reasons the check-in looks doubtful (see app/services/checkin.py) and its review state
    flags: list[str] = []
    review_status: str = "OK"
    passkey_verified: bool = False


class OccurrenceStatusIn(BaseModel):
    status: Literal["SCHEDULED", "CANCELLED"]


class ManualAttendanceIn(BaseModel):
    user_id: uuid.UUID


# ---------- helpers ----------
def _owned_service(db: Session, admin: User, service_id: uuid.UUID) -> ServiceTemplate:
    template = db.get(ServiceTemplate, service_id)
    if template is None or template.church_id != admin.church_id:
        raise HTTPException(404, "Service not found")
    return template


def _service_views(db: Session, templates: list[ServiceTemplate]) -> list[ServiceOut]:
    """ServiceOut for each template, plus its date span and total clock-ins."""
    ids = [t.id for t in templates]
    spans: dict[uuid.UUID, tuple[date, date]] = {}
    counts: dict[uuid.UUID, int] = {}
    restricted: dict[uuid.UUID, list[uuid.UUID]] = {}
    if ids:
        for tid, did in db.execute(
            select(ServiceParticipant.service_template_id, ServiceParticipant.department_id).where(
                ServiceParticipant.service_template_id.in_(ids),
                ServiceParticipant.department_id.is_not(None),
            )
        ):
            restricted.setdefault(tid, []).append(did)
        for tid, first, last in db.execute(
            select(
                ServiceOccurrence.service_template_id,
                func.min(ServiceOccurrence.service_date),
                func.max(ServiceOccurrence.service_date),
            )
            .where(ServiceOccurrence.service_template_id.in_(ids))
            .group_by(ServiceOccurrence.service_template_id)
        ):
            spans[tid] = (first, last)
        for tid, n in db.execute(
            select(ServiceOccurrence.service_template_id, func.count(AttendanceRecord.id))
            .select_from(ServiceOccurrence)
            .join(AttendanceRecord, AttendanceRecord.service_occurrence_id == ServiceOccurrence.id)
            .where(ServiceOccurrence.service_template_id.in_(ids))
            .group_by(ServiceOccurrence.service_template_id)
        ):
            counts[tid] = n
    views = []
    for t in templates:
        out = ServiceOut.model_validate(t)
        if not t.is_recurring and t.id in spans:
            out.first_date, out.last_date = spans[t.id]
        out.attendance_count = counts.get(t.id, 0)
        out.department_ids = restricted.get(t.id, [])
        views.append(out)
    return views


def _set_departments(
    db: Session, church_id: uuid.UUID, template: ServiceTemplate, department_ids: list[uuid.UUID]
) -> None:
    """Replace the departments this service is restricted to ([] = open to everyone).
    Rows that name individual people are left alone."""
    wanted = list(dict.fromkeys(department_ids))
    if wanted:
        found = set(
            db.scalars(
                select(Department.id).where(
                    Department.id.in_(wanted), Department.church_id == church_id
                )
            )
        )
        if len(found) != len(wanted):
            raise HTTPException(400, "One of the selected departments does not exist")
    current = {
        p.department_id: p
        for p in db.scalars(
            select(ServiceParticipant).where(
                ServiceParticipant.service_template_id == template.id,
                ServiceParticipant.department_id.is_not(None),
            )
        )
    }
    for did, row in current.items():
        if did not in wanted:
            db.delete(row)
    for did in wanted:
        if did not in current:
            db.add(ServiceParticipant(service_template_id=template.id, department_id=did))


def _attended_ids(db: Session, occurrence_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    if not occurrence_ids:
        return set()
    return set(
        db.scalars(
            select(AttendanceRecord.service_occurrence_id).where(
                AttendanceRecord.service_occurrence_id.in_(occurrence_ids)
            )
        )
    )


def _drop_unattended_upcoming(db: Session, template: ServiceTemplate, today: date) -> None:
    """Weekly service whose schedule changed: remove today's and later sessions nobody has
    clocked in to; ensure_occurrences then recreates them with the new day and time."""
    occs = db.scalars(
        select(ServiceOccurrence).where(
            ServiceOccurrence.service_template_id == template.id,
            ServiceOccurrence.service_date >= today,
            ServiceOccurrence.status != "CANCELLED",  # keep weeks the admin cancelled
        )
    ).all()
    attended = _attended_ids(db, [o.id for o in occs])
    for o in occs:
        if o.id not in attended:
            db.delete(o)


def _resync_event(db: Session, template: ServiceTemplate, data: dict, tz, today: date) -> None:
    """One-off event: apply a new date range and/or new times to its sessions."""
    occs = db.scalars(
        select(ServiceOccurrence).where(ServiceOccurrence.service_template_id == template.id)
    ).all()
    have = {o.service_date: o for o in occs}
    attended = _attended_ids(db, [o.id for o in occs])

    wanted = set(have)
    if ("start_date" in data or "end_date" in data) and have:
        first = data.get("start_date") or min(have)
        last = (data["end_date"] or first) if "end_date" in data else max(have)
        if last < first:
            raise HTTPException(400, "End date must not be before the start date")
        if (last - first).days > 30:
            raise HTTPException(400, "An event can span at most 31 days")
        wanted = {first + timedelta(days=i) for i in range((last - first).days + 1)}
        for day, o in have.items():
            if day not in wanted and o.id in attended:
                raise HTTPException(
                    409, f"People already clocked in on {day:%d %b %Y}, so that day cannot be removed"
                )
        for day, o in have.items():
            if day not in wanted:
                db.delete(o)
        for day in sorted(wanted - set(have)):
            db.add(build_occurrence(template, day, tz))

    # new times for the sessions that are still to come and have no attendance yet
    for day, o in have.items():
        if day in wanted and day >= today and o.id not in attended:
            fresh = build_occurrence(template, day, tz)
            o.start_time, o.end_time = fresh.start_time, fresh.end_time


# ---------- services: CRUD ----------
@router.get("", response_model=list[ServiceOut])
def list_services(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    templates = db.scalars(
        select(ServiceTemplate)
        .where(ServiceTemplate.church_id == admin.church_id)
        .order_by(ServiceTemplate.created_at.desc())
    ).all()
    return _service_views(db, list(templates))


@router.post("", response_model=ServiceOut, status_code=201)
def create_service(
    body: ServiceCreate, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    church = admin.church
    tz = church_tz(church)
    template = ServiceTemplate(
        church_id=church.id,
        name=body.name.strip(),
        description=body.description,
        service_type=body.service_type,
        day_of_week=body.day_of_week if body.is_recurring else None,
        default_start_time=body.start_time,
        default_end_time=body.end_time,
        is_recurring=body.is_recurring,
        verification_mode=body.verification_mode,
        passkey_mode=body.passkey_mode,
        created_by=admin.id,
    )
    db.add(template)
    db.flush()
    _set_departments(db, church.id, template, body.department_ids)

    if not body.is_recurring:
        day = body.start_date
        while day <= body.end_date:
            db.add(build_occurrence(template, day, tz))
            day += timedelta(days=1)
    db.commit()

    if body.is_recurring:
        today = datetime.now(tz).date()
        ensure_occurrences(db, church, today, today + timedelta(days=14))
    return _service_views(db, [template])[0]


@router.patch("/{service_id}", response_model=ServiceOut)
def update_service(
    service_id: uuid.UUID,
    body: ServiceUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    template = _owned_service(db, admin, service_id)
    data = body.model_dump(exclude_unset=True)
    for field in ("name", "service_type", "start_time", "is_active", "verification_mode", "passkey_mode"):
        if field in data and data[field] is None:
            raise HTTPException(422, f"{field} cannot be empty")

    tz = church_tz(admin.church)
    today = datetime.now(tz).date()

    if "name" in data:
        name = data["name"].strip()
        if not name:
            raise HTTPException(422, "Give the service a name")
        template.name = name
    if "description" in data:
        template.description = (data["description"] or "").strip() or None
    if "service_type" in data:
        template.service_type = data["service_type"]
    if "is_active" in data:
        template.is_active = data["is_active"]
    if "verification_mode" in data:
        template.verification_mode = data["verification_mode"]
    if "passkey_mode" in data:
        template.passkey_mode = data["passkey_mode"]

    # schedule
    if "day_of_week" in data:
        if not template.is_recurring:
            raise HTTPException(400, "Only weekly services have a day of the week")
        if data["day_of_week"] is None:
            raise HTTPException(422, "Pick the day of the week")
    if template.is_recurring and ("start_date" in data or "end_date" in data):
        raise HTTPException(400, "Dates only apply to one-off events")

    start = data.get("start_time", template.default_start_time)
    end = data["end_time"] if "end_time" in data else template.default_end_time
    if end is not None and end <= start:
        raise HTTPException(400, "End time must be after start time")

    if data.get("department_ids") is not None:
        _set_departments(db, admin.church_id, template, data["department_ids"])

    schedule_changed = bool(
        {"day_of_week", "start_time", "end_time", "start_date", "end_date"} & data.keys()
    )
    if schedule_changed:
        template.default_start_time = start
        template.default_end_time = end
        if "day_of_week" in data:
            template.day_of_week = data["day_of_week"]
        if template.is_recurring:
            _drop_unattended_upcoming(db, template, today)
        else:
            _resync_event(db, template, data, tz, today)
    db.commit()

    if schedule_changed and template.is_recurring and template.is_active:
        ensure_occurrences(db, admin.church, today, today + timedelta(days=14))
    return _service_views(db, [template])[0]


@router.delete("/{service_id}", status_code=204)
def delete_service(
    service_id: uuid.UUID, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    template = _owned_service(db, admin, service_id)
    recorded = db.scalar(
        select(func.count(AttendanceRecord.id))
        .select_from(AttendanceRecord)
        .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
        .where(ServiceOccurrence.service_template_id == template.id)
    )
    if recorded:
        # deleting would wipe the attendance history, so only unused services can go
        raise HTTPException(
            409,
            f"This service has {recorded} attendance record(s). "
            "Deactivate it instead so the history is kept.",
        )
    db.delete(template)
    db.commit()
    return Response(status_code=204)


# ---------- attendance: who came ----------
def _attendee_row(record: AttendanceRecord, user: User) -> AttendeeRow:
    return AttendeeRow(
        user_id=user.id,
        full_name=user.full_name,
        phone=user.phone,
        email=user.email,
        clock_in=record.clock_in,
        clock_out=record.clock_out,
        source=record.clock_in_source,
        flags=[f for f in (record.verification_flags or "").split(",") if f],
        review_status=record.review_status,
        passkey_verified=record.passkey_verified,
    )


def _owned_occurrence(
    db: Session, admin: User, occurrence_id: uuid.UUID
) -> tuple[ServiceOccurrence, str]:
    row = db.execute(
        select(ServiceOccurrence, ServiceTemplate.name)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(ServiceOccurrence.id == occurrence_id, ServiceTemplate.church_id == admin.church_id)
    ).first()
    if row is None:
        raise HTTPException(404, "Service not found")
    return row[0], row[1]


def _attendee_count(db: Session, occurrence_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(AttendanceRecord.id)).where(
                AttendanceRecord.service_occurrence_id == occurrence_id
            )
        )
        or 0
    )


@router.get("/occurrences", response_model=list[OccurrenceAdminOut])
def list_occurrences(
    date_from: date | None = None,
    date_to: date | None = None,
    service_id: uuid.UUID | None = None,
    limit: int = Query(300, ge=1, le=1000),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    tz = church_tz(admin.church)
    today = datetime.now(tz).date()
    ensure_occurrences(db, admin.church, today, today + timedelta(days=30))
    date_from = date_from or today - timedelta(days=30)
    date_to = date_to or today + timedelta(days=30)
    if date_from > date_to:
        raise HTTPException(400, "The start date is after the end date")

    stmt = (
        select(ServiceOccurrence, ServiceTemplate.name, func.count(AttendanceRecord.id))
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .outerjoin(
            AttendanceRecord, AttendanceRecord.service_occurrence_id == ServiceOccurrence.id
        )
        .where(
            ServiceTemplate.church_id == admin.church_id,
            ServiceOccurrence.service_date.between(date_from, date_to),
        )
        .group_by(ServiceOccurrence.id, ServiceTemplate.name)
        .order_by(ServiceOccurrence.start_time.desc())
        .limit(limit)
    )
    if service_id is not None:
        stmt = stmt.where(ServiceTemplate.id == service_id)
    rows = db.execute(stmt).all()
    return [
        OccurrenceAdminOut(
            id=o.id,
            name=name,
            service_date=o.service_date,
            start_time=o.start_time,
            end_time=o.end_time,
            status=o.status,
            attendee_count=count,
        )
        for o, name, count in rows
    ]


@router.get("/occurrences/{occurrence_id}/attendance", response_model=list[AttendeeRow])
def occurrence_attendance(
    occurrence_id: uuid.UUID, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    owned = db.scalar(
        select(ServiceOccurrence.id)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(ServiceOccurrence.id == occurrence_id, ServiceTemplate.church_id == admin.church_id)
    )
    if owned is None:
        raise HTTPException(404, "Service not found")
    rows = db.execute(
        select(AttendanceRecord, User)
        .join(User, User.id == AttendanceRecord.user_id)
        .where(AttendanceRecord.service_occurrence_id == occurrence_id)
        .order_by(AttendanceRecord.clock_in)
    ).all()
    return [
        _attendee_row(r, u)
        for r, u in rows
    ]


@router.get("/attendance/members", response_model=MemberAttendanceReport)
def attended_members(
    service_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Every member who attended a service (or any service) in a period, with how many
    sessions they came to. Leave the dates empty for 'ever'."""
    today = datetime.now(church_tz(admin.church)).date()
    end = min(date_to, today) if date_to else today
    if date_from and date_from > end:
        raise HTTPException(400, "The start date is after the end date")

    conds = [
        ServiceTemplate.church_id == admin.church_id,
        ServiceOccurrence.service_date <= end,
        ServiceOccurrence.status != "CANCELLED",
    ]
    if date_from:
        conds.append(ServiceOccurrence.service_date >= date_from)
    if service_id is not None:
        conds.append(ServiceTemplate.id == service_id)

    sessions = db.scalar(
        select(func.count(ServiceOccurrence.id))
        .select_from(ServiceOccurrence)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(*conds)
    )
    rows = db.execute(
        select(
            User.id,
            User.full_name,
            User.phone,
            User.email,
            func.count(AttendanceRecord.id),
            func.max(ServiceOccurrence.service_date),
        )
        .select_from(AttendanceRecord)
        .join(User, User.id == AttendanceRecord.user_id)
        .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(*conds)
        .group_by(User.id)
        .order_by(func.count(AttendanceRecord.id).desc(), func.lower(User.full_name))
    ).all()
    return MemberAttendanceReport(
        sessions=sessions or 0,
        members=[
            MemberAttendanceOut(
                user_id=uid,
                full_name=name,
                phone=phone,
                email=email,
                times_attended=n,
                last_attended=last,
            )
            for uid, name, phone, email, n, last in rows
        ],
    )


@router.patch("/occurrences/{occurrence_id}", response_model=OccurrenceAdminOut)
def set_occurrence_status(
    occurrence_id: uuid.UUID,
    body: OccurrenceStatusIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Cancel one session (a holiday, say) or bring a cancelled one back. The rest of
    the service is untouched, and members stop seeing a cancelled session."""
    occ, name = _owned_occurrence(db, admin, occurrence_id)
    count = _attendee_count(db, occ.id)
    if body.status == "CANCELLED" and count:
        raise HTTPException(
            409, f"{count} people are already marked present. Remove their attendance first."
        )
    occ.status = body.status
    db.commit()
    return OccurrenceAdminOut(
        id=occ.id,
        name=name,
        service_date=occ.service_date,
        start_time=occ.start_time,
        end_time=occ.end_time,
        status=occ.status,
        attendee_count=count,
    )


@router.post(
    "/occurrences/{occurrence_id}/attendance", response_model=AttendeeRow, status_code=201
)
def mark_present(
    occurrence_id: uuid.UUID,
    body: ManualAttendanceIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Mark a member present, for people who could not clock in themselves."""
    occ, _ = _owned_occurrence(db, admin, occurrence_id)
    if occ.status == "CANCELLED":
        raise HTTPException(400, "This session was cancelled. Restore it first.")
    member = db.get(User, body.user_id)
    if member is None or member.church_id != admin.church_id or not member.is_active:
        raise HTTPException(404, "Member not found")
    if db.scalar(
        select(AttendanceRecord.id).where(
            AttendanceRecord.user_id == member.id,
            AttendanceRecord.service_occurrence_id == occ.id,
        )
    ):
        raise HTTPException(409, f"{member.full_name} is already marked present")

    now = datetime.now(timezone.utc)
    record = AttendanceRecord(
        user_id=member.id,
        service_occurrence_id=occ.id,
        # a past service is recorded at its start time, a current one at this moment
        clock_in=occ.start_time if occ.start_time <= now else now,
        clock_in_server_time=now,
        clock_in_source="ADMIN",
        sync_status="SYNCED",
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"{member.full_name} is already marked present")
    return _attendee_row(record, member)


@router.delete("/occurrences/{occurrence_id}/attendance/{user_id}", status_code=204)
def remove_attendance(
    occurrence_id: uuid.UUID,
    user_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Delete a wrong attendance record."""
    _owned_occurrence(db, admin, occurrence_id)
    record = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.user_id == user_id,
            AttendanceRecord.service_occurrence_id == occurrence_id,
        )
    )
    if record is None:
        raise HTTPException(404, "No attendance record for this member")
    db.delete(record)
    db.commit()
    return Response(status_code=204)
