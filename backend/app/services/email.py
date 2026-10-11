"""Sending email, plus the wording of the emails the app sends.

Three ways to send, tried in this order:

1. Brevo (set BREVO_API_KEY) and 2. Resend (set RESEND_API_KEY): the email goes over HTTPS
   to the provider's web API. Use one of these on hosts that block SMTP, such as Render's
   free plan.
3. SMTP (set SMTP_HOST): a normal mail server.

Whichever you use also needs EMAIL_FROM (or SMTP_FROM), the sender address. Most providers
only deliver mail from an address or domain you have verified with them.

send_email never raises: a mail problem must not break the request that triggered it.
Run it through FastAPI BackgroundTasks so the response is not delayed.
"""
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from app.core.config import settings

log = logging.getLogger("uvicorn.error")

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
RESEND_URL = "https://api.resend.com/emails"


def _from_address() -> str | None:
    return settings.EMAIL_FROM or settings.SMTP_FROM


def email_provider() -> str | None:
    """Which way mail will be sent, or None when email is not set up."""
    if not _from_address():
        return None
    if settings.BREVO_API_KEY:
        return "brevo"
    if settings.RESEND_API_KEY:
        return "resend"
    if settings.SMTP_HOST:
        return "smtp"
    return None


def email_configured() -> bool:
    return email_provider() is not None


def _post_json(url: str, headers: dict, payload: dict) -> None:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            # providers sit behind firewalls that reject the default Python user agent
            "User-Agent": "church-attendance/1.0",
            **headers,
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        response.read()


def _send_brevo(to: str, subject: str, body: str) -> None:
    name, address = parseaddr(_from_address())
    sender = {"email": address}
    if name:
        sender["name"] = name
    _post_json(
        BREVO_URL,
        {"api-key": settings.BREVO_API_KEY},
        {"sender": sender, "to": [{"email": to}], "subject": subject, "textContent": body},
    )


def _send_resend(to: str, subject: str, body: str) -> None:
    _post_json(
        RESEND_URL,
        {"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        {"from": _from_address(), "to": [to], "subject": subject, "text": body},
    )


def _send_smtp(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = _from_address()
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if settings.SMTP_SECURITY == "ssl":
        server = smtplib.SMTP_SSL(
            settings.SMTP_HOST, settings.SMTP_PORT, timeout=20, context=ssl.create_default_context()
        )
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)
    with server:
        if settings.SMTP_SECURITY == "starttls":
            server.starttls(context=ssl.create_default_context())
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
        server.send_message(msg)


def send_email(to: str | None, subject: str, body: str) -> None:
    if not to:
        return
    provider = email_provider()
    if provider is None:
        log.warning(
            "Email is not configured (set BREVO_API_KEY, RESEND_API_KEY or SMTP_HOST, plus EMAIL_FROM); "
            "not sending %r to %s",
            subject,
            to,
        )
        if settings.ENVIRONMENT != "production":
            log.warning("---- email body (shown in development only) ----\n%s\n----", body)
        return
    try:
        {"brevo": _send_brevo, "resend": _send_resend, "smtp": _send_smtp}[provider](to, subject, body)
    except urllib.error.HTTPError as exc:  # the provider answered with an error
        log.error(
            "Email provider %s refused %r to %s: HTTP %s %s",
            provider, subject, to, exc.code, exc.read()[:300].decode("utf-8", "replace"),
        )
    except Exception:
        log.exception("Could not send email %r to %s using %s", subject, to, provider)


def password_reset_email(name: str, link: str, minutes: int) -> tuple[str, str]:
    subject = "Reset your Church Attendance password"
    body = (
        f"Hello {name},\n\n"
        "We received a request to reset your password. Open this link to choose a new one. "
        f"It works once and expires in {minutes} minutes:\n\n"
        f"{link}\n\n"
        "If you did not ask for this, you can ignore this email. Your password stays the same.\n"
    )
    return subject, body


def department_decision_email(name: str, department: str, approved: bool) -> tuple[str, str]:
    if approved:
        subject = f"You are now a member of {department}"
        body = (
            f"Hello {name},\n\n"
            f"An admin approved your request to join {department}. "
            "You can now see and clock in to its services.\n"
        )
    else:
        subject = f"Your request to join {department}"
        body = (
            f"Hello {name},\n\n"
            f"An admin did not approve your request to join {department} this time. "
            "If you think this is a mistake, please speak to a church admin.\n"
        )
    return subject, body
