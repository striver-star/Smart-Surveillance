"""Event set-up check and walk test (Phase 3 gate: real events raise alerts).

For each NVR added in the console, read which camera events notify the surveillance centre (the
"Notify Surveillance Center" linkage Hikvision needs before it sends an event to outside software),
and show, per camera, the events received in the last 7 days. The walk test lists cameras as their
first event arrives after a start time.

Smart motion: plain motion events are dropped (HSS_EDGE_IGNORE), but cameras chosen here also send motion when
the camera says the target was a person or vehicle (Hikvision Motion Detection 2.0 on value-series cameras such
as the DS-2CD1xx3G2-LIU and DS-2CD1047G2H-LIUF, which have no line crossing or intrusion).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

import re

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import vault
from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token
from .isapi import DeviceError, read_event_triggers

router = APIRouter(prefix="/event-setup", tags=["event setup"])
NOT_ACTIVITY = ("nvr_offline", "nvr_online", "camera_offline", "camera_online", "drive_fault", "drive_ok")


def summarise(triggers: list[dict]) -> dict[int, dict]:
    """Per channel: event names sent to HSS and those configured but not sent (pure, tested)."""
    out: dict[int, dict] = defaultdict(lambda: {"sent": [], "not_sent": []})
    for t in triggers:
        if t["channel"] is None or t["event"] == "vmd":
            continue
        bucket = out[t["channel"]]["sent" if t["center"] else "not_sent"]
        if t["name"] not in bucket:
            bucket.append(t["name"])
    return dict(out)


@router.post("/{nid}/check")
def check(nid: int, _: dict = Depends(require("admin", "cso"))) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT address, username, secret, scheme FROM nvrs WHERE id = %s", (nid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such NVR")
    try:
        triggers = read_event_triggers(r[0], r[1], vault.decrypt(r[2]), scheme=r[3])
    except DeviceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    checked = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute("UPDATE nvrs SET info = info || %s WHERE id = %s",
                     (Jsonb({"event_triggers": triggers, "event_checked_at": checked}), nid))
    return {"checked_at": checked, "triggers": len(triggers)}


@router.get("")
def overview(_: dict = Depends(require("admin", "cso"))) -> dict:
    from .console import load_devices
    dev = load_devices()
    with connect() as conn:
        rows = conn.execute("SELECT camera_id, type, count(*), max(occurred_at) FROM events WHERE occurred_at > now() - interval '7 days' "
                            "AND NOT (type = ANY(%s)) GROUP BY 1, 2", (list(NOT_ACTIVITY),)).fetchall()
        reg = {a: (i, info) for i, a, info in conn.execute("SELECT id, alias, info FROM nvrs").fetchall()}
    recent: dict[str, dict] = defaultdict(lambda: {"count": 0, "last": None, "types": {}})
    for cam, typ, n, last in rows:
        r = recent[cam]
        r["count"] += n
        r["types"][typ] = n
        r["last"] = max(r["last"], last) if r["last"] else last
    out = []
    for n in dev["nvrs"]:
        nid, info = reg.get(n["alias"], (None, {}))
        per_ch = summarise(info.get("event_triggers", [])) if info else {}
        device_events = [t for t in (info or {}).get("event_triggers", []) if t["channel"] is None]
        out.append({
            "nvr": n["name"], "alias": n["alias"], "address": n["address"], "registered_id": nid,
            "checked_at": (info or {}).get("event_checked_at"),
            "device_events": [{"name": t["name"], "center": t["center"]} for t in device_events],
            "cameras": [{"camera_id": c["camera_id"], "channel": c["channel"], "name": c["name"], "online": c["online"],
                         "tier": c["tier"], **per_ch.get(int(c["channel"]), {"sent": [], "not_sent": []}),
                         "events_7d": recent[c["camera_id"]]["count"] if c["camera_id"] in recent else 0,
                         "last_event": recent[c["camera_id"]]["last"] if c["camera_id"] in recent else None,
                         "types_7d": recent[c["camera_id"]]["types"] if c["camera_id"] in recent else {}}
                        for c in n["channels"]],
        })
    return {"nvrs": out}


@router.get("/walk")
def walk(since: datetime, _: dict = Depends(require("admin", "cso", "operator"))) -> list[dict]:
    from .access import need_all_cameras
    need_all_cameras(_)
    """Cameras that sent an event since `since`, with the first one and whether it raised an alert."""
    if since.tzinfo is None:
        raise HTTPException(status_code=422, detail="since needs a timezone")
    with connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT ON (e.camera_id) e.camera_id, e.type, e.object_class, e.occurred_at, e.received_at, a.id, a.severity "
            "FROM events e LEFT JOIN alerts a ON a.event_id = e.id WHERE e.received_at >= %s AND NOT (e.type = ANY(%s)) "
            "ORDER BY e.camera_id, e.received_at", (since, list(NOT_ACTIVITY))).fetchall()
        counts = dict(conn.execute("SELECT camera_id, count(*) FROM events WHERE received_at >= %s AND NOT (type = ANY(%s)) GROUP BY 1",
                                   (since, list(NOT_ACTIVITY))).fetchall())
    return [{"camera_id": c, "type": t, "object": o, "occurred_at": oa, "received_at": ra, "alert_id": str(a) if a else None,
             "alert_severity": s, "count": counts.get(c, 1)} for c, t, o, oa, ra, a, s in rows]


# ------------------------------------------------------------------ smart motion (person/vehicle motion)

KEY = "smart_motion_cameras"


def smart_motion() -> list[str]:
    with connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = %s", (KEY,)).fetchone()
    return list(r[0]) if r else []


class SmartMotionIn(BaseModel):
    cameras: list[str] = Field(default_factory=list, max_length=640)


@router.get("/smart-motion")
def get_smart_motion(_: dict = Depends(require("admin", "cso"))) -> dict:
    return {"cameras": smart_motion()}


@router.put("/smart-motion")
def put_smart_motion(body: SmartMotionIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    cams = sorted({c.strip() for c in body.cameras if c.strip()})
    bad = [c for c in cams if not re.fullmatch(r"[a-z][a-z0-9]{1,19}-ch\d{2,3}", c)]
    if bad:
        raise HTTPException(status_code=422, detail=f"camera ids look like nvr4-ch22: {', '.join(bad[:5])}")
    before = set(smart_motion())
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (KEY, Jsonb(cams)))
    audit("smart_motion_changed", user_id=user["id"], username=user["username"], ip=client_ip(request),
          added=sorted(set(cams) - before), removed=sorted(before - set(cams)))
    return {"cameras": cams, "takes_effect": "within a minute"}


@router.get("/smart-motion/edge", dependencies=[Depends(check_worker_token)])
def smart_motion_for_edge() -> list[str]:
    """The edge service's list. Only the worker token can read this."""
    return smart_motion()
