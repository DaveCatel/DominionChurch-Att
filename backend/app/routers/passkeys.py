import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.ratelimit import passkey_failures
from app.db.database import get_db
from app.deps import get_current_user
from app.models import Passkey, ServiceOccurrence, ServiceTemplate, User
from app.services.passkeys import (
    PasskeyError,
    StoredPasskey,
    authentication_options,
    registration_options,
    verify_assertion,
    verify_registration,
)

router = APIRouter(prefix="/passkeys", tags=["passkeys (fingerprint / face check-in)"])

MAX_PASSKEYS = 5  # phones per member


class PasskeyOut(BaseModel):
    id: uuid.UUID
    name: str | None
    created_at: datetime
    last_used_at: datetime | None


class RegisterOptionsIn(BaseModel):
    # Needed only when the member already has a passkey: proof from an existing one, so
    # someone who just knows the password cannot add their own phone to the account.
    assertion: dict | None = None


class RegisterVerifyIn(BaseModel):
    credential: dict
    name: str | None = Field(default=None, max_length=100)


class AuthOptionsIn(BaseModel):
    purpose: Literal["clock_in", "clock_out", "manage"]
    occurrence_id: uuid.UUID | None = None


def _mine(db: Session, user: User) -> list[Passkey]:
    return list(
        db.scalars(select(Passkey).where(Passkey.user_id == user.id).order_by(Passkey.created_at))
    )


def _out(p: Passkey) -> PasskeyOut:
    return PasskeyOut(id=p.id, name=p.name, created_at=p.created_at, last_used_at=p.last_used_at)


def _stored(passkeys: list[Passkey]) -> dict[str, StoredPasskey]:
    return {p.credential_id: StoredPasskey(p.public_key, p.alg, p.sign_count) for p in passkeys}


@router.get("", response_model=list[PasskeyOut])
def list_passkeys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return [_out(p) for p in _mine(db, user)]


@router.post("/auth/options")
def auth_options(
    body: AuthOptionsIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Challenge for confirming with a passkey: to check in, or to add another phone."""
    passkeys = _mine(db, user)
    if not passkeys:
        raise HTTPException(400, "You have not set up fingerprint or face check-in yet.")
    if body.purpose in ("clock_in", "clock_out"):
        if body.occurrence_id is None:
            raise HTTPException(422, "Say which service you are checking in to")
        found = db.scalar(
            select(ServiceOccurrence.id)
            .join(ServiceTemplate, ServiceTemplate.id == ServiceOccurrence.service_template_id)
            .where(
                ServiceOccurrence.id == body.occurrence_id,
                ServiceTemplate.church_id == user.church_id,
            )
        )
        if found is None:
            raise HTTPException(404, "Service not found")
    occurrence_id = body.occurrence_id if body.purpose != "manage" else None
    return authentication_options(user.id, [p.credential_id for p in passkeys], body.purpose, occurrence_id)


@router.post("/register/options")
def register_options(
    body: RegisterOptionsIn,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    passkeys = _mine(db, user)
    if len(passkeys) >= MAX_PASSKEYS:
        raise HTTPException(400, f"You can set up at most {MAX_PASSKEYS} phones. Ask an admin to reset them.")
    if passkeys:
        # adding a second phone needs the first one's fingerprint / face
        if not body.assertion:
            raise HTTPException(
                403,
                "Confirm with your current phone first, or ask an admin to reset your passkeys.",
            )
        key = str(user.id)
        passkey_failures.check(key)
        try:
            result = verify_assertion(body.assertion, "manage", user.id, None, _stored(passkeys))
        except PasskeyError as exc:
            passkey_failures.hit(key)
            raise HTTPException(403, str(exc))
        for p in passkeys:
            if p.credential_id == result.credential_id:
                p.sign_count = result.sign_count
                p.last_used_at = datetime.now(timezone.utc)
        db.commit()
    return registration_options(
        user.id,
        user.email or user.phone or str(user.id),
        user.full_name,
        [p.credential_id for p in passkeys],
    )


@router.post("/register/verify", response_model=PasskeyOut, status_code=201)
def register_verify(
    body: RegisterVerifyIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    count = db.scalar(select(func.count(Passkey.id)).where(Passkey.user_id == user.id)) or 0
    if count >= MAX_PASSKEYS:
        raise HTTPException(400, f"You can set up at most {MAX_PASSKEYS} phones.")
    try:
        registered = verify_registration(body.credential, user.id)
    except PasskeyError as exc:
        raise HTTPException(400, str(exc))

    passkey = Passkey(
        user_id=user.id,
        credential_id=registered.credential_id,
        public_key=registered.public_key,
        alg=registered.alg,
        sign_count=registered.sign_count,
        name=(body.name or "").strip()[:100] or "My phone",
    )
    db.add(passkey)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "This phone is already set up for an account.")
    return _out(passkey)
