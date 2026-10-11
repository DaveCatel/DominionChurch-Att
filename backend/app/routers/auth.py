import ipaddress
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.ratelimit import login_account_failures, login_failures, signup_limiter
from app.core.security import (
    create_access_token,
    hash_password,
    hash_token,
    new_refresh_token,
    verify_password,
)
from app.db.database import get_db
from app.models import AuthSession, Church, Department, Role, User, UserDepartment
from app.schemas import (
    AuthOut,
    LoginIn,
    RefreshIn,
    SignupIn,
    TokensOut,
    normalize_phone,
    user_out,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    host = request.client.host if request.client else None
    try:
        return str(ipaddress.ip_address(host)) if host else None
    except ValueError:
        return None


def _issue_session(db: Session, user: User, request: Request) -> AuthOut:
    raw, hashed = new_refresh_token()
    now = datetime.now(timezone.utc)
    db.add(
        AuthSession(
            user_id=user.id,
            refresh_token_hash=hashed,
            ip_address=_client_ip(request),
            user_agent=(request.headers.get("user-agent") or "")[:500] or None,
            expires_at=now + timedelta(days=settings.REFRESH_TOKEN_DAYS),
            last_used_at=now,
        )
    )
    user.last_login_at = now
    db.commit()
    return AuthOut(
        access_token=create_access_token(user.id),
        refresh_token=raw,
        user=user_out(user),
    )


@router.post("/signup", response_model=AuthOut, status_code=status.HTTP_201_CREATED)
def signup(body: SignupIn, request: Request, db: Session = Depends(get_db)):
    signup_limiter.check_and_hit(_client_ip(request) or "unknown")
    church = db.scalar(
        select(Church).where(Church.is_active.is_(True)).order_by(Church.created_at).limit(1)
    )
    role = db.scalar(select(Role).where(Role.name == "member"))
    if church is None or role is None:
        raise HTTPException(503, "The app has not been set up yet (run scripts.init_db)")

    email = body.email.lower()
    exists = db.scalar(
        select(User.id).where(
            User.church_id == church.id,
            or_(User.email == email, User.phone == body.phone),
        )
    )
    if exists:
        raise HTTPException(409, "An account with this email or phone already exists")

    department_ids = list(dict.fromkeys(body.department_ids))
    departments = db.scalars(
        select(Department).where(
            Department.church_id == church.id,
            Department.is_active.is_(True),
            Department.id.in_(department_ids),
        )
    ).all()
    found_ids = {department.id for department in departments}
    missing_ids = [department_id for department_id in department_ids if department_id not in found_ids]
    if missing_ids:
        raise HTTPException(400, "One or more selected departments are invalid or inactive")

    user = User(
        church_id=church.id,
        role_id=role.id,
        full_name=body.full_name.strip(),
        email=email,
        phone=body.phone,
        password_hash=hash_password(body.password),
    )
    db.add(user)
    try:
        db.flush()
        for index, department_id in enumerate(department_ids):
            db.add(
                UserDepartment(
                    user_id=user.id,
                    department_id=department_id,
                    is_primary=(index == 0),
                    status="PENDING",
                )
            )
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email or phone already exists")
    return _issue_session(db, user, request)


@router.post("/login", response_model=AuthOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ident = body.identifier.strip()
    # at most 5 wrong passwords per sign-in name and address every 15 minutes
    attempt_key = f"{_client_ip(request)}|{ident.lower()}"
    login_failures.check(attempt_key)
    login_account_failures.check(ident.lower())
    cond = User.email == ident.lower() if "@" in ident else User.phone == normalize_phone(ident)
    user = db.scalars(select(User).where(cond).limit(1)).first()
    if user is None or not verify_password(body.password, user.password_hash):
        login_failures.hit(attempt_key)
        login_account_failures.hit(ident.lower())
        raise HTTPException(401, "Wrong email/phone or password")
    login_failures.reset(attempt_key)
    login_account_failures.reset(ident.lower())
    if not user.is_active:
        raise HTTPException(403, "This account has been deactivated")
    return _issue_session(db, user, request)


@router.post("/refresh", response_model=TokensOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    session = db.scalar(
        select(AuthSession).where(
            AuthSession.refresh_token_hash == hash_token(body.refresh_token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
        )
    )
    if session is None or not session.user.is_active:
        raise HTTPException(401, "Session expired, please log in again")
    raw, hashed = new_refresh_token()  # rotate: the old refresh token stops working
    session.refresh_token_hash = hashed
    session.last_used_at = now
    session.expires_at = now + timedelta(days=settings.REFRESH_TOKEN_DAYS)
    db.commit()
    return TokensOut(access_token=create_access_token(session.user_id), refresh_token=raw)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(body: RefreshIn, db: Session = Depends(get_db)):
    session = db.scalar(
        select(AuthSession).where(AuthSession.refresh_token_hash == hash_token(body.refresh_token))
    )
    if session and session.revoked_at is None:
        session.revoked_at = datetime.now(timezone.utc)
        db.commit()
