"""HSS platform API. Step 0: health and version endpoints only."""
import os

import psycopg
from fastapi import FastAPI, Response

VERSION = "0.1.0"

app = FastAPI(title="HSS Platform API", version=VERSION)


def database_url() -> str:
    return os.environ["HSS_DATABASE_URL"]


@app.get("/version")
def version() -> dict:
    return {"service": "api", "version": VERSION, "timezone": os.environ.get("HSS_TZ", "UTC")}


@app.get("/healthz")
def healthz(response: Response) -> dict:
    checks = {"api": "ok"}
    try:
        with psycopg.connect(database_url(), connect_timeout=3) as conn:
            postgis = conn.execute("SELECT postgis_version()").fetchone()[0]
        checks["database"] = "ok"
        checks["postgis"] = postgis
    except Exception as exc:  # report, do not crash the health endpoint
        checks["database"] = f"error: {exc.__class__.__name__}"
        response.status_code = 503
    return checks
