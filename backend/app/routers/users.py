import re
import uuid
from pathlib import Path

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.database import get_db
from app.deps import get_current_user
from app.models import Department, User, UserAvatar, UserDepartment
from app.schemas import DepartmentRequestIn, MyDepartmentOut, ProfileUpdate, UserOut, user_out
from app.services.images import ImageError, prepare_avatar

router = APIRouter(prefix="/users", tags=["users"])

MAX_AVATAR_BYTES = 2 * 1024 * 1024
AVATAR_URL_PREFIX = "/api/media/avatars/"  # photos saved the old way, as files on the server
AVATAR_ROUTE_PREFIX = "/api/users/avatar/"  # photos kept in the database


def _image_ext(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    return None


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user_out(user)


@router.patch("/me", response_model=UserOut)
def update_me(
    body: ProfileUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if body.full_name is not None:
        user.full_name = body.full_name.strip()
    if body.email is not None:
        email = body.email.lower()
        taken = db.scalar(
            select(User.id).where(
                User.church_id == user.church_id, User.email == email, User.id != user.id
            )
        )
        if taken:
            raise HTTPException(409, "That email is already used by another account")
        user.email = email
    if body.phone is not None:
        taken = db.scalar(
            select(User.id).where(
                User.church_id == user.church_id, User.phone == body.phone, User.id != user.id
            )
        )
        if taken:
            raise HTTPException(409, "That phone number is already used by another account")
        user.phone = body.phone
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email or phone already in use")
    return user_out(user)


@router.post("/me/avatar", response_model=UserOut)
async def upload_avatar(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    data = await file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        raise HTTPException(413, "Image is too large (max 2 MB)")
    ext = _image_ext(data)
    if ext is None:
        raise HTTPException(415, "Use a JPG, PNG or WebP image")

    try:
        photo, content_type = prepare_avatar(data)  # straightened, square, small
    except ImageError as exc:
        raise HTTPException(415, str(exc))

    # Kept in the database: the server's disk is wiped on every restart on hosts like Render.
    token = uuid.uuid4().hex
    avatar = db.get(UserAvatar, user.id)
    if avatar is None:
        db.add(UserAvatar(user_id=user.id, token=token, content_type=content_type, data=photo))
    else:
        avatar.token, avatar.content_type, avatar.data = token, content_type, photo

    old = user.profile_photo_url
    user.profile_photo_url = AVATAR_ROUTE_PREFIX + token
    db.commit()

    if old and old.startswith(AVATAR_URL_PREFIX):  # tidy up a photo saved the old way
        (Path(settings.MEDIA_DIR) / "avatars" / old.removeprefix(AVATAR_URL_PREFIX)).unlink(missing_ok=True)
    return user_out(user)


@router.get("/avatar/{token}")
def get_avatar(token: str, db: Session = Depends(get_db)):
    """A member's photo. The address is unguessable and changes when they upload a new one,
    so it can be cached for a year and shown in plain <img> tags without signing in."""
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        raise HTTPException(404, "Photo not found")
    avatar = db.scalar(select(UserAvatar).where(UserAvatar.token == token))
    if avatar is None:
        raise HTTPException(404, "Photo not found")
    return Response(
        content=bytes(avatar.data),
        media_type=avatar.content_type,
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )


# ---------- my departments ----------
def _my_departments(db: Session, user: User) -> list[MyDepartmentOut]:
    rows = db.execute(
        select(UserDepartment, Department)
        .join(Department, Department.id == UserDepartment.department_id)
        .where(UserDepartment.user_id == user.id, Department.is_active.is_(True))
        .order_by(func.lower(Department.name))
    ).all()
    return [
        MyDepartmentOut(
            department_id=d.id, name=d.name, description=d.description, status=ud.status
        )
        for ud, d in rows
    ]


@router.get("/me/departments", response_model=list[MyDepartmentOut])
def my_departments(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _my_departments(db, user)


@router.post("/me/departments", response_model=list[MyDepartmentOut])
def request_departments(
    body: DepartmentRequestIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Ask to join more departments. An admin still has to approve each request."""
    ids = list(dict.fromkeys(body.department_ids))
    found = db.scalars(
        select(Department).where(
            Department.id.in_(ids),
            Department.church_id == user.church_id,
            Department.is_active.is_(True),
        )
    ).all()
    if len(found) != len(ids):
        raise HTTPException(400, "One of the selected departments is not available")

    existing = {
        ud.department_id: ud
        for ud in db.scalars(
            select(UserDepartment).where(
                UserDepartment.user_id == user.id, UserDepartment.department_id.in_(ids)
            )
        )
    }
    for dept in found:
        ud = existing.get(dept.id)
        if ud is None:
            db.add(UserDepartment(user_id=user.id, department_id=dept.id, status="PENDING"))
        elif ud.status == "REJECTED":  # asking again after a rejection
            ud.status = "PENDING"
            ud.joined_at = datetime.now(timezone.utc)
            ud.reviewed_at = None
            ud.reviewed_by = None
        # already PENDING or ACTIVE: nothing to do
    db.commit()
    return _my_departments(db, user)


@router.delete("/me/departments/{department_id}", status_code=204)
def leave_department(
    department_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a pending request, or leave a department you are in."""
    ud = db.get(UserDepartment, (user.id, department_id))
    if ud is None:
        raise HTTPException(404, "You are not in this department")
    db.delete(ud)
    db.commit()
    return Response(status_code=204)
