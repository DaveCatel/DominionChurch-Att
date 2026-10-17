"""Proof that someone is really at the service: the rotating check-in code and the
location check. Pure functions with no database, so they are easy to test.

The code is not stored anywhere. It is derived from the service and the current time
with a secret key, so the screen at church and the server always agree on it:

    code = last six digits of HMAC(secret, "<service session id>:<30 second window>")

A code is accepted during its own 30 second window and the one after it (so people who
type slowly or have a slow connection still get in), which means it works for 30 to 60
seconds. After that it is useless, so a code sent to a friend outside is dead quickly.
"""
import hashlib
import hmac
import math
import re
import time
import uuid
from datetime import datetime, timedelta, tzinfo

from app.core.config import settings

WINDOW_SECONDS = 30

# reasons a clock-in is put in the admin's review list
FLAG_NO_LOCATION = "NO_LOCATION"  # the member did not share a location
FLAG_LOW_ACCURACY = "LOW_ACCURACY"  # the phone could only guess roughly where it is
FLAG_FAR_FROM_VENUE = "FAR_FROM_VENUE"  # clearly outside the church area
FLAG_NEW_DEVICE = "NEW_DEVICE"  # first time this account is used from this phone
FLAG_NO_DEVICE_ID = "NO_DEVICE_ID"  # the browser did not identify the phone


def _key() -> bytes:
    # a separate key for this purpose, derived from the app secret
    return hashlib.sha256(("checkin-code:" + settings.SECRET_KEY).encode()).digest()


def code_for_window(occurrence_id: uuid.UUID, window_index: int) -> str:
    digest = hmac.new(_key(), f"{occurrence_id}:{window_index}".encode(), hashlib.sha256).digest()
    return f"{int.from_bytes(digest[:4], 'big') % 1_000_000:06d}"


def current_code(occurrence_id: uuid.UUID, now: float | None = None) -> tuple[str, int]:
    """The code to show right now, and how many seconds until it changes."""
    ts = time.time() if now is None else now
    window_index = int(ts // WINDOW_SECONDS)
    return code_for_window(occurrence_id, window_index), WINDOW_SECONDS - int(ts % WINDOW_SECONDS)


def code_is_valid(occurrence_id: uuid.UUID, submitted: str | None, now: float | None = None) -> bool:
    digits = re.sub(r"\D", "", submitted or "")  # "482 913" and "482-913" are fine
    if len(digits) != 6:
        return False
    ts = time.time() if now is None else now
    window_index = int(ts // WINDOW_SECONDS)
    return any(
        hmac.compare_digest(code_for_window(occurrence_id, w), digits)
        for w in (window_index, window_index - 1)
    )


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance between two points on earth, in metres (haversine)."""
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def check_location(
    church_lat: float | None,
    church_lng: float | None,
    radius_m: int,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
) -> tuple[list[str], int | None]:
    """Returns (flags, distance in metres). Nothing here blocks anyone: GPS indoors is
    only good to 50-150 m, so doubtful cases are flagged for an admin to look at."""
    if church_lat is None or church_lng is None:
        return [], None  # the admin has not set the church location: nothing to compare with
    if lat is None or lng is None:
        return [FLAG_NO_LOCATION], None

    flags = []
    dist = distance_m(church_lat, church_lng, lat, lng)
    if accuracy_m is not None and accuracy_m > max(500, 2 * radius_m):
        flags.append(FLAG_LOW_ACCURACY)
    # "clearly outside": even if the phone is as close as its own error margin allows
    if dist - (accuracy_m or 0) > radius_m:
        flags.append(FLAG_FAR_FROM_VENUE)
    return flags, round(dist)


# ---------- clock-out: only at the end of the service, and at the church ----------
def clock_out_window(
    end_time: datetime | None, opens_minutes_before: int, closes_minutes_after: int
) -> tuple[datetime | None, datetime | None]:
    """When clock-out is possible: from the end of the service (or a few minutes before, if
    configured) until a few hours after it. A service with no end time has nothing to wait for,
    so there is no restriction."""
    if end_time is None:
        return None, None
    return end_time - timedelta(minutes=opens_minutes_before), end_time + timedelta(minutes=closes_minutes_after)


def clock_out_time_error(
    now: datetime, opens: datetime | None, closes: datetime | None, tz: tzinfo
) -> str | None:
    """A message for the member if clock-out is not possible right now, else None."""
    if opens is not None and now < opens:
        return f"You can clock out when the service ends, at {opens.astimezone(tz):%H:%M}."
    if closes is not None and now > closes:
        return "Clock-out for this service has closed. Ask an admin if your time needs correcting."
    return None


def location_error(
    church_lat: float | None,
    church_lng: float | None,
    radius_m: int,
    lat: float | None,
    lng: float | None,
    accuracy_m: float | None,
    action: str,
) -> tuple[str | None, int | None]:
    """The phone must be at the church to check in or out, so this refuses instead of
    flagging. `action` is the words for the message ("check in" or "clock out"). Returns
    (message or None, distance in metres). If the admin has not set the church location there
    is nothing to compare with, and nobody is refused."""
    flags, distance = check_location(church_lat, church_lng, radius_m, lat, lng, accuracy_m)
    if FLAG_NO_LOCATION in flags:
        return "Allow location access so we can confirm you are at the church, then try again.", None
    if FLAG_FAR_FROM_VENUE in flags:
        return f"You need to be at the church to {action}. Your phone puts you about {distance} m away.", distance
    if FLAG_LOW_ACCURACY in flags:
        return (
            "Your phone cannot tell where you are precisely enough. Move near a window or outside, wait a "
            "few seconds and try again."
        ), distance
    return None, distance


def clock_out_location_error(church_lat, church_lng, radius_m, lat, lng, accuracy_m):
    return location_error(church_lat, church_lng, radius_m, lat, lng, accuracy_m, "clock out")


# ---------- how a member confirms they are really there ----------
# Location is always required (see location_error). On top of it the member confirms with ONE of:
#   CODE     the 6-digit code shown on the screen at church
#   PASSKEY  the fingerprint, face or screen lock of their own phone
# and the service decides which are allowed (passkey_mode):
#   OFF       code only
#   OPTIONAL  either; a member who has not set a passkey up simply uses the code
#   REQUIRED  fingerprint / face only (the code is not accepted)
SETUP_MESSAGE = (
    "This service needs fingerprint or face check-in. Set it up on your profile page first, "
    "or ask an usher to mark you present."
)


def checkin_methods(passkey_mode: str, has_passkey: bool) -> list[str]:
    """The ways this member can confirm at this service, best first."""
    if passkey_mode == "REQUIRED":
        return ["PASSKEY"] if has_passkey else []
    if passkey_mode == "OPTIONAL" and has_passkey:
        return ["PASSKEY", "CODE"]
    return ["CODE"]


def needs_passkey_setup(passkey_mode: str, has_passkey: bool) -> bool:
    return passkey_mode == "REQUIRED" and not has_passkey


def choose_factor(passkey_mode: str, has_passkey: bool, sent_passkey: bool) -> tuple[str | None, str | None, int]:
    """Decide what the server must verify for this check-in: (factor, error message, HTTP status).
    factor is "PASSKEY" or "CODE", or None when the request must be refused."""
    if passkey_mode == "REQUIRED":
        if not has_passkey:
            return None, SETUP_MESSAGE, 403
        if not sent_passkey:
            return None, "Confirm with your fingerprint or face to check in.", 400
        return "PASSKEY", None, 200
    if passkey_mode == "OPTIONAL" and has_passkey and sent_passkey:
        return "PASSKEY", None, 200
    return "CODE", None, 200


def clock_out_needs_passkey(passkey_mode: str, clocked_in_with_passkey: bool) -> bool:
    """Whoever clocked in with their fingerprint must clock out with it too, so nobody else can
    end their attendance for them; and fingerprint-only services always need it."""
    return passkey_mode == "REQUIRED" or clocked_in_with_passkey
