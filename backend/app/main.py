from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.core.config import settings
from app.routers import (
    account,
    attendance,
    auth,
    checkin,
    departments,
    members,
    passkeys,
    services,
    users,
)

production = settings.ENVIRONMENT == "production"
app = FastAPI(
    title="Church Attendance API",
    # the interactive API docs are only for development
    docs_url=None if production else "/docs",
    redoc_url=None if production else "/redoc",
    openapi_url=None if production else "/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for router in (
    auth.router,
    users.router,
    attendance.router,
    services.router,
    departments.router,
    members.router,
    account.router,
    checkin.router,
    passkeys.router,
):
    app.include_router(router, prefix="/api")

Path(settings.MEDIA_DIR, "avatars").mkdir(parents=True, exist_ok=True)
app.mount("/api/media", StaticFiles(directory=settings.MEDIA_DIR), name="media")


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path.startswith("/api/"):
        # Never cache API answers. The check-in code changes every 30 seconds and everything
        # else is personal, and hosts such as Vercel can cache proxied responses.
        response.headers.setdefault("Cache-Control", "no-store")  # a route may set its own
    return response


@app.get("/api/health")
def health():
    return {"status": "ok"}
