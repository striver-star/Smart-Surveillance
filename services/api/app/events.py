"""Event ingestion for AI workers and event listing for the PoC."""
import base64
import binascii
import hmac
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .db import connect

router = APIRouter()


def snapshot_dir() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data")) / "snapshots"


class EventIn(BaseModel):
    camera_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    source_kind: Literal["edge", "nvr", "server_ai"]
    source_ref: str | None = Field(default=None, max_length=200)
    tier: Literal["E", "N", "S"]
    type: str = Field(min_length=1, max_length=50)
    object_class: str | None = Field(default=None, max_length=50)
    zone: str | None = Field(default=None, max_length=100)
    severity: Literal["info", "warning", "critical"]
    confidence: float | None = Field(default=None, ge=0, le=1)
    occurred_at: datetime
    snapshot_jpeg_b64: str | None = Field(default=None, max_length=4_000_000)
    raw: dict = Field(default_factory=dict)


def check_worker_token(authorization: str | None = Header(default=None)) -> None:
    expected = os.environ.get("HSS_WORKER_TOKEN", "")
    given = (authorization or "").removeprefix("Bearer ").strip()
    if not expected or not hmac.compare_digest(given, expected):
        raise HTTPException(status_code=401, detail="invalid worker token")


@router.post("/events", status_code=201, dependencies=[Depends(check_worker_token)])
def ingest_event(event: EventIn) -> dict:
    if event.occurred_at.tzinfo is None:
        raise HTTPException(status_code=422, detail="occurred_at needs a timezone")
    event_id = uuid.uuid4()
    snapshot_ref = None
    if event.snapshot_jpeg_b64:
        try:
            data = base64.b64decode(event.snapshot_jpeg_b64, validate=True)
        except binascii.Error:
            raise HTTPException(status_code=422, detail="snapshot is not valid base64")
        if not data.startswith(b"\xff\xd8"):
            raise HTTPException(status_code=422, detail="snapshot is not a JPEG")
        day = event.occurred_at.astimezone(timezone.utc).strftime("%Y/%m/%d")
        target = snapshot_dir() / day / f"{event_id}.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        snapshot_ref = f"snapshots/{day}/{event_id}.jpg"
    with connect() as conn:
        received_at = conn.execute(
            """INSERT INTO events (id, camera_id, source_kind, source_ref, tier, type, object_class, zone,
                                   severity, confidence, occurred_at, snapshot_ref, raw)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING received_at""",
            (event_id, event.camera_id, event.source_kind, event.source_ref, event.tier, event.type,
             event.object_class, event.zone, event.severity, event.confidence, event.occurred_at,
             snapshot_ref, Jsonb(event.raw)),
        ).fetchone()[0]
    latency_ms = round((received_at - event.occurred_at).total_seconds() * 1000)
    return {"id": str(event_id), "received_at": received_at.isoformat(), "latency_ms": latency_ms}


@router.get("/events")
def list_events(limit: int = 50, camera_id: str | None = None) -> list[dict]:
    limit = max(1, min(limit, 500))
    sql = ("SELECT id, camera_id, source_kind, source_ref, tier, type, object_class, zone, severity, confidence, "
           "occurred_at, received_at, snapshot_ref, raw FROM events")
    params: list = []
    if camera_id:
        sql += " WHERE camera_id = %s"
        params.append(camera_id)
    sql += " ORDER BY occurred_at DESC LIMIT %s"
    params.append(limit)
    with connect() as conn:
        cur = conn.execute(sql, params)
        cols = [c.name for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    for r in rows:
        r["id"] = str(r["id"])
        r["latency_ms"] = round((r["received_at"] - r["occurred_at"]).total_seconds() * 1000)
        r["snapshot_url"] = f"/api/events/{r['id']}/snapshot" if r.pop("snapshot_ref") else None
    return rows


@router.get("/events/{event_id}/snapshot")
def event_snapshot(event_id: uuid.UUID):
    with connect() as conn:
        row = conn.execute("SELECT snapshot_ref FROM events WHERE id = %s", (event_id,)).fetchone()
    if not row or not row[0]:
        raise HTTPException(status_code=404, detail="no snapshot")
    path = (snapshot_dir().parent / row[0]).resolve()
    if not path.is_relative_to(snapshot_dir().resolve()) or not path.exists():
        raise HTTPException(status_code=404, detail="no snapshot")
    return FileResponse(path, media_type="image/jpeg")
