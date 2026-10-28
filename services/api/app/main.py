"""HSS platform API. Health, version, and event ingestion for the PoC."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response

from . import events
from .db import connect, migrate

VERSION = "0.2.0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    yield


app = FastAPI(title="HSS Platform API", version=VERSION, lifespan=lifespan)
app.include_router(events.router)


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
