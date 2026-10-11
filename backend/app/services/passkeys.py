"""Passkeys (WebAuthn): proving that the person tapping "check in" is the account owner.

The member's phone keeps a private key that never leaves it and is unlocked by their
fingerprint, face or screen lock. We store only the matching public key. At check-in the
phone signs a one-time challenge; only the real phone, unlocked by its owner, can do that,
so a friend who knows your password still cannot check in as you.

This module has no database code, so it can be tested on its own. It follows the W3C
WebAuthn rules for what a relying party must verify, for the "none" attestation that
consumer apps use (we do not need to know which phone model it is, only that the key
signs correctly).

Challenges are not stored. Each one carries its own expiry and a signature (HMAC) that
binds it to one purpose, one member and, for check-in, one service session, so a
challenge cannot be reused for another member or another service. Each is also accepted
only once.
"""
import base64
import binascii
import hashlib
import hmac
import json
import os
import struct
import threading
import time
import uuid
from dataclasses import dataclass
from urllib.parse import urlparse

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa

from app.core.config import settings

CHALLENGE_SECONDS = 120
ALG_ES256 = -7  # ECDSA with P-256 and SHA-256: what phones use
ALG_RS256 = -257  # RSA PKCS#1 v1.5 with SHA-256: what some Windows PCs use

FLAG_UP = 0x01  # user present
FLAG_UV = 0x04  # user verified (fingerprint, face or screen lock)
FLAG_AT = 0x40  # attested credential data included

PURPOSES = ("register", "manage", "clock_in")


class PasskeyError(Exception):
    """Something is wrong with the passkey response. The text is safe to show the member."""


BAD_RESPONSE = "The fingerprint check came back in a form we could not read. Please try again."


@dataclass
class RegisteredPasskey:
    credential_id: str  # base64url
    public_key: bytes  # SubjectPublicKeyInfo DER
    alg: int
    sign_count: int


@dataclass
class StoredPasskey:
    public_key: bytes
    alg: int
    sign_count: int


@dataclass
class AssertionResult:
    credential_id: str
    sign_count: int


# ---------- where this site lives ----------
def rp_id() -> str:
    """The domain passkeys are tied to (a passkey made for one domain cannot be used on
    another, which is what defeats look-alike phishing sites)."""
    if settings.WEBAUTHN_RP_ID:
        return settings.WEBAUTHN_RP_ID
    return urlparse(settings.WEB_BASE_URL).hostname or "localhost"


def allowed_origins() -> list[str]:
    if settings.WEBAUTHN_ORIGINS:
        return [o.rstrip("/") for o in settings.WEBAUTHN_ORIGINS]
    parts = urlparse(settings.WEB_BASE_URL)
    return [f"{parts.scheme}://{parts.netloc}"]


# ---------- base64url ----------
def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64u(value) -> bytes:
    if not isinstance(value, str):
        raise PasskeyError(BAD_RESPONSE)
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, binascii.Error):
        raise PasskeyError(BAD_RESPONSE)


# ---------- the little bit of CBOR that WebAuthn needs ----------
def _cbor(data: bytes, pos: int = 0, depth: int = 0):
    """Decode one CBOR item starting at pos. Returns (value, position after it)."""
    if depth > 8 or pos >= len(data):
        raise PasskeyError(BAD_RESPONSE)
    first = data[pos]
    major, info = first >> 5, first & 31
    pos += 1

    if major == 7:  # simple values and floats
        if info in (20, 21):
            return info == 21, pos
        if info in (22, 23):
            return None, pos
        sizes = {25: ("e", 2), 26: ("f", 4), 27: ("d", 8)}
        if info in sizes:
            fmt, size = sizes[info]
            if pos + size > len(data):
                raise PasskeyError(BAD_RESPONSE)
            return struct.unpack(">" + fmt, data[pos : pos + size])[0], pos + size
        raise PasskeyError(BAD_RESPONSE)

    if info < 24:
        n = info
    else:
        size = {24: 1, 25: 2, 26: 4, 27: 8}.get(info)
        if size is None or pos + size > len(data):  # indefinite lengths are not used here
            raise PasskeyError(BAD_RESPONSE)
        n = int.from_bytes(data[pos : pos + size], "big")
        pos += size

    if major == 0:
        return n, pos
    if major == 1:
        return -1 - n, pos
    if major in (2, 3):
        end = pos + n
        if end > len(data):
            raise PasskeyError(BAD_RESPONSE)
        raw = bytes(data[pos:end])
        if major == 2:
            return raw, end
        try:
            return raw.decode("utf-8"), end
        except UnicodeDecodeError:
            raise PasskeyError(BAD_RESPONSE)
    if major == 4:
        if n > 1000:
            raise PasskeyError(BAD_RESPONSE)
        items = []
        for _ in range(n):
            item, pos = _cbor(data, pos, depth + 1)
            items.append(item)
        return items, pos
    if major == 5:
        if n > 1000:
            raise PasskeyError(BAD_RESPONSE)
        out = {}
        for _ in range(n):
            key, pos = _cbor(data, pos, depth + 1)
            value, pos = _cbor(data, pos, depth + 1)
            if not isinstance(key, (int, str, bytes)):
                raise PasskeyError(BAD_RESPONSE)
            out[key] = value
        return out, pos
    if major == 6:  # a tag: we only care about the value inside
        return _cbor(data, pos, depth + 1)
    raise PasskeyError(BAD_RESPONSE)


def cbor_decode(data: bytes):
    value, _ = _cbor(data, 0)
    return value


# ---------- challenges ----------
_used_challenges: dict[str, float] = {}
_used_lock = threading.Lock()


def _mac(purpose: str, user_id: uuid.UUID, occurrence_id: uuid.UUID | None, payload: bytes) -> bytes:
    key = hashlib.sha256(("webauthn-challenge:" + settings.SECRET_KEY).encode()).digest()
    message = b"|".join([purpose.encode(), str(user_id).encode(), str(occurrence_id or "").encode(), payload])
    return hmac.new(key, message, hashlib.sha256).digest()[:16]


def issue_challenge(
    purpose: str, user_id: uuid.UUID, occurrence_id: uuid.UUID | None = None, now: float | None = None
) -> str:
    assert purpose in PURPOSES
    ts = time.time() if now is None else now
    payload = os.urandom(16) + int(ts + CHALLENGE_SECONDS).to_bytes(4, "big")
    return b64u(payload + _mac(purpose, user_id, occurrence_id, payload))


def _consume_challenge(
    challenge, purpose: str, user_id: uuid.UUID, occurrence_id: uuid.UUID | None, now: float | None
) -> None:
    """Accept a challenge once, for the purpose, member and service it was made for."""
    ts = time.time() if now is None else now
    raw = unb64u(challenge)
    if len(raw) != 36:
        raise PasskeyError(BAD_RESPONSE)
    payload, mac = raw[:20], raw[20:]
    if not hmac.compare_digest(mac, _mac(purpose, user_id, occurrence_id, payload)):
        raise PasskeyError("This fingerprint check was not meant for this request. Please start again.")
    if int.from_bytes(payload[16:], "big") < ts:
        raise PasskeyError("The fingerprint check took too long. Please try again.")
    with _used_lock:
        for key in [k for k, exp in _used_challenges.items() if exp < ts]:
            del _used_challenges[key]  # forget challenges that have expired anyway
        if challenge in _used_challenges:
            raise PasskeyError("This fingerprint check was already used. Please try again.")
        _used_challenges[challenge] = int.from_bytes(payload[16:], "big")


# ---------- what the phone sends back ----------
def _check_client_data(
    raw: bytes,
    expected_type: str,
    purpose: str,
    user_id: uuid.UUID,
    occurrence_id: uuid.UUID | None,
    now: float | None,
) -> None:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise PasskeyError(BAD_RESPONSE)
    if not isinstance(data, dict) or data.get("type") != expected_type:
        raise PasskeyError(BAD_RESPONSE)
    if data.get("origin") not in allowed_origins():
        raise PasskeyError(
            "Fingerprint check-in is not allowed from this web address. Open the app from its normal address."
        )
    if data.get("crossOrigin") is True:
        raise PasskeyError(BAD_RESPONSE)
    _consume_challenge(data.get("challenge"), purpose, user_id, occurrence_id, now)


def _parse_auth_data(auth: bytes) -> dict:
    if len(auth) < 37:
        raise PasskeyError(BAD_RESPONSE)
    out = {
        "rp_hash": auth[:32],
        "flags": auth[32],
        "sign_count": int.from_bytes(auth[33:37], "big"),
        "credential_id": None,
        "cose_key": None,
    }
    if out["flags"] & FLAG_AT:
        pos = 37 + 16  # skip the authenticator model id
        if pos + 2 > len(auth):
            raise PasskeyError(BAD_RESPONSE)
        id_len = int.from_bytes(auth[pos : pos + 2], "big")
        pos += 2
        if pos + id_len > len(auth):
            raise PasskeyError(BAD_RESPONSE)
        out["credential_id"] = auth[pos : pos + id_len]
        pos += id_len
        out["cose_key"], _ = _cbor(auth, pos)
    return out


def _check_auth_data(parsed: dict) -> None:
    if not hmac.compare_digest(parsed["rp_hash"], hashlib.sha256(rp_id().encode()).digest()):
        raise PasskeyError("This fingerprint check was made for a different website.")
    if not parsed["flags"] & FLAG_UP:
        raise PasskeyError("The phone did not confirm that you were present. Please try again.")
    if not parsed["flags"] & FLAG_UV:
        raise PasskeyError("The phone did not check your fingerprint, face or screen lock. Please try again.")


def _public_key_from_cose(cose) -> tuple[int, bytes]:
    if not isinstance(cose, dict):
        raise PasskeyError(BAD_RESPONSE)
    kty, alg = cose.get(1), cose.get(3)
    try:
        if kty == 2 and alg == ALG_ES256 and cose.get(-1) == 1:
            x, y = cose.get(-2), cose.get(-3)
            if not (isinstance(x, bytes) and isinstance(y, bytes) and len(x) == 32 and len(y) == 32):
                raise PasskeyError(BAD_RESPONSE)
            key = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x, "big"), int.from_bytes(y, "big"), ec.SECP256R1()
            ).public_key()
        elif kty == 3 and alg == ALG_RS256:
            n, e = cose.get(-1), cose.get(-2)
            if not (isinstance(n, bytes) and isinstance(e, bytes)):
                raise PasskeyError(BAD_RESPONSE)
            key = rsa.RSAPublicNumbers(int.from_bytes(e, "big"), int.from_bytes(n, "big")).public_key()
            if key.key_size < 2048:
                raise PasskeyError("This passkey is too weak to use.")
        else:
            raise PasskeyError("This phone uses a kind of passkey we do not support yet.")
    except ValueError:  # for example a point that is not on the curve
        raise PasskeyError(BAD_RESPONSE)
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return alg, der


def _verify_signature(alg: int, public_key_der: bytes, signature: bytes, signed: bytes) -> None:
    key = serialization.load_der_public_key(public_key_der)
    try:
        if alg == ALG_ES256:
            key.verify(signature, signed, ec.ECDSA(hashes.SHA256()))
        elif alg == ALG_RS256:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
        else:
            raise PasskeyError(BAD_RESPONSE)
    except InvalidSignature:
        raise PasskeyError("The fingerprint check could not be verified. Please try again.")


# ---------- options the browser needs ----------
def registration_options(
    user_id: uuid.UUID, user_name: str, display_name: str, existing_credential_ids: list[str]
) -> dict:
    return {
        "challenge": issue_challenge("register", user_id),
        "rp": {"name": settings.WEBAUTHN_RP_NAME, "id": rp_id()},
        "user": {"id": b64u(user_id.bytes), "name": user_name, "displayName": display_name},
        "pubKeyCredParams": [
            {"type": "public-key", "alg": ALG_ES256},
            {"type": "public-key", "alg": ALG_RS256},
        ],
        "timeout": 60000,
        "attestation": "none",
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",  # the phone's own fingerprint / face / screen lock
            "residentKey": "preferred",
            "userVerification": "required",
        },
        # stops the same phone being registered twice for one account
        "excludeCredentials": [{"type": "public-key", "id": cid} for cid in existing_credential_ids],
    }


def authentication_options(
    user_id: uuid.UUID, credential_ids: list[str], purpose: str, occurrence_id: uuid.UUID | None = None
) -> dict:
    return {
        "challenge": issue_challenge(purpose, user_id, occurrence_id),
        "rpId": rp_id(),
        "timeout": 60000,
        "userVerification": "required",
        "allowCredentials": [{"type": "public-key", "id": cid} for cid in credential_ids],
    }


# ---------- checking what comes back ----------
def verify_registration(credential: dict, user_id: uuid.UUID, now: float | None = None) -> RegisteredPasskey:
    """Check a newly created passkey and return what to store."""
    if not isinstance(credential, dict) or not isinstance(credential.get("response"), dict):
        raise PasskeyError(BAD_RESPONSE)
    response = credential["response"]
    if credential.get("type") != "public-key":
        raise PasskeyError(BAD_RESPONSE)

    _check_client_data(unb64u(response.get("clientDataJSON")), "webauthn.create", "register", user_id, None, now)

    attestation = cbor_decode(unb64u(response.get("attestationObject")))
    if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
        raise PasskeyError(BAD_RESPONSE)
    parsed = _parse_auth_data(attestation["authData"])
    _check_auth_data(parsed)
    if not parsed["flags"] & FLAG_AT or not parsed["credential_id"]:
        raise PasskeyError(BAD_RESPONSE)
    if parsed["credential_id"] != unb64u(credential.get("rawId")):
        raise PasskeyError(BAD_RESPONSE)

    alg, public_key = _public_key_from_cose(parsed["cose_key"])
    return RegisteredPasskey(
        credential_id=b64u(parsed["credential_id"]),
        public_key=public_key,
        alg=alg,
        sign_count=parsed["sign_count"],
    )


def verify_assertion(
    assertion: dict,
    purpose: str,
    user_id: uuid.UUID,
    occurrence_id: uuid.UUID | None,
    stored: dict[str, StoredPasskey],
    now: float | None = None,
) -> AssertionResult:
    """Check a fingerprint/face confirmation against the member's saved passkeys."""
    if not isinstance(assertion, dict) or not isinstance(assertion.get("response"), dict):
        raise PasskeyError(BAD_RESPONSE)
    response = assertion["response"]
    credential_id = assertion.get("id")
    passkey = stored.get(credential_id) if isinstance(credential_id, str) else None
    if passkey is None or assertion.get("type") != "public-key":
        raise PasskeyError("That passkey is not registered to your account.")
    if unb64u(assertion.get("rawId")) != unb64u(credential_id):
        raise PasskeyError(BAD_RESPONSE)

    client_data = unb64u(response.get("clientDataJSON"))
    _check_client_data(client_data, "webauthn.get", purpose, user_id, occurrence_id, now)

    auth_data = unb64u(response.get("authenticatorData"))
    parsed = _parse_auth_data(auth_data)
    _check_auth_data(parsed)

    signed = auth_data + hashlib.sha256(client_data).digest()
    _verify_signature(passkey.alg, passkey.public_key, unb64u(response.get("signature")), signed)

    # Phones that count their uses must always count upwards; a counter that does not
    # means the key was probably copied. Synced passkeys keep the counter at 0.
    if (parsed["sign_count"] or passkey.sign_count) and parsed["sign_count"] <= passkey.sign_count:
        raise PasskeyError(
            "This passkey looks like it was copied, so it was refused. Please ask an admin to reset your passkeys."
        )
    return AssertionResult(credential_id=credential_id, sign_count=parsed["sign_count"])
