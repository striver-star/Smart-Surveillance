"""Live device health (Phase 3 part B).

The edge service checks every NVR once a minute and posts what it found here. The API keeps the
latest state per NVR and turns changes into events, so the alert rules handle them like any other:

  nvr_offline / nvr_online         the NVR stopped or started answering
  camera_offline / camera_online   a channel's camera went offline or came back
  drive_fault / drive_ok           a drive reports a problem, or recovered

Only changes raise events: a camera that stays offline raises one event, not one a minute.
"""
from __future__ import annotations

import os
import re
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .db import connect
from .events import check_worker_token

router = APIRouter(prefix="/devices", tags=["devices"])
OK_DISK = ("ok", "normal", "notexist", "idle", "")


class ChannelIn(BaseModel):
    id: int
    name: str = ""
    ip: str = ""
    online: bool | None = None


class DiskIn(BaseModel):
    name: str = ""
    status: str = ""
    capacity_gb: float | None = None
    free_gb: float | None = None


class HealthIn(BaseModel):
    nvr: str = Field(max_length=100)
    reachable: bool
    name: str = ""
    model: str = ""
    firmware: str = ""
    time_mode: str = ""
    channels: list[ChannelIn] = Field(default_factory=list)
    disks: list[DiskIn] = Field(default_factory=list)
    detail: str = Field(default="", max_length=500)


def alias(nvr: str) -> str:
    m = re.search(r"\.(\d+)$", nvr.split(":")[0])
    return f"nvr{m.group(1)}" if m else re.sub(r"[^A-Za-z0-9]", "", nvr)[:20]


def transitions(prev: dict | None, cur: dict, nvr_alias: str) -> list[dict]:
    """Device events for what changed between two health snapshots (pure function, tested).

    prev is the last stored state (its channels and disks are the last *good* data, kept while the NVR
    was unreachable), or None for the first report ever, which only sets the baseline."""
    out = []

    def ev(camera_id, type_, severity, text):
        out.append({"camera_id": camera_id, "type": type_, "severity": severity, "zone": text})

    name = cur.get("name") or (prev or {}).get("name") or nvr_alias
    if prev is None:
        if not cur["reachable"]:
            ev(nvr_alias, "nvr_offline", "critical", f"{name} not answering")
        return out
    if prev["reachable"] and not cur["reachable"]:
        ev(nvr_alias, "nvr_offline", "critical", f"{name} not answering")
    if not prev["reachable"] and cur["reachable"]:
        ev(nvr_alias, "nvr_online", "info", f"{name} answering again")
    if not cur["reachable"]:
        return out
    before = {c["id"]: c for c in prev.get("channels", [])}
    for c in cur["channels"]:
        b = before.get(c["id"])
        if b is None:
            continue                                   # a newly added channel: baseline only
        cam, label = f"{nvr_alias}-ch{int(c['id']):02d}", c.get("name") or f"channel {c['id']}"
        if b.get("online") is not False and c.get("online") is False:
            ev(cam, "camera_offline", "warning", f"{label} offline")
        elif b.get("online") is False and c.get("online") is True:
            ev(cam, "camera_online", "info", f"{label} back online")
    disks_before = {d["name"]: d for d in prev.get("disks", [])}
    for d in cur["disks"]:
        if d["name"] not in disks_before:
            continue
        bad = (d.get("status") or "").lower() not in OK_DISK
        was_bad = (disks_before[d["name"]].get("status") or "").lower() not in OK_DISK
        if bad and not was_bad:
            ev(nvr_alias, "drive_fault", "critical", f"drive {d['name']} reports '{d['status']}'")
        elif was_bad and not bad:
            ev(nvr_alias, "drive_ok", "info", f"drive {d['name']} is {d['status'] or 'ok'} again")
    return out


@router.post("/health", dependencies=[Depends(check_worker_token)])
def post_health(h: HealthIn) -> dict:
    cur = h.model_dump()
    a = alias(h.nvr)
    with connect() as conn:
        row = conn.execute("SELECT reachable, data FROM device_health WHERE nvr = %s", (h.nvr,)).fetchone()
        prev = {**row[1], "reachable": row[0]} if row else None
        events = transitions(prev, cur, a)
        # While an NVR is unreachable keep its last good channels and disks, so the console still shows them
        # and the comparison after it comes back is against what was true before.
        data = {k: v for k, v in cur.items() if k != "reachable"} if h.reachable else \
            {**{k: v for k, v in (prev or {}).items() if k != "reachable"}, "detail": h.detail}
        conn.execute(
            "INSERT INTO device_health (nvr, alias, reachable, data, checked_at, changed_at) VALUES (%s, %s, %s, %s, now(), now()) "
            "ON CONFLICT (nvr) DO UPDATE SET reachable = EXCLUDED.reachable, data = EXCLUDED.data, checked_at = now()"
            + (", changed_at = now()" if events else ""), (h.nvr, a, h.reachable, Jsonb(data)))
    return {"events": [_store_device_event(e, h.nvr) for e in events]}


def _store_device_event(e: dict, nvr: str) -> dict:
    from .alerts import on_event
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute("INSERT INTO events (id, camera_id, source_kind, source_ref, tier, type, severity, zone, occurred_at, raw) "
                     "VALUES (%s, %s, 'nvr', %s, 'N', %s, %s, %s, %s, %s)",
                     (event_id, e["camera_id"], f"health:{nvr}", e["type"], e["severity"], e["zone"], now, Jsonb({"device": True})))
    recovered = {"camera_online": "camera_offline", "nvr_online": "nvr_offline", "drive_ok": "drive_fault"}.get(e["type"])
    if recovered:
        from .alerts import add_timeline, broker, get_alert
        with connect() as conn:
            rows = conn.execute("SELECT a.id FROM alerts a JOIN events ev ON ev.id = a.event_id WHERE a.status <> 'closed' "
                                "AND ev.type = %s AND ev.camera_id = %s", (recovered, e["camera_id"])).fetchall()
            for (aid,) in rows:
                add_timeline(conn, aid, "recovered", f"{e['zone']} at {now.astimezone():%H:%M:%S}")
        for (aid,) in rows:
            broker.publish({"kind": "updated", "alert": get_alert(aid)})
    alert_id = on_event({"id": event_id, "camera_id": e["camera_id"], "zone": e["zone"], "type": e["type"],
                         "object_class": None, "severity": e["severity"], "confidence": None, "occurred_at": now})
    return {"type": e["type"], "camera_id": e["camera_id"], "event_id": str(event_id), "alert_id": alert_id}


def live_health(max_age_s: int = 300) -> dict[str, dict]:
    """Latest health per NVR address, if fresh enough to trust."""
    with connect() as conn:
        rows = conn.execute("SELECT nvr, alias, reachable, data, checked_at FROM device_health "
                            "WHERE checked_at > now() - %s * interval '1 second'", (max_age_s,)).fetchall()
    return {n: {"alias": a, "reachable": r, **d, "checked_at": c} for n, a, r, d, c in rows}
