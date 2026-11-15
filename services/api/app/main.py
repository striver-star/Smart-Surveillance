"""HSS platform API: login and users, console data, health, events, wall PCs and notifications."""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from . import alerts, auth, console, events, notify, wall
from .reports import service as reports
from .db import connect, migrate

VERSION = "0.7.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    watcher = asyncio.create_task(notify.background_loop())
    scheduler = asyncio.create_task(reports.background_loop())
    escalator = asyncio.create_task(alerts.background_loop())
    yield
    watcher.cancel()
    scheduler.cancel()
    escalator.cancel()


app = FastAPI(title="HSS Platform API", version=VERSION, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(console.router)
app.include_router(alerts.router)
app.include_router(reports.router)
app.include_router(events.router)
app.include_router(wall.router)
app.include_router(notify.router)


@app.get("/version")
def version() -> dict:
    return {"service": "api", "version": VERSION, "timezone": os.environ.get("HSS_TZ", "UTC")}


@app.get("/healthz")
def healthz(response: Response) -> dict:
    checks = {"api": "ok"}
    try:
        with connect(connect_timeout=3) as conn:
            postgis = conn.execute("SELECT postgis_version()").fetchone()[0]
        checks["database"] = "ok"
        checks["postgis"] = postgis
    except Exception as exc:  # report, do not crash the health endpoint
        checks["database"] = f"error: {exc.__class__.__name__}"
        response.status_code = 503
    return checks
