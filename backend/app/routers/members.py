import re
import uuid
from datetime import date, datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.db.database import get_db
from app.deps import require_admin
from app.models import (
    AttendanceRecord,
    AuthSession,
    Department,
    Passkey,
    Role,
    ServiceOccurrence,
    User,
    UserDepartment,
)
from app.schemas import _check_password, normalize_phone

router = APIRouter(prefix="/members", tags=["members (admin)"])


# ---------- shapes ----------
class MemberDepartment(BaseModel):
    department_id: uuid.UUID
    name: str
    status: str


class MemberOut(BaseModel):
    id: uuid.UUID
    full_name: str
    email: str | None
    phone: str | None
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    departments: list[MemberDepartment]
    times_attended: int
    last_attended: date | None
    passkey_count: int = 0  # phones set up for fingerprint / face check-in


class MemberList(BaseModel):
    items: list[MemberOut]
    total: int


class MemberUpdate(BaseModel):
    """Only the fields that are sent are changed."""

    full_name: str | None = Field(default=None, min_length=2, max_length=150)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    role: Literal["admin", "member"] | None = None
    is_active: bool | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = normalize_phone(v)
        if len(re.sub(r"\D", "", v)) < 7:
            raise ValueError("Enter a valid phone number")
        return v


class TemporaryPasswordIn(BaseModel):
    new_password: str = Field(min_length=8)

    _pw = field_validator("new_password")(_check_password)


class MembershipIn(BaseModel):
    status: Literal["ACTIVE", "PENDING", "REJECTED"] = "ACTIVE"


# ---------- helpers ----------
def _like(text: str) -> str:
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _members_out(db: Session, rows: list[tuple[User, str]]) -> list[MemberOut]:
    ids = [u.id for u, _ in rows]
    departments: dict[uuid.UUID, list[MemberDepartment]] = {}
    stats: dict[uuid.UUID, tuple[int, date | None]] = {}
    passkeys: dict[uuid.UUID, int] = {}
    if ids:
        passkeys = dict(
            db.execute(
                select(Passkey.user_id, func.count(Passkey.id))
                .where(Passkey.user_id.in_(ids))
                .group_by(Passkey.user_id)
            ).all()
        )
        for ud, dept in db.execute(
            select(UserDepartment, Department)
            .join(Department, Department.id == UserDepartment.department_id)
            .where(UserDepartment.user_id.in_(ids), Department.is_active.is_(True))
            .order_by(func.lower(Department.name))
        ):
            departments.setdefault(ud.user_id, []).append(
                MemberDepartment(department_id=dept.id, name=dept.name, status=ud.status)
            )
        for uid, count, last in db.execute(
            select(
                AttendanceRecord.user_id,
                func.count(AttendanceRecord.id),
                func.max(ServiceOccurrence.service_date),
            )
            .select_from(AttendanceRecord)
            .join(ServiceOccurrence, ServiceOccurrence.id == AttendanceRecord.service_occurrence_id)
            .where(AttendanceRecord.user_id.in_(ids))
            .group_by(AttendanceRecord.user_id)
        ):
            stats[uid] = (count, last)
    return [
        MemberOut(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            phone=u.phone,
            role=role_name,
            is_active=u.is_active,
            created_at=u.created_at,
            last_login_at=u.last_login_at,
            departments=departments.get(u.id, []),
            times_attended=stats.get(u.id, (0, None))[0],
            last_attended=stats.get(u.id, (0, None))[1],
            passkey_count=passkeys.get(u.id, 0),
        )
        for u, role_name in rows
    ]


def _get_member(db: Session, admin: User, user_id: uuid.UUID) -> tuple[User, str]:
    row = db.execute(
        select(User, Role.name)
        .join(Role, Role.id == User.role_id)
        .where(User.id == user_id, User.church_id == admin.church_id)
    ).first()
    if row is None:
        raise HTTPException(404, "Member not found")
    return row[0], row[1]


def _one(db: Session, admin: User, user_id: uuid.UUID) -> MemberOut:
    user, role_name = _get_member(db, admin, user_id)
    return _members_out(db, [(user, role_name)])[0]


def _revoke_sessions(db: Session, user_id: uuid.UUID) -> None:
    db.execute(
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


def _other_active_admins(db: Session, church_id: uuid.UUID, exclude: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.count(User.id))
            .select_from(User)
            .join(Role, Role.id == User.role_id)
            .where(
                User.church_id == church_id,
                Role.name == "admin",
                User.is_active.is_(True),
                User.id != exclude,
            )
        )
        or 0
    )


# ---------- endpoints ----------
@router.get("", response_model=MemberList)
def list_members(
    q: str | None = None,
    department_id: uuid.UUID | None = None,
    role: Literal["admin", "member"] | None = None,
    active: bool | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    conds = [User.church_id == admin.church_id]
    if q and q.strip():
        term = q.strip()
        matches = [
            User.full_name.ilike(_like(term), escape="\\"),
            User.email.ilike(_like(term), escape="\\"),
            User.phone.ilike(_like(term), escape="\\"),
        ]
        digits = normalize_phone(term)  # "6 77 00" also finds +237677001234
        if digits != term and len(re.sub(r"\D", "", digits)) >= 3:
            matches.append(User.phone.ilike(_like(digits), escape="\\"))
        conds.append(or_(*matches))
    if department_id is not None:
        conds.append(
            User.id.in_(
                select(UserDepartment.user_id).where(
                    UserDepartment.department_id == department_id,
                    UserDepartment.status == "ACTIVE",
                )
            )
        )
    if role is not None:
        conds.append(Role.name == role)
    if active is not None:
        conds.append(User.is_active.is_(active))

    total = (
        db.scalar(
            select(func.count(User.id))
            .select_from(User)
            .join(Role, Role.id == User.role_id)
            .where(*conds)
        )
        or 0
    )
    rows = db.execute(
        select(User, Role.name)
        .join(Role, Role.id == User.role_id)
        .where(*conds)
        .order_by(func.lower(User.full_name), User.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return MemberList(items=_members_out(db, [(u, r) for u, r in rows]), total=total)


@router.patch("/{user_id}", response_model=MemberOut)
def update_member(
    user_id: uuid.UUID,
    body: MemberUpdate,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user, role_name = _get_member(db, admin, user_id)
    data = body.model_dump(exclude_unset=True)
    for field in ("full_name", "email", "phone", "role", "is_active"):
        if field in data and data[field] is None:
            raise HTTPException(422, f"{field} cannot be empty")

    new_role = data.get("role", role_name)
    new_active = data.get("is_active", user.is_active)
    loses_admin = role_name == "admin" and user.is_active and (new_role != "admin" or not new_active)
    if user.id == admin.id and (new_role != "admin" or not new_active):
        raise HTTPException(400, "You cannot remove your own admin access or deactivate yourself.")
    if loses_admin and _other_active_admins(db, admin.church_id, user.id) == 0:
        raise HTTPException(400, "This is the only active admin. Make someone else an admin first.")

    if "full_name" in data:
        name = data["full_name"].strip()
        if len(name) < 2:
            raise HTTPException(422, "Enter the member's name")
        user.full_name = name
    if "email" in data:
        email = data["email"].lower()
        if db.scalar(
            select(User.id).where(
                User.church_id == admin.church_id, User.email == email, User.id != user.id
            )
        ):
            raise HTTPException(409, "Another member already uses this email")
        user.email = email
    if "phone" in data:
        if db.scalar(
            select(User.id).where(
                User.church_id == admin.church_id, User.phone == data["phone"], User.id != user.id
            )
        ):
            raise HTTPException(409, "Another member already uses this phone number")
        user.phone = data["phone"]
    if "role" in data and new_role != role_name:
        role = db.scalar(select(Role).where(Role.name == new_role))
        if role is None:
            raise HTTPException(500, "Role is missing; run scripts.init_db")
        user.role_id = role.id
    if "is_active" in data and new_active != user.is_active:
        user.is_active = new_active
        if not new_active:
            _revoke_sessions(db, user.id)  # signed out everywhere, immediately

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Another member already uses this email or phone number")
    return _one(db, admin, user_id)


@router.put("/{user_id}/departments/{department_id}", response_model=MemberOut)
def set_membership(
    user_id: uuid.UUID,
    department_id: uuid.UUID,
    body: MembershipIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Add a member to a department (or change the status of their membership)."""
    _get_member(db, admin, user_id)
    dept = db.get(Department, department_id)
    if dept is None or dept.church_id != admin.church_id:
        raise HTTPException(404, "Department not found")

    now = datetime.now(timezone.utc)
    ud = db.get(UserDepartment, (user_id, department_id))
    if ud is None:
        ud = UserDepartment(user_id=user_id, department_id=department_id, status=body.status)
        db.add(ud)
    else:
        ud.status = body.status
    if body.status == "PENDING":
        ud.reviewed_by, ud.reviewed_at = None, None
    else:
        ud.reviewed_by, ud.reviewed_at = admin.id, now
    db.commit()
    return _one(db, admin, user_id)


@router.delete("/{user_id}/departments/{department_id}", response_model=MemberOut)
def remove_membership(
    user_id: uuid.UUID,
    department_id: uuid.UUID,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    _get_member(db, admin, user_id)
    ud = db.get(UserDepartment, (user_id, department_id))
    if ud is None:
        raise HTTPException(404, "This member is not in that department")
    db.delete(ud)
    db.commit()
    return _one(db, admin, user_id)


@router.post("/{user_id}/password", status_code=204)
def set_temporary_password(
    user_id: uuid.UUID,
    body: TemporaryPasswordIn,
    admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """For members who cannot receive the reset email: the admin sets a new password."""
    user, _ = _get_member(db, admin, user_id)
    user.password_hash = hash_password(body.new_password)
    _revoke_sessions(db, user.id)
    db.commit()
    return Response(status_code=204)


@router.delete("/{user_id}/passkeys", response_model=MemberOut)
def reset_passkeys(
    user_id: uuid.UUID, admin: User = Depends(require_admin), db: Session = Depends(get_db)
):
    """Remove all of a member's fingerprint / face check-in phones, for example after a lost
    phone or when someone else set one up on their account. They can set a new one up."""
    _get_member(db, admin, user_id)
    for passkey in db.scalars(select(Passkey).where(Passkey.user_id == user_id)):
        db.delete(passkey)
    db.commit()
    return _one(db, admin, user_id)
