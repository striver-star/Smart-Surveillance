"""Smart search (release 2.0, third batch): find people and vehicles by colour in the pictures of stored events.

The attribute service (ai-worker, worker/attributes.py) analyses each event snapshot and stores the people
and vehicles in it with their colours (a person's top and bottom, a vehicle's body). This module feeds that
service and answers searches such as "person, red top, blue bottom, gate cameras, last night".

Nobody is identified: clothing and vehicle colours only. Face and plate recognition snapshots are never
analysed or returned. Searches respect each user's camera list, and every search is written to the audit log.
"""
from __future__ import annotations

import io
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token

router = APIRouter(prefix="/search", tags=["search"])
SEARCHERS = ("admin", "cso", "operator", "viewer")
COLOURS = ("black", "white", "grey", "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown")
SKIP_TYPES = ("face_match", "plate_match", "nvr_offline", "nvr_online", "camera_offline", "camera_online", "drive_fault", "drive_ok",
              "unit_offline", "unit_online", "low_battery", "missed_patrol", "checkpoint_visit", "sos")
BACKFILL_DAYS = 90


def data_dir() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data"))


def slot(camera_id: str, obj: dict, grid: int = 40) -> tuple:
    """Where an object stands in the picture, coarsely (pure, tested): the same parked car or fixed object in
    many pictures falls in the same slot, so a search shows it once with a count instead of a page of copies."""
    x1, y1, x2, y2 = obj.get("box") or (0, 0, 0, 0)
    looks = tuple(tuple(obj.get(k, [])) for k in ("upper", "lower", "body"))      # different clothes = a different person
    return (camera_id, obj.get("class"), round((x1 + x2) / 2 / grid), round((y1 + y2) / 2 / grid), round((x2 - x1) / grid), looks)


def matches(obj: dict, what: str, upper: list[str], lower: list[str], body: list[str]) -> bool:
    """Whether one found object fits the search (pure, tested). Colour lists are 'any of'; an empty list is any colour."""
    if what == "person":
        if obj.get("class") != "human":
            return False
        return (not upper or bool(set(upper) & set(obj.get("upper", [])))) and (not lower or bool(set(lower) & set(obj.get("lower", []))))
    if what == "vehicle":
        return obj.get("class") == "vehicle" and (not body or bool(set(body) & set(obj.get("body", []))))
    return obj.get("class") in ("human", "vehicle")


# ------------------------------------------------------------------ the attribute service's feed (worker token)

@router.get("/worker/next", dependencies=[Depends(check_worker_token)])
def worker_next(limit: int = 20) -> list[dict]:
    """Events with a picture and no attributes yet: the last day first, then older ones (back to 90 days)."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT e.id FROM events e LEFT JOIN event_attributes x ON x.event_id = e.id WHERE x.event_id IS NULL "
            "AND e.snapshot_ref IS NOT NULL AND NOT (e.type = ANY(%s)) AND e.occurred_at > now() - %s * interval '1 day' "
            "ORDER BY (e.occurred_at > now() - interval '1 day') DESC, e.occurred_at DESC LIMIT %s",
            (list(SKIP_TYPES), BACKFILL_DAYS, max(1, min(limit, 100)))).fetchall()
    return [{"id": str(r[0])} for r in rows]


def _snapshot(event_id) -> tuple[Path, dict]:
    with connect() as conn:
        r = conn.execute("SELECT snapshot_ref, camera_id, type, occurred_at FROM events WHERE id = %s", (event_id,)).fetchone()
    if not r or not r[0] or r[2] in ("face_match", "plate_match"):
        raise HTTPException(status_code=404, detail="no picture")
    p = (data_dir() / r[0]).resolve()
    if not p.is_relative_to((data_dir() / "snapshots").resolve()) or not p.exists():
        raise HTTPException(status_code=404, detail="no picture")
    return p, {"camera_id": r[1], "type": r[2], "occurred_at": r[3]}


@router.get("/worker/snapshot/{event_id}", dependencies=[Depends(check_worker_token)])
def worker_snapshot(event_id: uuid.UUID) -> Response:
    p, _ = _snapshot(event_id)
    return Response(p.read_bytes(), media_type="image/jpeg")


class AttributesIn(BaseModel):
    objects: list[dict] = Field(default_factory=list, max_length=50)
    ok: bool = True


@router.put("/worker/attributes/{event_id}", dependencies=[Depends(check_worker_token)])
def worker_attributes(event_id: uuid.UUID, body: AttributesIn) -> dict:
    clean = []
    for o in body.objects:
        if o.get("class") not in ("human", "vehicle"):
            continue
        item = {"class": o["class"], "confidence": float(o.get("confidence", 0)), "box": [int(v) for v in (o.get("box") or [0, 0, 0, 0])[:4]]}
        for part in ("upper", "lower", "body"):
            if part in o:
                item[part] = [c for c in o[part] if c in COLOURS][:2]
        clean.append(item)
    with connect() as conn:
        conn.execute("INSERT INTO event_attributes (event_id, objects, ok) VALUES (%s, %s, %s) ON CONFLICT (event_id) DO UPDATE "
                     "SET objects = EXCLUDED.objects, ok = EXCLUDED.ok, analysed_at = now()", (event_id, Jsonb(clean), body.ok))
    return {"ok": True, "objects": len(clean)}


# ------------------------------------------------------------------ searching

def _list(v: str) -> list[str]:
    return [c for c in (v or "").lower().split(",") if c in COLOURS]


@router.get("")
def search(request: Request, what: str = "person", upper: str = "", lower: str = "", body: str = "", camera: str = "", zone: str = "",
           since: datetime | None = None, until: datetime | None = None, limit: int = 120,
           user: dict = Depends(require(*SEARCHERS))) -> dict:
    from .access import sql as cam_sql
    if what not in ("person", "vehicle", "any"):
        raise HTTPException(status_code=422, detail="what is person, vehicle or any")
    until = until or datetime.now(timezone.utc)
    since = since or until - timedelta(days=1)
    if since.tzinfo is None or until.tzinfo is None:
        raise HTTPException(status_code=422, detail="times need a time zone")
    if until - since > timedelta(days=31):
        raise HTTPException(status_code=422, detail="search at most 31 days at a time")
    up, lo, bo = _list(upper), _list(lower), _list(body)
    sql = ("SELECT e.id, e.camera_id, e.type, e.zone, e.occurred_at, x.objects, a.id FROM events e JOIN event_attributes x ON x.event_id = e.id "
           "LEFT JOIN alerts a ON a.event_id = e.id WHERE e.occurred_at >= %s AND e.occurred_at < %s AND x.ok")
    args: list = [since, until]
    if camera:
        sql += " AND e.camera_id = %s"
        args.append(camera)
    if zone:
        sql += " AND e.zone = %s"
        args.append(zone)
    w, a = cam_sql(user, "e.camera_id")
    sql += w + " ORDER BY e.occurred_at DESC LIMIT 5000"
    args += a
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
        cov = conn.execute("SELECT count(*), count(x.event_id) FROM events e LEFT JOIN event_attributes x ON x.event_id = e.id "
                           "WHERE e.snapshot_ref IS NOT NULL AND NOT (e.type = ANY(%s)) AND e.occurred_at >= %s AND e.occurred_at < %s" + w,
                           [list(SKIP_TYPES), since, until] + a).fetchone()
    from .alerts import camera_label
    hits, seen = [], {}
    for eid, cam, typ, z, at, objects, aid in rows:
        for i, o in enumerate(objects or []):
            if not matches(o, what, up, lo, bo):
                continue
            key = slot(cam, o)
            if key in seen:                             # the same spot again: a parked vehicle or a fixed object
                seen[key]["seen"] += 1
                continue
            hit = {"event_id": str(eid), "object": i, "camera_id": cam, "camera": camera_label(cam) or cam, "type": typ, "zone": z,
                   "at": at, "class": o["class"], "upper": o.get("upper", []), "lower": o.get("lower", []), "body": o.get("body", []),
                   "crop_url": f"/api/search/crop/{eid}/{i}", "alert_id": str(aid) if aid else None, "seen": 1}
            seen[key] = hit
            hits.append(hit)
            break                                       # one tile per event picture
        if len(hits) >= max(1, min(limit, 500)):
            break
    for hit in hits:
        hit["fixed"] = hit["seen"] >= 5                 # in five or more pictures at the same spot
    audit("smart_search", user_id=user["id"], username=user["username"], ip=client_ip(request), what=what, upper=up, lower=lo, body=bo,
          camera=camera or "all", since=since.isoformat(timespec="minutes"), until=until.isoformat(timespec="minutes"), results=len(hits))
    return {"results": hits, "since": since, "until": until, "pictures": cov[0], "analysed": cov[1]}


@router.get("/crop/{event_id}/{index}")
def crop(event_id: uuid.UUID, index: int, user: dict = Depends(require(*SEARCHERS))) -> Response:
    """The found person or vehicle cut out of the event picture, with some room around it."""
    from .access import allowed
    p, meta = _snapshot(event_id)
    if not allowed(user, meta["camera_id"]):
        raise HTTPException(status_code=404, detail="no picture")
    with connect() as conn:
        r = conn.execute("SELECT objects FROM event_attributes WHERE event_id = %s", (event_id,)).fetchone()
    objs = (r[0] if r else None) or []
    if not 0 <= index < len(objs):
        raise HTTPException(status_code=404, detail="no such object")
    from PIL import Image
    with Image.open(p) as im:
        x1, y1, x2, y2 = objs[index]["box"]
        w, h = x2 - x1, y2 - y1
        box = (max(0, x1 - w * 0.25), max(0, y1 - h * 0.12), min(im.width, x2 + w * 0.25), min(im.height, y2 + h * 0.12))
        out = im.crop(tuple(int(v) for v in box)).convert("RGB")
        out.thumbnail((360, 360))
        buf = io.BytesIO()
        out.save(buf, "JPEG", quality=85)
    return Response(buf.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/status")
def status(_: dict = Depends(require(*SEARCHERS))) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT count(*) FILTER (WHERE x.event_id IS NULL), max(x.analysed_at) FROM events e LEFT JOIN event_attributes x "
                         "ON x.event_id = e.id WHERE e.snapshot_ref IS NOT NULL AND NOT (e.type = ANY(%s)) AND e.occurred_at > now() - %s * interval '1 day'",
                         (list(SKIP_TYPES), BACKFILL_DAYS)).fetchone()
    return {"waiting": r[0], "last_analysed": r[1], "service_running": bool(r[1] and datetime.now(timezone.utc) - r[1] < timedelta(minutes=10)) or r[0] == 0}
