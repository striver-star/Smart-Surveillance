"""HSS platform API: login and users, console data, health, events, wall PCs and notifications."""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from . import alerts, auth, clips, console, devices, events, eventsetup, evidence, geo, legal, notify, nvrs, screens, wall
from .reports import service as reports
from .db import connect, migrate

VERSION = "0.12.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    watcher = asyncio.create_task(notify.background_loop())
    scheduler = asyncio.create_task(reports.background_loop())
    escalator = asyncio.create_task(alerts.background_loop())
    gateway_sync = asyncio.create_task(nvrs.background_loop())
    vault_cleanup = asyncio.create_task(evidence.background_loop())
    geo_checks = asyncio.create_task(geo.background_loop())
    yield
    geo_checks.cancel()
    vault_cleanup.cancel()
    gateway_sync.cancel()
    watcher.cancel()
    scheduler.cancel()
    escalator.cancel()


app = FastAPI(title="HSS Platform API", version=VERSION, lifespan=lifespan)
app.include_router(auth.router)
app.include_router(console.router)
app.include_router(evidence.router)
app.include_router(eventsetup.router)
app.include_router(geo.router)
app.include_router(alerts.router)
app.include_router(devices.router)
app.include_router(nvrs.router)
app.include_router(legal.router)
app.include_router(clips.router)
app.include_router(reports.router)
app.include_router(events.router)
app.include_router(screens.router)
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
