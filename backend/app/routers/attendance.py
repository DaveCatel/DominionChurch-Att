import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.deps import get_current_user
from app.models import (
    AttendanceRecord,
    ServiceOccurrence,
    ServiceParticipant,
    ServiceTemplate,
    Department,
    User,
    Passkey,
    UserDepartment,
    UserDevice,
)
from app.core.config import settings
from app.core.ratelimit import code_failures, passkey_failures
from app.schemas import ClockIn, HistoryItem, ServiceCard, TodayOut
from app.services.checkin import (
    FLAG_FAR_FROM_VENUE,
    FLAG_GEOFENCE_UNCERTAIN,
    FLAG_LOW_ACCURACY,
    FLAG_NEW_DEVICE,
    FLAG_NO_DEVICE_ID,
    FLAG_NO_LOCATION,
    SETUP_MESSAGE,
    check_location,
    checkin_methods,
    choose_factor,
    clock_out_needs_passkey,
    clock_out_time_error,
    clock_out_window,
    code_is_valid,
    location_error,
    needs_passkey_setup,
)
from app.services.passkeys import PasskeyError, StoredPasskey, verify_assertion
from app.services.scheduling import attendance_state, church_tz, ensure_occurrences, window

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _has_passkey(db: Session, user: User) -> bool:
    return bool(db.scalar(select(func.count(Passkey.id)).where(Passkey.user_id == user.id)))


def _card(occ, template, record, now, tz, has_passkey: bool = False) -> ServiceCard:
    opens, _ = window(occ, tz)
    verified = template.verification_mode != "NONE"  # the service checks where members are
    out_opens, out_closes = clock_out_window(
        occ.end_time, settings.CHECKOUT_OPENS_MINUTES_BEFORE_END, settings.CHECKOUT_CLOSES_MINUTES_AFTER_END
    )
    return ServiceCard(
        occurrence_id=occ.id,
        name=template.name,
        description=template.description,
        service_type=template.service_type,
        service_date=occ.service_date,
        start_time=occ.start_time,
        end_time=occ.end_time,
        opens_at=opens,
        clock_out_opens_at=out_opens,
        clock_out_closes_at=out_closes,
        state=attendance_state(occ, record, now, tz),
        clock_in=record.clock_in if record else None,
        clock_out=record.clock_out if record else None,
        verification_mode=template.verification_mode,
        checkin_methods=checkin_methods(template.passkey_mode, has_passkey) if verified else [],
        needs_passkey_setup=verified and needs_passkey_setup(template.passkey_mode, has_passkey),
        clock_out_passkey=verified
        and clock_out_needs_passkey(template.passkey_mode, bool(record and record.passkey_verified)),
    )


def _load(db: Session, user: User, occurrence_id: uuid.UUID):
    row = db.execute(
        select(ServiceOccurrence, ServiceTemplate)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(
            ServiceOccurrence.id == occurrence_id,
            ServiceTemplate.church_id == user.church_id,
            ServiceTemplate.is_active.is_(True),
            ServiceOccurrence.status != "CANCELLED",
        )
    ).first()
    if row is None:
        raise HTTPException(404, "Service not found")
    return row


def _is_service_eligible(
    db: Session, user: User, template: ServiceTemplate
) -> bool:
    participant_exists = db.scalar(
        select(ServiceParticipant.id)
        .where(ServiceParticipant.service_template_id == template.id)
        .limit(1)
    ) is not None

    # No participant rows means the service is open to all eligible church users.
    if not participant_exists:
        return True

    direct_match = select(ServiceParticipant.id).where(
        ServiceParticipant.service_template_id == template.id,
        ServiceParticipant.user_id == user.id,
    ).exists()

    active_department_match = (
        select(ServiceParticipant.id)
        .join(
            UserDepartment,
            UserDepartment.department_id == ServiceParticipant.department_id,
        )
        .join(
            Department,
            Department.id == UserDepartment.department_id,
        )
        .where(
            ServiceParticipant.service_template_id == template.id,
            UserDepartment.user_id == user.id,
            UserDepartment.status == "ACTIVE",
            Department.church_id == user.church_id,
        )
        .exists()
    )

    return bool(
        db.scalar(select(or_(direct_match, active_department_match)))
    )


def _require_service_eligibility(
    db: Session, user: User, template: ServiceTemplate
) -> None:
    if not _is_service_eligible(db, user, template):
        raise HTTPException(403, "You are not eligible for this service")


def _record(db: Session, user: User, occurrence_id: uuid.UUID) -> AttendanceRecord | None:
    return db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.user_id == user.id,
            AttendanceRecord.service_occurrence_id == occurrence_id,
        )
    )


@router.get("/today", response_model=TodayOut)
def today(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    tz = church_tz(user.church)
    now = datetime.now(timezone.utc)
    today_date = now.astimezone(tz).date()
    horizon = today_date + timedelta(days=14)
    ensure_occurrences(db, user.church, today_date, horizon)

    rows = db.execute(
        select(ServiceOccurrence, ServiceTemplate)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(
            ServiceTemplate.church_id == user.church_id,
            ServiceTemplate.is_active.is_(True),
            ServiceOccurrence.status != "CANCELLED",
            ServiceOccurrence.service_date.between(today_date, horizon),
        )
        .order_by(ServiceOccurrence.start_time)
    ).all()

    rows = [(o, t) for o, t in rows if _is_service_eligible(db, user, t)]
    records = {
        r.service_occurrence_id: r
        for r in db.scalars(
            select(AttendanceRecord).where(
                AttendanceRecord.user_id == user.id,
                AttendanceRecord.service_occurrence_id.in_([o.id for o, _ in rows]),
            )
        )
    }
    has_passkey = _has_passkey(db, user)
    cards = [_card(o, t, records.get(o.id), now, tz, has_passkey) for o, t in rows]
    return TodayOut(
        server_time=now,
        timezone=str(tz),
        today=[c for c in cards if c.service_date == today_date],
        upcoming=[c for c in cards if c.service_date > today_date][:10],
    )


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def _require_valid_code(user: User, occurrence_id: uuid.UUID, code: str | None) -> None:
    """The code on the screen at church proves the person is in the room right now."""
    key = str(user.id)
    code_failures.check(key)  # 429 after too many wrong guesses
    if not (code or "").strip():
        raise HTTPException(400, "Enter the check-in code shown on the screen at church.")
    if not code_is_valid(occurrence_id, code):
        code_failures.hit(key)
        raise HTTPException(
            400, "That code is wrong or has expired. Look at the screen at church for the new one."
        )


def _assert_passkey(
    db: Session, user: User, occ: ServiceOccurrence, payload: dict, now: datetime, purpose: str
) -> None:
    """Check a fingerprint / face confirmation from the member's own phone. A friend who knows
    your password cannot pass it: the check happens on your phone and needs your fingerprint."""
    passkeys = list(db.scalars(select(Passkey).where(Passkey.user_id == user.id)))
    if not passkeys:
        raise HTTPException(400, "You have not set up fingerprint or face check-in yet.")
    key = str(user.id)
    passkey_failures.check(key)  # 429 after too many failures
    stored = {p.credential_id: StoredPasskey(p.public_key, p.alg, p.sign_count) for p in passkeys}
    try:
        result = verify_assertion(payload, purpose, user.id, occ.id, stored)
    except PasskeyError as exc:
        passkey_failures.hit(key)
        raise HTTPException(400, str(exc))
    for p in passkeys:
        if p.credential_id == result.credential_id:
            p.sign_count = result.sign_count
            p.last_used_at = now


def _identify_device(
    db: Session, user: User, occ: ServiceOccurrence, token: str | None, request: Request, now: datetime
) -> tuple[UserDevice | None, list[str]]:
    """Link the clock-in to the phone it came from.

    One phone can check in only one person per service, which stops someone from
    clocking in a friend by logging in to the friend's account on their own phone."""
    token = (token or "").strip()
    if not token:
        return None, [FLAG_NO_DEVICE_ID]

    used_for_someone_else = db.scalar(
        select(AttendanceRecord.id)
        .join(UserDevice, UserDevice.id == AttendanceRecord.device_id)
        .where(
            AttendanceRecord.service_occurrence_id == occ.id,
            UserDevice.device_identifier == token,
            AttendanceRecord.user_id != user.id,
        )
        .limit(1)
    )
    if used_for_someone_else is not None:
        raise HTTPException(
            409,
            "This phone has already been used to check in someone else for this service. "
            "Everyone must check in with their own phone. If you have no phone, ask an usher "
            "to mark you present.",
        )

    flags: list[str] = []
    device = db.scalar(
        select(UserDevice).where(
            UserDevice.user_id == user.id, UserDevice.device_identifier == token
        )
    )
    if device is None:
        known = db.scalar(select(func.count(UserDevice.id)).where(UserDevice.user_id == user.id)) or 0
        device = UserDevice(
            user_id=user.id,
            device_identifier=token,
            device_name=(request.headers.get("user-agent") or "")[:150] or None,
            platform="WEB",
            last_seen_at=now,
        )
        db.add(device)
        db.flush()
        if known:  # the very first phone is not suspicious, a second one is worth a look
            flags.append(FLAG_NEW_DEVICE)
    else:
        device.last_seen_at = now
    return device, flags


@router.post("/clock-in", response_model=ServiceCard)
def clock_in(
    body: ClockIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    occ, template = _load(db, user, body.occurrence_id)
    _require_service_eligibility(db, user, template)
    tz = church_tz(user.church)
    now = datetime.now(timezone.utc)

    if _record(db, user, occ.id) is not None:
        raise HTTPException(409, "You have already clocked in to this service")

    state = attendance_state(occ, None, now, tz)
    if state == "upcoming":
        opens, _ = window(occ, tz)
        raise HTTPException(
            400, f"Clock-in opens at {opens.astimezone(tz):%H:%M}"
        )
    if state == "missed":
        raise HTTPException(400, "This service has ended")

    # --- is this person really here, and really themselves? ---
    mode = template.verification_mode
    flags: list[str] = []
    device = None
    distance = None
    passkey_ok = False
    if mode != "NONE":
        # 1. Reject missing or clearly out-of-range locations. Uncertain readings
        #    that could still be inside are accepted and sent to admin review.
        church = user.church
        location_flags, distance = check_location(
            church.latitude,
            church.longitude,
            church.geofence_radius_m,
            body.latitude,
            body.longitude,
            body.accuracy_m,
        )
        if FLAG_NO_LOCATION in location_flags or FLAG_FAR_FROM_VENUE in location_flags:
            problem, distance = location_error(
                church.latitude,
                church.longitude,
                church.geofence_radius_m,
                body.latitude,
                body.longitude,
                body.accuracy_m,
                "check in",
            )
            if problem:
                raise HTTPException(400, problem)
        flags.extend(
            flag
            for flag in location_flags
            if flag in (FLAG_LOW_ACCURACY, FLAG_GEOFENCE_UNCERTAIN)
        )

        # 2. plus ONE confirmation: the code on the screen, or fingerprint / face,
        #    as far as this service and this member allow
        factor, problem, status_code = choose_factor(
            template.passkey_mode, _has_passkey(db, user), bool(body.passkey)
        )
        if problem:
            raise HTTPException(status_code, problem)
        if factor == "PASSKEY":
            _assert_passkey(db, user, occ, body.passkey, now, "clock_in")
            passkey_ok = True
        else:
            _require_valid_code(user, occ.id, body.code)

        # 3. which phone it came from (one phone cannot check in two people)
        device, device_flags = _identify_device(db, user, occ, body.device_token, request, now)
        # a fingerprint/face check already proved who this is, so a new phone is not suspicious
        flags += [f for f in device_flags if not (passkey_ok and f == FLAG_NEW_DEVICE)]

    record = AttendanceRecord(
        user_id=user.id,
        service_occurrence_id=occ.id,
        device_id=device.id if device else None,
        clock_in=now,
        clock_in_server_time=now,
        clock_in_device_time=body.device_time,
        clock_in_source="ONLINE",
        sync_status="SYNCED",
        # a location is only kept when the service checks it
        latitude=body.latitude if mode != "NONE" else None,
        longitude=body.longitude if mode != "NONE" else None,
        accuracy_m=body.accuracy_m if mode != "NONE" else None,
        distance_m=distance,
        ip_address=_client_ip(request) if mode != "NONE" else None,
        passkey_verified=passkey_ok,
        verification_flags=",".join(flags) or None,
        review_status="NEEDS_REVIEW" if flags else "OK",
    )
    db.add(record)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already clocked in to this service")
    return _card(occ, template, record, now, tz, _has_passkey(db, user))


@router.post("/clock-out", response_model=ServiceCard)
def clock_out(body: ClockIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    occ, template = _load(db, user, body.occurrence_id)
    _require_service_eligibility(db, user, template)
    tz = church_tz(user.church)
    now = datetime.now(timezone.utc)

    record = _record(db, user, occ.id)
    if record is None:
        raise HTTPException(400, "You have not clocked in to this service")
    if record.clock_out is not None:
        raise HTTPException(409, "You have already clocked out")

    # Clocking out proves you stayed, so it is only possible once the service has ended...
    opens, closes = clock_out_window(
        occ.end_time, settings.CHECKOUT_OPENS_MINUTES_BEFORE_END, settings.CHECKOUT_CLOSES_MINUTES_AFTER_END
    )
    problem = clock_out_time_error(now, opens, closes, tz)
    if problem:
        raise HTTPException(400, problem)

    # ...and only at the church...
    distance = None
    if template.verification_mode != "NONE":
        church = user.church
        problem, distance = location_error(
            church.latitude,
            church.longitude,
            church.geofence_radius_m,
            body.latitude,
            body.longitude,
            body.accuracy_m,
            "clock out",
        )
        if problem:
            raise HTTPException(400, problem)

        # ...and by the member themselves: whoever clocked in with their fingerprint clocks out
        # with it too, so nobody else can end their attendance for them.
        if clock_out_needs_passkey(template.passkey_mode, record.passkey_verified):
            if not _has_passkey(db, user):
                if template.passkey_mode == "REQUIRED":
                    raise HTTPException(403, SETUP_MESSAGE)
            elif not body.passkey:
                raise HTTPException(400, "Confirm with your fingerprint or face to clock out.")
            else:
                _assert_passkey(db, user, occ, body.passkey, now, "clock_out")
        record.clock_out_distance_m = distance
        record.clock_out_accuracy_m = body.accuracy_m
    record.clock_out = now
    record.clock_out_server_time = now
    record.clock_out_device_time = body.device_time
    record.clock_out_source = "ONLINE"
    db.commit()
    return _card(occ, template, record, now, tz, _has_passkey(db, user))


@router.get("/me", response_model=list[HistoryItem])
def my_history(
    limit: int = Query(30, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    rows = db.execute(
        select(AttendanceRecord, ServiceOccurrence, ServiceTemplate.name)
        .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
        .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
        .where(AttendanceRecord.user_id == user.id)
        .order_by(AttendanceRecord.clock_in.desc())
        .limit(limit)
    ).all()
    return [
        HistoryItem(
            occurrence_id=o.id,
            name=name,
            service_date=o.service_date,
            clock_in=r.clock_in,
            clock_out=r.clock_out,
        )
        for r, o, name in rows
    ]
