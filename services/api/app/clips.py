"""Video clips for alerts, cut from the NVR's recording by the edge service (Phase 3 part B).

A clip covers 10 s before to 20 s after the event. Critical alerts request one automatically; the
console can request one for any alert. The edge service claims queued jobs, pulls the recording
over RTSP playback from the NVR (FFmpeg, stream copy, no re-encoding) and uploads the MP4 here.
Each clip's SHA-256 is recorded on the alert's timeline and included in the evidence export.
"""
from __future__ import annotations

import hashlib
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token

router = APIRouter(tags=["clips"])
BEFORE, AFTER, WAIT = 10, 20, 30           # seconds
MAX_BYTES = 200 * 1024 * 1024
MAX_ATTEMPTS = 3


def clip_dir() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data")) / "clips"


def request_clip(alert_id, event_id, camera_id: str, occurred_at: datetime, requested_by: str) -> str | None:
    """Queue a clip unless one is already queued or done for this alert. Camera ids that aren't NVR
    channels (nvr<octet>-ch<NN>) can't be clipped."""
    import re
    if not re.fullmatch(r"nvr\d+-ch\d{2,3}", camera_id):
        return None
    with connect() as conn:
        if conn.execute("SELECT 1 FROM clips WHERE alert_id = %s AND status IN ('queued', 'working', 'done')", (alert_id,)).fetchone():
            return None
        row = conn.execute(
            "INSERT INTO clips (alert_id, event_id, camera_id, starts_at, ends_at, not_before, requested_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (alert_id, event_id, camera_id, occurred_at - timedelta(seconds=BEFORE), occurred_at + timedelta(seconds=AFTER),
             max(occurred_at + timedelta(seconds=WAIT), datetime.now(timezone.utc)), requested_by)).fetchone()
        from .alerts import add_timeline
        add_timeline(conn, alert_id, "clip_requested", f"Clip of {BEFORE + AFTER} s requested from the NVR recording",
                     None if requested_by == "rule" else requested_by)
    return str(row[0])


def clips_for(alert_id) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, status, detail, sha256, size_bytes, starts_at, ends_at, updated_at FROM clips "
                            "WHERE alert_id = %s ORDER BY created_at", (alert_id,)).fetchall()
    return [{"id": str(i), "status": s, "detail": d, "sha256": h, "size_bytes": n, "starts_at": a, "ends_at": b,
             "updated_at": u, "url": f"/api/clips/{i}/video" if s == "done" else None}
            for i, s, d, h, n, a, b, u in rows]


@router.post("/alerts/{alert_id}/clip")
def ask_for_clip(alert_id: uuid.UUID, request: Request, user: dict = Depends(require("admin", "cso", "operator"))) -> dict:
    from .access import check
    with connect() as conn:
        cam = conn.execute("SELECT e.camera_id FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.id = %s", (alert_id,)).fetchone()
    check(user, cam[0] if cam else None)
    with connect() as conn:
        row = conn.execute("SELECT e.id, e.camera_id, e.occurred_at FROM alerts a JOIN events e ON e.id = a.event_id "
                           "WHERE a.id = %s", (alert_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="no such alert")
    job = request_clip(alert_id, row[0], row[1], row[2], user["username"])
    if job is None:
        raise HTTPException(status_code=409, detail="A clip is already on its way or done, or this camera isn't an NVR channel.")
    audit("clip_requested", user_id=user["id"], username=user["username"], ip=client_ip(request), alert=str(alert_id))
    _publish(alert_id)
    return {"clip": job}


# ------------------------------------------------------------------ edge service side (worker token)

@router.get("/clips/next", dependencies=[Depends(check_worker_token)])
def next_job() -> dict:
    with connect() as conn:
        conn.execute("UPDATE clips SET status = 'queued' WHERE status = 'working' AND updated_at < now() - interval '10 minutes'")
        row = conn.execute("SELECT id, camera_id, starts_at, ends_at FROM clips WHERE status = 'queued' AND not_before <= now() "
                           "ORDER BY not_before LIMIT 1 FOR UPDATE SKIP LOCKED").fetchone()
        if not row:
            return {"job": None}
        conn.execute("UPDATE clips SET status = 'working', attempts = attempts + 1, updated_at = now() WHERE id = %s", (row[0],))
    return {"job": {"id": str(row[0]), "camera_id": row[1], "starts_at": row[2].isoformat(), "ends_at": row[3].isoformat()}}


@router.put("/clips/{clip_id}", dependencies=[Depends(check_worker_token)])
async def upload(clip_id: uuid.UUID, request: Request) -> dict:
    data = await request.body()
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="clip too large")
    if len(data) < 1000 or data[4:8] != b"ftyp":
        raise HTTPException(status_code=422, detail="not an MP4 file")
    digest = hashlib.sha256(data).hexdigest()
    with connect() as conn:
        row = conn.execute("SELECT alert_id, starts_at FROM clips WHERE id = %s", (clip_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="no such clip")
        folder = clip_dir() / f"{row[1]:%Y}" / f"{row[1]:%m}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{clip_id}.mp4"
        path.write_bytes(data)
        conn.execute("UPDATE clips SET status = 'done', path = %s, sha256 = %s, size_bytes = %s, detail = '', updated_at = now() "
                     "WHERE id = %s", (str(path.relative_to(clip_dir().parent)), digest, len(data), clip_id))
        from .alerts import add_timeline
        add_timeline(conn, row[0], "clip_ready", f"Clip ready ({len(data) // 1024} KB), SHA-256 {digest}")
    _publish(row[0])
    return {"sha256": digest}


class FailIn(BaseModel):
    detail: str = Field(max_length=500)


@router.post("/clips/{clip_id}/fail", dependencies=[Depends(check_worker_token)])
def failed(clip_id: uuid.UUID, body: FailIn) -> dict:
    with connect() as conn:
        row = conn.execute("SELECT alert_id, attempts FROM clips WHERE id = %s", (clip_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="no such clip")
        final = row[1] >= MAX_ATTEMPTS
        conn.execute("UPDATE clips SET status = %s, detail = %s, not_before = now() + interval '60 seconds', updated_at = now() "
                     "WHERE id = %s", ("failed" if final else "queued", body.detail, clip_id))
        if final:
            from .alerts import add_timeline
            add_timeline(conn, row[0], "clip_failed", f"Clip not available after {row[1]} tries: {body.detail}")
    _publish(row[0])
    return {"final": final}


@router.get("/clips/{clip_id}/video")
def video(clip_id: uuid.UUID, user: dict = Depends(require("admin", "cso", "operator", "viewer"))):
    from .access import allowed
    with connect() as conn:
        row = conn.execute("SELECT path, camera_id FROM clips WHERE id = %s AND status = 'done'", (clip_id,)).fetchone()
    if not row or not allowed(user, row[1]):
        raise HTTPException(status_code=404, detail="clip not ready")
    path = (clip_dir().parent / row[0]).resolve()
    if not path.is_relative_to(clip_dir().resolve()) or not path.exists():
        raise HTTPException(status_code=404, detail="clip file missing")
    return FileResponse(path, media_type="video/mp4")


def clip_file(alert_id) -> tuple[Path, str] | None:
    with connect() as conn:
        row = conn.execute("SELECT path, sha256 FROM clips WHERE alert_id = %s AND status = 'done' ORDER BY created_at DESC LIMIT 1",
                           (alert_id,)).fetchone()
    if not row:
        return None
    p = clip_dir().parent / row[0]
    return (p, row[1]) if p.exists() else None


def _publish(alert_id) -> None:
    from .alerts import broker, get_alert
    try:
        broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
    except HTTPException:
        pass
