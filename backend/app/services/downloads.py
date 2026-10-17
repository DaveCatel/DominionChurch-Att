"""Short-lived signed links for downloading a file (such as the attendance PDF).

A browser opens a download link directly and cannot send the usual sign-in header, so an
admin first asks the API for a link (an authenticated request) and gets back an address that
works for two minutes, for that one file and that one admin. Nothing is stored.
"""
import hashlib
import hmac
import time
import uuid

from app.core.config import settings
from app.services.passkeys import b64u, unb64u

LINK_SECONDS = 120


def _mac(kind: str, subject: uuid.UUID, user_id: uuid.UUID, expires: int) -> str:
    key = hashlib.sha256(("download-link:" + settings.SECRET_KEY).encode()).digest()
    message = f"{kind}|{subject}|{user_id}|{expires}".encode()
    return b64u(hmac.new(key, message, hashlib.sha256).digest()[:18])


def make_download_token(kind: str, subject: uuid.UUID, user_id: uuid.UUID, now: float | None = None) -> str:
    expires = int((time.time() if now is None else now) + LINK_SECONDS)
    return f"{user_id.hex}.{expires}.{_mac(kind, subject, user_id, expires)}"


def read_download_token(token: str | None, kind: str, subject: uuid.UUID, now: float | None = None) -> uuid.UUID | None:
    """The user the link was made for, or None if it is forged, expired or for something else."""
    try:
        user_hex, expires_text, mac = (token or "").split(".")
        user_id = uuid.UUID(hex=user_hex)
        expires = int(expires_text)
    except (ValueError, TypeError):
        return None
    if expires < (time.time() if now is None else now):
        return None
    if not hmac.compare_digest(mac, _mac(kind, subject, user_id, expires)):
        return None
    return user_id
