"""Operator logbook and shift handover (release 2.0, first batch).

Shifts are set in settings (default Day 06:00 to 18:00, Night 18:00 to 06:00, local time). During a shift,
operators write entries: patrol, incident, visitor, maintenance or other. The log is append-only: the
author can correct an entry within 15 minutes; after that a correction is a new entry.

At the end of a shift the outgoing operator hands over: HSS writes the shift's summary (alerts raised and
still open, device problems, outputs still on, entries) and the operator adds what to watch. The incoming
operator takes over with their own note. Both names and times are kept, and the next shift sees a waiting
handover until someone takes it.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from .auth import audit, client_ip, require
from .db import connect

router = APIRouter(prefix="/logbook", tags=["logbook"])
WRITERS = ("admin", "cso", "operator")
READERS = ("admin", "cso", "operator", "management")
DEFAULT_SHIFTS = [["Day", "06:00", "18:00"], ["Night", "18:00", "06:00"]]
EDIT_MIN = 15
CATEGORIES = ("patrol", "incident", "visitor", "maintenance", "other")


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))


def shift_at(shifts: list[list[str]], at: datetime) -> tuple[str, datetime, datetime]:
    """(label, start, end) of the shift running at `at`, a time-zone-aware local datetime (pure, tested).
    A shift whose end is before its start runs over midnight."""
    t = at.timetz().replace(tzinfo=None)
    for label, s, e in shifts:
        ts, te = time.fromisoformat(s), time.fromisoformat(e)
        overnight = te <= ts
        inside = (ts <= t < te) if not overnight else (t >= ts or t < te)
        if not inside:
            continue
        day = at.date()
        if overnight and t < te:
            day -= timedelta(days=1)                # the night shift that began yesterday evening
        start = datetime.combine(day, ts, at.tzinfo)
        end = datetime.combine(day + timedelta(days=1) if overnight else day, te, at.tzinfo)
        return label, start, end
    # Not covered by any shift: treat the gap as its own period, from the last end to the next start.
    return "Outside shifts", at.replace(minute=0, second=0, microsecond=0), at.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)


def load_shifts() -> list[list[str]]:
    with connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = 'shifts'").fetchone()
    return r[0] if r else DEFAULT_SHIFTS


def current_shift(at: datetime | None = None) -> dict:
    at = (at or datetime.now(timezone.utc)).astimezone(tz())
    label, start, end = shift_at(load_shifts(), at)
    return {"label": label, "start": start, "end": end}


# ------------------------------------------------------------------ summary for a handover

def summarise(start: datetime, end: datetime) -> dict:
    with connect() as conn:
        raised = dict(conn.execute("SELECT severity, count(*) FROM alerts WHERE created_at >= %s AND created_at < %s GROUP BY 1",
                                   (start, end)).fetchall())
        closed = dict(conn.execute("SELECT coalesce(close_reason, 'other'), count(*) FROM alerts WHERE closed_at >= %s AND closed_at < %s "
                                   "GROUP BY 1", (start, end)).fetchall())
        open_rows = conn.execute(
            "SELECT a.id, a.severity, a.status, e.camera_id, e.type, e.zone, a.created_at, a.assigned_to FROM alerts a "
            "JOIN events e ON e.id = a.event_id WHERE a.status <> 'closed' ORDER BY (a.severity = 'critical') DESC, a.created_at DESC LIMIT 15"
        ).fetchall()
        open_count = conn.execute("SELECT count(*) FROM alerts WHERE status <> 'closed'").fetchone()[0]
        devices = conn.execute("SELECT type, camera_id, zone, occurred_at FROM events WHERE occurred_at >= %s AND occurred_at < %s "
                               "AND type IN ('nvr_offline', 'camera_offline', 'drive_fault', 'unit_offline') ORDER BY occurred_at",
                               (start, end)).fetchall()
        entries = dict(conn.execute("SELECT category, count(*) FROM logbook_entries WHERE at >= %s AND at < %s GROUP BY 1",
                                    (start, end)).fetchall())
        events = conn.execute("SELECT count(*) FROM events WHERE occurred_at >= %s AND occurred_at < %s", (start, end)).fetchone()[0]
    try:
        from .outputs import active
        outputs_on = [v["name"] for v in active.snapshot().values()]
    except Exception:
        outputs_on = []
    try:
        from .alerts import camera_label
    except Exception:
        camera_label = lambda c: None  # noqa: E731
    return {
        "events": events, "alerts_raised": raised, "alerts_closed": closed, "open_alerts": open_count,
        "open_list": [{"id": str(i), "severity": s, "status": st, "camera": camera_label(c) or c, "type": t, "zone": z,
                       "since": at.isoformat(), "assigned_to": who} for i, s, st, c, t, z, at, who in open_rows],
        "device_problems": [{"type": t, "camera": camera_label(c) or c, "detail": z, "at": at.isoformat()} for t, c, z, at in devices],
        "outputs_on": outputs_on, "entries": entries,
    }


# ------------------------------------------------------------------ endpoints

@router.get("/shift")
def get_shift(_: dict = Depends(require(*READERS)), at: datetime | None = None) -> dict:
    """The shift running now, or at `at` (to step through earlier shifts)."""
    sh = current_shift(at)
    return {**sh, "shifts": load_shifts(), "is_current": sh["start"] <= datetime.now(timezone.utc) < sh["end"]}


class ShiftsIn(BaseModel):
    shifts: list[list[str]] = Field(min_length=1, max_length=6)

    @field_validator("shifts")
    @classmethod
    def _shifts(cls, v):
        for s in v:
            if len(s) != 3 or not s[0].strip() or not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) for t in s[1:]):
                raise ValueError('each shift is ["Name", "HH:MM", "HH:MM"]')
        return [[s[0].strip()[:30], s[1], s[2]] for s in v]


@router.put("/shifts")
def put_shifts(body: ShiftsIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('shifts', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (Jsonb(body.shifts),))
    audit("shifts_changed", user_id=user["id"], username=user["username"], ip=client_ip(request),
          shifts="; ".join(f"{n} {a}-{b}" for n, a, b in body.shifts))
    return get_shift(user, None)


@router.get("")
def entries(start: datetime | None = None, end: datetime | None = None, _: dict = Depends(require(*READERS))) -> dict:
    if start is None or end is None:
        sh = current_shift()
        start, end = sh["start"], sh["end"]
    with connect() as conn:
        rows = conn.execute("SELECT l.id, l.at, l.username, coalesce(u.display_name, l.username), l.category, l.text, l.alert_id, l.camera_id, l.edited_at "
                            "FROM logbook_entries l LEFT JOIN users u ON u.username = l.username WHERE l.at >= %s AND l.at < %s "
                            "ORDER BY l.at DESC LIMIT 1000", (start, end)).fetchall()
        hos = conn.execute("SELECT id, shift_label, shift_start, shift_end, from_user, from_at, notes, summary, to_user, to_at, to_note "
                           "FROM handovers WHERE from_at >= %s AND from_at < %s + interval '12 hours' ORDER BY from_at DESC",
                           (start, end)).fetchall()
    keys = ["id", "shift_label", "shift_start", "shift_end", "from_user", "from_at", "notes", "summary", "to_user", "to_at", "to_note"]
    return {"start": start, "end": end,
            "entries": [{"id": i, "at": at, "username": u, "name": dn, "category": c, "text": t, "alert_id": str(a) if a else None,
                         "camera_id": cam, "edited_at": ed} for i, at, u, dn, c, t, a, cam, ed in rows],
            "handovers": [dict(zip(keys, r)) for r in hos]}


class EntryIn(BaseModel):
    category: str = Field(pattern="^(" + "|".join(CATEGORIES) + ")$")
    text: str = Field(min_length=1, max_length=2000)
    alert_id: str | None = Field(default=None, pattern=r"^[0-9a-f-]{36}$")
    camera_id: str | None = Field(default=None, max_length=64)


@router.post("", status_code=201)
def add_entry(body: EntryIn, user: dict = Depends(require(*WRITERS))) -> dict:
    with connect() as conn:
        eid, at = conn.execute("INSERT INTO logbook_entries (username, category, text, alert_id, camera_id) VALUES (%s, %s, %s, %s, %s) "
                               "RETURNING id, at", (user["username"], body.category, body.text.strip(), body.alert_id, body.camera_id)).fetchone()
        if body.alert_id:
            from .alerts import add_timeline
            add_timeline(conn, body.alert_id, "comment", f"Logbook: {body.text.strip()[:300]}", user["username"])
    return {"id": eid, "at": at}


def may_edit(entry_user: str, entry_at: datetime, user: str, now: datetime) -> bool:
    """Only the author, and only for 15 minutes (pure, tested)."""
    return entry_user == user and now - entry_at <= timedelta(minutes=EDIT_MIN)


class EditIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


@router.put("/{eid}")
def edit_entry(eid: int, body: EditIn, user: dict = Depends(require(*WRITERS))) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT username, at FROM logbook_entries WHERE id = %s", (eid,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="no such entry")
        if not may_edit(r[0], r[1], user["username"], datetime.now(timezone.utc)):
            raise HTTPException(status_code=403, detail=f"Entries can be corrected by their author for {EDIT_MIN} minutes; add a new entry instead.")
        conn.execute("UPDATE logbook_entries SET text = %s, edited_at = now() WHERE id = %s", (body.text.strip(), eid))
    return {"id": eid}


@router.get("/handover/draft")
def handover_draft(_: dict = Depends(require(*WRITERS))) -> dict:
    sh = current_shift()
    return {"shift": sh, "summary": summarise(sh["start"], min(sh["end"], datetime.now(timezone.utc)))}


class HandoverIn(BaseModel):
    notes: str = Field(default="", max_length=4000)


@router.post("/handover", status_code=201)
def hand_over(body: HandoverIn, request: Request, user: dict = Depends(require(*WRITERS))) -> dict:
    sh = current_shift()
    summary = summarise(sh["start"], min(sh["end"], datetime.now(timezone.utc)))
    with connect() as conn:
        hid = conn.execute("INSERT INTO handovers (shift_label, shift_start, shift_end, from_user, notes, summary) VALUES (%s, %s, %s, %s, %s, %s) "
                           "RETURNING id", (sh["label"], sh["start"], sh["end"], user["username"], body.notes.strip(), Jsonb(summary))).fetchone()[0]
    audit("handover_given", user_id=user["id"], username=user["username"], ip=client_ip(request), shift=sh["label"], handover=hid)
    return {"id": hid}


@router.get("/handover/pending")
def pending(user: dict = Depends(require(*READERS))) -> dict | None:
    with connect() as conn:
        r = conn.execute("SELECT id, shift_label, shift_start, shift_end, from_user, from_at, notes, summary FROM handovers "
                         "WHERE to_user IS NULL AND from_at > now() - interval '24 hours' ORDER BY from_at DESC LIMIT 1").fetchone()
    if not r:
        return None
    keys = ["id", "shift_label", "shift_start", "shift_end", "from_user", "from_at", "notes", "summary"]
    return {**dict(zip(keys, r)), "mine": r[4] == user["username"]}


class TakeIn(BaseModel):
    note: str = Field(default="", max_length=2000)


@router.post("/handover/{hid}/take")
def take_over(hid: int, body: TakeIn, request: Request, user: dict = Depends(require(*WRITERS))) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT from_user, to_user FROM handovers WHERE id = %s", (hid,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="no such handover")
        if r[1]:
            raise HTTPException(status_code=409, detail=f"{r[1]} has already taken over.")
        if r[0] == user["username"]:
            raise HTTPException(status_code=409, detail="The incoming operator takes over, not the one handing over.")
        conn.execute("UPDATE handovers SET to_user = %s, to_at = now(), to_note = %s WHERE id = %s", (user["username"], body.note.strip(), hid))
    audit("handover_taken", user_id=user["id"], username=user["username"], ip=client_ip(request), handover=hid)
    return {"id": hid, "to_user": user["username"]}
