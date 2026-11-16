"""Face and plate recognition, stage 4 (go-live): watchlists, the recognition worker's feed, and operator
verdicts on matches.

Privacy by design (DPIA and legal review, docs/recognition.md):
- Watchlist only: a face or plate is compared with the enrolled entries and nothing else. The worker posts
  matches only; unmatched faces and plates are discarded in memory.
- Every entry has a list, a reason, a consent or legal authority reference and an expiry date; expired entries
  stop matching at once. Deleting a person deletes their photos and face data.
- Only the CSO and administrators manage watchlists, and only while the legal review is in force for that feature.
- A match is a lead, not proof: it raises an alert with the enrolment photo beside the live picture, and an
  operator confirms it or marks it "not this person". Verdicts (camera, score, outcome; no names) are kept to
  measure accuracy and tune the thresholds.
- Match records are deleted after HSS_RECOGNITION_DAYS (30) unless their alert is still open.
- Enrolments, changes, deletions, photo views and verdicts are written to the audit log.
"""
from __future__ import annotations

import base64
import binascii
import io
import os
import re
import shutil
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token

router = APIRouter(prefix="/recognition", tags=["recognition"])
MANAGE = ("admin", "cso")
OPERATE = ("admin", "cso", "operator")
FACE_LISTS = {"barred": ("Barred", "critical"), "watch": ("Watch", "warning"), "vip": ("VIP", "info"),
              "trial": ("Trial volunteers", "warning")}
PLATE_LISTS = {"block": ("Blocked", "critical"), "watch": ("Watch", "warning"), "allow": ("Allowed", None)}
MAX_PHOTOS = 5
MAX_YEAR = 366
DEFAULTS = {"cameras": [], "face_threshold": 0.40, "face_margin": 0.06, "plate_min_confidence": 0.80, "repeat_s": 60}


def data_dir() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data")) / "watchlist"


def normalise_plate(raw: str) -> str:
    """Letters and digits, upper case (pure, tested): 'lsr-123 ab' -> 'LSR123AB'."""
    return re.sub(r"[^A-Z0-9]", "", (raw or "").upper())


def _unlocked(scope: str) -> bool:
    from .legal import unlocked
    return unlocked(scope)


def _need(scope: str) -> None:
    if not _unlocked(scope):
        raise HTTPException(status_code=423, detail=f"{scope.capitalize()} recognition is locked: accept the legal review first (Face & plate).")


def config() -> dict:
    with connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = 'recognition'").fetchone()
    return {**DEFAULTS, **((r[0] if r else None) or {})}


def _expiry(d: date) -> date:
    today = date.today()
    if d <= today:
        raise HTTPException(status_code=422, detail="The expiry date must be in the future.")
    if (d - today).days > MAX_YEAR:
        raise HTTPException(status_code=422, detail="Entries expire within 12 months; renew them when the reason still holds.")
    return d


# ------------------------------------------------------------------ settings: cameras and thresholds

class CameraIn(BaseModel):
    camera_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    face: bool = True
    plate: bool = False
    roi: list[float] | None = None          # x1, y1, x2, y2 as fractions, for a fixed lane (plates)


class ConfigIn(BaseModel):
    cameras: list[CameraIn] = Field(default_factory=list, max_length=16)
    face_threshold: float = Field(default=0.40, ge=0.30, le=0.80)
    face_margin: float = Field(default=0.06, ge=0.0, le=0.30)
    plate_min_confidence: float = Field(default=0.80, ge=0.5, le=0.99)
    repeat_s: int = Field(default=60, ge=10, le=3600)


@router.get("/config")
def get_config(_: dict = Depends(require(*MANAGE))) -> dict:
    from .legal import status
    st = status()
    return {**config(), "unlocked": {"face": bool(st.get("face")), "plate": bool(st.get("plate"))},
            "face_lists": {k: {"label": v[0], "severity": v[1]} for k, v in FACE_LISTS.items()},
            "plate_lists": {k: {"label": v[0], "severity": v[1]} for k, v in PLATE_LISTS.items()},
            "worker": worker_seen()}


@router.put("/config")
def put_config(body: ConfigIn, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    for c in body.cameras:
        if c.roi is not None and (len(c.roi) != 4 or not (0 <= c.roi[0] < c.roi[2] <= 1 and 0 <= c.roi[1] < c.roi[3] <= 1)):
            raise HTTPException(status_code=422, detail=f"{c.camera_id}: the area must be four fractions x1, y1, x2, y2")
    value = body.model_dump()
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('recognition', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (Jsonb(value),))
    audit("recognition_config_changed", user_id=user["id"], username=user["username"], ip=client_ip(request),
          cameras=[f"{c.camera_id}{' face' if c.face else ''}{' plate' if c.plate else ''}" for c in body.cameras],
          face_threshold=body.face_threshold, face_margin=body.face_margin, plate_min_confidence=body.plate_min_confidence)
    return get_config(user)


# ------------------------------------------------------------------ face watchlist

class PersonIn(BaseModel):
    list: str
    name: str = Field(min_length=2, max_length=80)
    reason: str = Field(min_length=5, max_length=300)
    authority_ref: str = Field(min_length=3, max_length=120)
    expires_at: date


def _person(pid: uuid.UUID) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT id, list, name, reason, authority_ref, expires_at, added_by, added_at, active FROM watch_people WHERE id = %s",
                         (pid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such person")
    return dict(zip(["id", "list", "name", "reason", "authority_ref", "expires_at", "added_by", "added_at", "active"], r))


@router.get("/people")
def people(_: dict = Depends(require(*MANAGE))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT p.id, p.list, p.name, p.reason, p.authority_ref, p.expires_at, p.added_by, p.added_at, p.active, "
            "coalesce(json_agg(json_build_object('id', f.id, 'status', f.status, 'problem', f.problem)) FILTER (WHERE f.id IS NOT NULL), '[]') "
            "FROM watch_people p LEFT JOIN watch_faces f ON f.person_id = p.id GROUP BY p.id ORDER BY p.list, lower(p.name)").fetchall()
    today = date.today()
    return [{"id": str(i), "list": li, "name": n, "reason": r, "authority_ref": a, "expires_at": e, "added_by": b, "added_at": at,
             "active": act, "expired": e < today, "faces": f} for i, li, n, r, a, e, b, at, act, f in rows]


@router.post("/people", status_code=201)
def add_person(body: PersonIn, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    _need("face")
    if body.list not in FACE_LISTS:
        raise HTTPException(status_code=422, detail=f"list must be one of {', '.join(FACE_LISTS)}")
    with connect() as conn:
        pid = conn.execute("INSERT INTO watch_people (list, name, reason, authority_ref, expires_at, added_by) VALUES (%s, %s, %s, %s, %s, %s) "
                           "RETURNING id", (body.list, body.name.strip(), body.reason.strip(), body.authority_ref.strip(),
                                            _expiry(body.expires_at), user["username"])).fetchone()[0]
    audit("watchlist_person_added", user_id=user["id"], username=user["username"], ip=client_ip(request), person=str(pid),
          list=body.list, authority=body.authority_ref, expires=str(body.expires_at))
    return {"id": str(pid)}


class PersonEdit(BaseModel):
    list: str | None = None
    reason: str | None = Field(default=None, min_length=5, max_length=300)
    authority_ref: str | None = Field(default=None, min_length=3, max_length=120)
    expires_at: date | None = None
    active: bool | None = None


@router.put("/people/{pid}")
def edit_person(pid: uuid.UUID, body: PersonEdit, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    _need("face")
    _person(pid)
    if body.list is not None and body.list not in FACE_LISTS:
        raise HTTPException(status_code=422, detail=f"list must be one of {', '.join(FACE_LISTS)}")
    sets, args = [], []
    for col in ("list", "reason", "authority_ref", "active"):
        v = getattr(body, col)
        if v is not None:
            sets.append(f"{col} = %s")
            args.append(v.strip() if isinstance(v, str) else v)
    if body.expires_at is not None:
        sets.append("expires_at = %s")
        args.append(_expiry(body.expires_at))
    if not sets:
        raise HTTPException(status_code=422, detail="nothing to change")
    with connect() as conn:
        conn.execute(f"UPDATE watch_people SET {', '.join(sets)}, updated_at = now() WHERE id = %s", (*args, pid))
    audit("watchlist_person_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), person=str(pid),
          **{k: str(v) for k, v in body.model_dump(exclude_none=True).items()})
    return {"ok": True}


@router.delete("/people/{pid}")
def delete_person(pid: uuid.UUID, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    """Deletes the person, their photos and their face data. Past match alerts keep their own snapshots."""
    p = _person(pid)
    with connect() as conn:
        conn.execute("DELETE FROM watch_people WHERE id = %s", (pid,))
    shutil.rmtree(data_dir() / str(pid), ignore_errors=True)
    audit("watchlist_person_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), person=str(pid), list=p["list"])
    return {"deleted": True}


class PhotoIn(BaseModel):
    image_data_url: str = Field(max_length=8_000_000)


@router.post("/people/{pid}/photos", status_code=201)
def add_photo(pid: uuid.UUID, body: PhotoIn, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    _need("face")
    _person(pid)
    m = re.match(r"^data:image/(jpeg|png|webp);base64,(.+)$", body.image_data_url, re.S)
    if not m:
        raise HTTPException(status_code=422, detail="The photo must be a JPEG, PNG or WebP image.")
    try:
        raw = base64.b64decode(m.group(2), validate=True)
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(raw)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")      # upright, and no EXIF (location, device) kept
            if min(im.size) < 160:
                raise HTTPException(status_code=422, detail="The photo is too small; use at least 160 pixels on the short side.")
            out = io.BytesIO()
            im.save(out, "JPEG", quality=92)
    except (binascii.Error, OSError) as exc:
        raise HTTPException(status_code=422, detail="That file isn't a readable image.") from exc
    with connect() as conn:
        n = conn.execute("SELECT count(*) FROM watch_faces WHERE person_id = %s AND status <> 'rejected'", (pid,)).fetchone()[0]
        if n >= MAX_PHOTOS:
            raise HTTPException(status_code=409, detail=f"{MAX_PHOTOS} photos at most; delete one first.")
        fid = uuid.uuid4()
        folder = data_dir() / str(pid)
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{fid}.jpg").write_bytes(out.getvalue())
        conn.execute("INSERT INTO watch_faces (id, person_id, file) VALUES (%s, %s, %s)", (fid, pid, f"{pid}/{fid}.jpg"))
    audit("watchlist_photo_added", user_id=user["id"], username=user["username"], ip=client_ip(request), person=str(pid))
    return {"id": str(fid), "status": "pending"}


@router.delete("/people/{pid}/photos/{fid}")
def delete_photo(pid: uuid.UUID, fid: uuid.UUID, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM watch_faces WHERE id = %s AND person_id = %s RETURNING file", (fid, pid)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such photo")
    (data_dir() / r[0]).unlink(missing_ok=True)
    audit("watchlist_photo_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), person=str(pid))
    return {"deleted": True}


@router.get("/people/{pid}/photos/{fid}")
def photo(pid: uuid.UUID, fid: uuid.UUID, request: Request, user: dict = Depends(require(*OPERATE))) -> Response:
    """An enrolment photo: for the CSO managing the list, and for operators checking a match."""
    with connect() as conn:
        r = conn.execute("SELECT file FROM watch_faces WHERE id = %s AND person_id = %s", (fid, pid)).fetchone()
    if not r or not (data_dir() / r[0]).exists():
        raise HTTPException(status_code=404, detail="no such photo")
    if _views.should_log(user["username"], str(pid)):
        audit("watchlist_photo_viewed", user_id=user["id"], username=user["username"], ip=client_ip(request), person=str(pid))
    return Response((data_dir() / r[0]).read_bytes(), media_type="image/jpeg",
                    headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})


class _ViewLog:
    """One audit line per person and viewer per 10 minutes (a page shows several photos)."""
    def __init__(self):
        self.lock, self.seen = threading.Lock(), {}

    def should_log(self, user: str, person: str) -> bool:
        now = time.monotonic()
        with self.lock:
            if now - self.seen.get((user, person), -1e9) < 600:
                return False
            self.seen[(user, person)] = now
            return True


_views = _ViewLog()


# ------------------------------------------------------------------ plate watchlist

class PlateIn(BaseModel):
    plate: str = Field(min_length=3, max_length=20)
    list: str
    name: str = Field(default="", max_length=80)
    reason: str = Field(min_length=3, max_length=300)
    authority_ref: str = Field(min_length=3, max_length=120)
    expires_at: date


@router.get("/plates")
def plates(_: dict = Depends(require(*MANAGE))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, plate, list, name, reason, authority_ref, expires_at, added_by, added_at, active FROM watch_plates "
                            "ORDER BY list, plate").fetchall()
    today = date.today()
    return [{"id": str(i), "plate": p, "list": li, "name": n, "reason": r, "authority_ref": a, "expires_at": e, "added_by": b,
             "added_at": at, "active": act, "expired": e < today} for i, p, li, n, r, a, e, b, at, act in rows]


@router.post("/plates", status_code=201)
def add_plate(body: PlateIn, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    _need("plate")
    plate = normalise_plate(body.plate)
    if not 3 <= len(plate) <= 12:
        raise HTTPException(status_code=422, detail="A plate has 3 to 12 letters and digits.")
    if body.list not in PLATE_LISTS:
        raise HTTPException(status_code=422, detail=f"list must be one of {', '.join(PLATE_LISTS)}")
    try:
        with connect() as conn:
            pid = conn.execute("INSERT INTO watch_plates (plate, list, name, reason, authority_ref, expires_at, added_by) "
                               "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                               (plate, body.list, body.name.strip(), body.reason.strip(), body.authority_ref.strip(),
                                _expiry(body.expires_at), user["username"])).fetchone()[0]
    except Exception as exc:
        if "watch_plates_plate" in str(exc):
            raise HTTPException(status_code=409, detail=f"{plate} is already on a list.") from exc
        raise
    audit("watchlist_plate_added", user_id=user["id"], username=user["username"], ip=client_ip(request), plate=plate, list=body.list,
          authority=body.authority_ref, expires=str(body.expires_at))
    return {"id": str(pid), "plate": plate}


@router.delete("/plates/{pid}")
def delete_plate(pid: uuid.UUID, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM watch_plates WHERE id = %s RETURNING plate, list", (pid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such plate")
    audit("watchlist_plate_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), plate=r[0], list=r[1])
    return {"deleted": True}


# ------------------------------------------------------------------ matches: what operators see, and their verdicts

@router.get("/matches/{alert_id}")
def match(alert_id: uuid.UUID, user: dict = Depends(require(*OPERATE))) -> dict:
    from .access import check
    from .alerts import get_alert
    a = get_alert(alert_id)
    check(user, a["camera_id"])
    with connect() as conn:
        raw = conn.execute("SELECT raw FROM events WHERE id = %s", (a["event_id"],)).fetchone()[0] or {}
        v = conn.execute("SELECT verdict, username, at, note FROM recognition_verdicts WHERE alert_id = %s", (alert_id,)).fetchone()
    out = {"alert_id": str(alert_id), "kind": raw.get("kind"), "score": raw.get("score"), "margin": raw.get("margin"),
           "verdict": dict(zip(["verdict", "username", "at", "note"], v)) if v else None}
    if raw.get("kind") == "face":
        pid = raw.get("person_id")
        with connect() as conn:
            p = conn.execute("SELECT name, list, reason, expires_at FROM watch_people WHERE id::text = %s", (pid,)).fetchone()
            faces = conn.execute("SELECT id FROM watch_faces WHERE person_id::text = %s AND status = 'ok' ORDER BY added_at", (pid,)).fetchall()
        out.update(person_id=pid, name=p[0] if p else raw.get("name"), list=(p[1] if p else raw.get("list")),
                   list_label=FACE_LISTS.get(p[1] if p else raw.get("list"), ("?",))[0], reason=p[2] if p else "(entry deleted)",
                   photos=[f"/api/recognition/people/{pid}/photos/{f[0]}" for f in faces] if p else [])
    elif raw.get("kind") == "plate":
        out.update(plate=raw.get("plate"), list=raw.get("list"), list_label=PLATE_LISTS.get(raw.get("list"), ("?",))[0],
                   name=raw.get("name", ""), read_confidence=raw.get("confidence"))
    return out


class VerdictIn(BaseModel):
    verdict: str = Field(pattern="^(confirmed|rejected)$")
    note: str = Field(default="", max_length=500)


@router.post("/matches/{alert_id}/verdict")
def verdict(alert_id: uuid.UUID, body: VerdictIn, request: Request, user: dict = Depends(require(*OPERATE))) -> dict:
    """Confirm a match after comparing the pictures, or mark it 'not this person' (which closes the alert as a
    false alarm). Each verdict is final; the CSO can see them all on the Face & plate page."""
    from .access import check
    from .alerts import add_timeline, broker, get_alert
    a = get_alert(alert_id)
    check(user, a["camera_id"])
    with connect() as conn:
        raw = conn.execute("SELECT raw FROM events WHERE id = %s", (a["event_id"],)).fetchone()[0] or {}
        if raw.get("kind") not in ("face", "plate"):
            raise HTTPException(status_code=422, detail="This alert isn't a recognition match.")
        if conn.execute("SELECT 1 FROM recognition_verdicts WHERE alert_id = %s", (alert_id,)).fetchone():
            raise HTTPException(status_code=409, detail="This match already has a verdict.")
        conn.execute("INSERT INTO recognition_verdicts (alert_id, verdict, username, note, camera_id, kind, score) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (alert_id, body.verdict, user["username"], body.note.strip(), a["camera_id"], raw["kind"], raw.get("score")))
        what = "the same person" if raw["kind"] == "face" else "the same plate"
        add_timeline(conn, alert_id, "verdict", (f"Match confirmed: {what}" if body.verdict == "confirmed" else "Not a match")
                     + (f". {body.note.strip()}" if body.note.strip() else ""), user["username"])
        if body.verdict == "rejected" and a["status"] != "closed":
            conn.execute("UPDATE alerts SET status = 'closed', close_reason = 'false_alarm', closed_by = %s, closed_at = now() WHERE id = %s",
                         (user["username"], alert_id))
            add_timeline(conn, alert_id, "closed", "Closed as false alarm (not a match)", user["username"])
        elif body.verdict == "confirmed" and a["status"] == "open":
            conn.execute("UPDATE alerts SET status = 'acknowledged', acknowledged_by = %s, acknowledged_at = now(), "
                         "assigned_to = coalesce(assigned_to, %s) WHERE id = %s", (user["username"], user["username"], alert_id))
    try:                                  # a verdict ends any siren or light the match switched on, as acknowledging does
        from .outputs import silence_alert
        silenced = silence_alert(str(alert_id))
        if silenced:
            with connect() as conn:
                add_timeline(conn, alert_id, "outputs", "Silenced: " + ", ".join(silenced), user["username"])
    except Exception:
        pass
    audit("recognition_verdict", user_id=user["id"], username=user["username"], ip=client_ip(request), alert=str(alert_id),
          verdict=body.verdict, kind=raw["kind"], camera=a["camera_id"])
    broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
    return {"verdict": body.verdict}


def suggest_threshold(confirmed: list[float], rejected: list[float], current: float) -> float | None:
    """A face threshold from operator verdicts (pure, tested): just above the highest score operators rejected,
    unless that would also drop more than a tenth of confirmed matches. None until there are 20 verdicts."""
    if len(confirmed) + len(rejected) < 20 or not rejected:
        return None
    cand = round(max(rejected) + 0.01, 2)
    lost = sum(1 for s in confirmed if s < cand) / max(1, len(confirmed))
    if lost > 0.10:
        return None
    return max(cand, current) if cand > current else None


@router.get("/stats")
def stats(days: int = 90, _: dict = Depends(require(*MANAGE))) -> dict:
    days = max(1, min(days, 365))
    with connect() as conn:
        rows = conn.execute("SELECT camera_id, kind, verdict, score FROM recognition_verdicts WHERE at > now() - %s * interval '1 day'",
                            (days,)).fetchall()
        open_matches = conn.execute("SELECT count(*) FROM alerts a JOIN events e ON e.id = a.event_id LEFT JOIN recognition_verdicts v "
                                    "ON v.alert_id = a.id WHERE e.type IN ('face_match', 'plate_match') AND v.alert_id IS NULL").fetchone()[0]
    per: dict[tuple[str, str], dict] = {}
    for cam, kind, v, score in rows:
        d = per.setdefault((cam, kind), {"camera_id": cam, "kind": kind, "confirmed": 0, "rejected": 0})
        d[v] += 1
    from .alerts import camera_label
    out = []
    for d in per.values():
        n = d["confirmed"] + d["rejected"]
        out.append({**d, "camera": camera_label(d["camera_id"]) or d["camera_id"], "precision": round(d["confirmed"] / n, 3) if n else None})
    face = [(v, s) for _c, k, v, s in rows if k == "face" and s is not None]
    cfg = config()
    return {"days": days, "by_camera": sorted(out, key=lambda x: (x["kind"], x["camera"])), "waiting_for_verdict": open_matches,
            "face_threshold": cfg["face_threshold"],
            "suggested_face_threshold": suggest_threshold([s for v, s in face if v == "confirmed"], [s for v, s in face if v == "rejected"],
                                                          cfg["face_threshold"]),
            "worker": worker_seen()}


# ------------------------------------------------------------------ the recognition worker's feed (worker token)

_worker: dict = {"at": None, "data": {}}


def worker_seen() -> dict:
    at = _worker["at"]
    return {"last_seen": at, "online": bool(at and datetime.now(timezone.utc) - at < timedelta(minutes=3)), **_worker["data"]}


def main_stream(camera_id: str) -> str | None:
    """The camera's main stream straight from its NVR (channel N01): the gateway only carries sub-streams,
    which are too small for faces and plates. None if the camera isn't on an NVR added in Devices; the
    worker then reads the gateway path (fine for tests, not for recognition)."""
    from urllib.parse import quote
    from .playback import _nvr
    try:
        n = _nvr(camera_id)
    except HTTPException:
        return None
    return f"rtsp://{quote(n['user'], safe='')}:{quote(n['password'], safe='')}@{n['host']}:{n['rtsp_port']}/Streaming/Channels/{n['channel']}01"


@router.get("/worker/state", dependencies=[Depends(check_worker_token)])
def worker_state() -> dict:
    """Everything the worker needs, only for features the legal review has unlocked. Expired and paused entries are left out."""
    from .legal import status
    st = status()
    face, plate = bool(st.get("face")), bool(st.get("plate"))
    cfg = config()
    people, pending, plates_out = [], [], []
    with connect() as conn:
        if face:
            for pid, name, li, emb in conn.execute(
                    "SELECT p.id, p.name, p.list, array_agg(f.embedding) FILTER (WHERE f.status = 'ok') FROM watch_people p "
                    "JOIN watch_faces f ON f.person_id = p.id WHERE p.active AND p.expires_at >= current_date GROUP BY p.id").fetchall():
                vecs = [base64.b64encode(bytes(e)).decode() for e in (emb or []) if e]
                if vecs:
                    people.append({"id": str(pid), "name": name, "list": li, "embeddings": vecs})
            pending = [str(r[0]) for r in conn.execute("SELECT id FROM watch_faces WHERE status = 'pending' ORDER BY added_at LIMIT 50").fetchall()]
        if plate:
            plates_out = [{"id": str(i), "plate": p, "list": li, "name": n} for i, p, li, n in conn.execute(
                "SELECT id, plate, list, name FROM watch_plates WHERE active AND expires_at >= current_date").fetchall()]
    cams = [{**c, "source": main_stream(c["camera_id"])} for c in cfg["cameras"] if (c.get("face") and face) or (c.get("plate") and plate)]
    return {"unlocked": {"face": face, "plate": plate}, "cameras": cams, "face_threshold": cfg["face_threshold"],
            "face_margin": cfg["face_margin"], "plate_min_confidence": cfg["plate_min_confidence"], "repeat_s": cfg["repeat_s"],
            "face_lists": {k: v[1] for k, v in FACE_LISTS.items()}, "plate_lists": {k: v[1] for k, v in PLATE_LISTS.items()},
            "people": people, "pending_faces": pending, "plates": plates_out}


@router.get("/worker/faces/{fid}/photo", dependencies=[Depends(check_worker_token)])
def worker_photo(fid: uuid.UUID) -> Response:
    with connect() as conn:
        r = conn.execute("SELECT file FROM watch_faces WHERE id = %s AND status = 'pending'", (fid,)).fetchone()
    if not r or not (data_dir() / r[0]).exists():
        raise HTTPException(status_code=404, detail="no such pending photo")
    return Response((data_dir() / r[0]).read_bytes(), media_type="image/jpeg")


class FaceResult(BaseModel):
    status: str = Field(pattern="^(ok|rejected)$")
    problem: str = Field(default="", max_length=300)
    embedding_b64: str | None = Field(default=None, max_length=2000)
    quality: dict = Field(default_factory=dict)


@router.put("/worker/faces/{fid}", dependencies=[Depends(check_worker_token)])
def worker_face_result(fid: uuid.UUID, body: FaceResult) -> dict:
    emb = None
    if body.status == "ok":
        try:
            emb = base64.b64decode(body.embedding_b64 or "", validate=True)
        except binascii.Error as exc:
            raise HTTPException(status_code=422, detail="embedding is not base64") from exc
        if len(emb) != 128 * 4:
            raise HTTPException(status_code=422, detail="embedding must be 128 float32 values")
    with connect() as conn:
        conn.execute("UPDATE watch_faces SET status = %s, problem = %s, embedding = %s, quality = %s WHERE id = %s",
                     (body.status, body.problem, emb, Jsonb(body.quality), fid))
    return {"ok": True}


class WorkerStatus(BaseModel):
    cameras: dict = Field(default_factory=dict)
    note: str = Field(default="", max_length=300)


@router.post("/worker/status", dependencies=[Depends(check_worker_token)])
def worker_status(body: WorkerStatus) -> dict:
    """Counts only (frames, faces seen, matches): no personal data."""
    _worker["at"] = datetime.now(timezone.utc)
    _worker["data"] = {"cameras": body.cameras, "note": body.note}
    return {"ok": True}
