from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATABASE_URL: str
    SECRET_KEY: str

    # "production" turns on stricter checks (see _production_checks) and hides /docs
    ENVIRONMENT: Literal["development", "production"] = "development"

    ACCESS_TOKEN_MINUTES: int = 30
    REFRESH_TOKEN_DAYS: int = 30
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    MEDIA_DIR: str = "media"
    # how long before a service starts that people may clock in
    CHECKIN_OPENS_MINUTES_BEFORE: int = 120
    # Clock-out is only possible once the service has ended: it opens this many minutes before
    # the end time (0 = exactly at the end) and closes this many minutes after it.
    CHECKOUT_OPENS_MINUTES_BEFORE_END: int = 0
    CHECKOUT_CLOSES_MINUTES_AFTER_END: int = 120

    # public address of the web app; used for the links inside emails
    WEB_BASE_URL: str = "http://localhost:5173"
    PASSWORD_RESET_MINUTES: int = 60

    # Passkeys (fingerprint / face check-in). Leave these empty and they are worked out from
    # WEB_BASE_URL. Passkeys only work on https:// addresses (and on localhost).
    WEBAUTHN_RP_NAME: str = "Church Attendance"
    WEBAUTHN_RP_ID: str | None = None  # the domain, e.g. attendance.yourchurch.org
    WEBAUTHN_ORIGINS: list[str] = []  # e.g. ["https://attendance.yourchurch.org"]

    # brute-force protection on login, signup and password reset
    RATE_LIMIT_ENABLED: bool = True

    # outgoing email (leave SMTP_HOST empty to disable: links are then printed in the
    # server console during development instead of being emailed)
    # Sender address, e.g. Church Attendance <no-reply@yourchurch.org>. Used by every way of
    # sending (falls back to SMTP_FROM). Brevo / Resend need it to be a sender you verified.
    EMAIL_FROM: str | None = None
    # Send through a web API instead of SMTP. Needed on hosts that block SMTP (Render free plan).
    BREVO_API_KEY: str | None = None
    RESEND_API_KEY: str | None = None

    SMTP_HOST: str | None = None
    SMTP_PORT: int = 587
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM: str | None = None  # e.g. Church Attendance <no-reply@yourchurch.org>
    SMTP_SECURITY: Literal["starttls", "ssl", "none"] = "starttls"

    @model_validator(mode="after")
    def _production_checks(self):
        if self.ENVIRONMENT == "production":
            weak = len(self.SECRET_KEY) < 32 or self.SECRET_KEY.lower().startswith("change")
            if weak:
                raise ValueError(
                    "SECRET_KEY is too weak for production. Generate one with: "
                    'python -c "import secrets; print(secrets.token_urlsafe(48))"'
                )
        return self


settings = Settings()
