"""Anomaly detection (release 2.0, third batch): unusual activity, and cameras that go unusually quiet.

Each camera's usual number of events is learned for every hour of the day, separately for weekdays and
weekends, from the last 6 weeks. A camera is judged once it has 14 days of history. Every 10 minutes:

- Unusual activity: the last hour's events at a camera are compared with what is usual for that hour. If that
  many events would almost never happen by chance (a Poisson test; sensitivity sets how rare), and there are at
  least 3, it is flagged: for example several events at 02:00 at a camera that is usually silent at night. A
  busy camera being busy is not flagged.
- Unusually quiet: a camera that usually has 15 or more events in three hours and has had none. It may be
  blocked, turned, or its events switched off.

A finding is stored as an event (unusual_activity or unusually_quiet, warning) and goes through the alert rules
like any other; one per camera and kind every 3 hours. Counted events are the cameras' own detections (line
crossing, intrusion, motion, server AI and so on), not device faults, guard positions or recognition matches.
"""
from __future__ import annotations

import asyncio
import logging
import math
import os
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.anomaly")
router = APIRouter(prefix="/anomalies", tags=["anomalies"])
HISTORY_DAYS, LEARN_DAYS, COOLDOWN_H = 42, 14, 3
SENSITIVITY = {"low": 1e-4, "normal": 1e-3, "high": 1e-2}
KINDS = ("unusual_activity", "unusually_quiet")
NOT_COUNTED = ("nvr_offline", "nvr_online", "camera_offline", "camera_online", "drive_fault", "drive_ok", "unit_offline", "unit_online",
               "low_battery", "missed_patrol", "checkpoint_visit", "sos", "face_match", "plate_match", "zone_enter", "zone_exit") + KINDS


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))


def daytype(d: date) -> str:
    return "weekend" if d.weekday() >= 5 else "weekday"


# ------------------------------------------------------------------ pure statistics (tested)

def poisson_sf(k: int, lam: float) -> float:
    """P(X >= k) for a Poisson count with mean lam."""
    if k <= 0:
        return 1.0
    term = math.exp(-lam)
    cdf = term
    for i in range(1, k):
        term *= lam / i
        cdf += term
    return max(0.0, 1.0 - cdf)


def baseline(counts: dict[tuple[date, int], int], first_day: date, today: date, history_days: int = HISTORY_DAYS) -> dict[tuple[str, int], float]:
    """Mean events per hour slot (daytype, hour) over the whole days from first_day (or the history start) to
    yesterday; days without events count as zero (pure, tested)."""
    start = max(first_day, today - timedelta(days=history_days))
    days = [start + timedelta(days=i) for i in range((today - start).days)]
    n = {"weekday": sum(1 for d in days if daytype(d) == "weekday"), "weekend": sum(1 for d in days if daytype(d) == "weekend")}
    sums: dict[tuple[str, int], int] = {}
    for (d, h), c in counts.items():
        if start <= d < today:
            sums[(daytype(d), h)] = sums.get((daytype(d), h), 0) + c
    return {(t, h): (sums.get((t, h), 0) / n[t] if n[t] else 0.0) for t in ("weekday", "weekend") for h in range(24)}


def unusual(observed: int, expected: float, p_limit: float, min_events: int = 3) -> tuple[bool, float]:
    """Whether observed events are too many for chance, and how likely they were (pure, tested)."""
    p = poisson_sf(observed, max(expected, 0.05))
    return observed >= min_events and p < p_limit, p


def quiet(observed: int, expected: float, min_expected: float = 15.0) -> bool:
    return expected >= min_expected and observed == 0


def explain(kind: str, observed: int, expected: float, hour: int, dt: str, label: str) -> str:
    if kind == "unusually_quiet":
        return (f"No events at {label} in the last 3 hours; usually about {expected:.0f}. The camera may be blocked, turned, "
                f"or its events switched off.")
    usual = "almost none" if expected < 0.5 else f"about {expected:.1f}"
    return f"{observed} events at {label} in the last hour; usually {usual} around {hour:02d}:00 on {dt}s."


# ------------------------------------------------------------------ settings

def settings() -> dict:
    with connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = 'anomaly'").fetchone()
    return {"enabled": True, "sensitivity": "normal", "quiet": True, **((r[0] if r else None) or {})}


class SettingsIn(BaseModel):
    enabled: bool = True
    sensitivity: str = "normal"
    quiet: bool = True


# ------------------------------------------------------------------ learning and checking

_cache: dict = {"at": 0.0, "value": None}
_lock = threading.Lock()


def learn(now: datetime | None = None) -> dict:
    """{camera: {"first": date, "slots": {(daytype, hour): mean}}}; recomputed at most once an hour."""
    with _lock:
        if _cache["value"] is not None and time.monotonic() - _cache["at"] < 3600:
            return _cache["value"]
    zone = tz()
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(zone).date()
    start_today = datetime.combine(today, datetime.min.time(), zone)
    with connect() as conn:
        rows = conn.execute(
            "SELECT camera_id, (occurred_at AT TIME ZONE %s)::date, extract(hour FROM occurred_at AT TIME ZONE %s)::int, count(*) "
            "FROM events WHERE occurred_at >= %s AND occurred_at < %s AND NOT (type = ANY(%s)) AND source_kind <> 'gps' GROUP BY 1, 2, 3",
            (str(zone), str(zone), start_today - timedelta(days=HISTORY_DAYS), start_today, list(NOT_COUNTED))).fetchall()
        firsts = dict(conn.execute("SELECT camera_id, min(occurred_at) FROM events WHERE NOT (type = ANY(%s)) AND source_kind <> 'gps' "
                                   "GROUP BY 1", (list(NOT_COUNTED),)).fetchall())
    per: dict[str, dict] = {}
    for cam, d, h, c in rows:
        per.setdefault(cam, {})[(d, h)] = c
    out = {}
    for cam, first in firsts.items():
        fd = first.astimezone(zone).date()
        out[cam] = {"first": fd, "days": (today - fd).days, "slots": baseline(per.get(cam, {}), fd, today)}
    with _lock:
        _cache.update(at=time.monotonic(), value=out)
    return out


def _recent(conn, cam: str, kind: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM events WHERE camera_id = %s AND type = %s AND occurred_at > now() - %s * interval '1 hour' LIMIT 1",
                             (cam, kind, COOLDOWN_H)).fetchone())


def check_once(now: datetime | None = None) -> list[dict]:
    cfg = settings()
    if not cfg["enabled"]:
        return []
    zone = tz()
    now = now or datetime.now(timezone.utc)
    p_limit = SENSITIVITY.get(cfg["sensitivity"], 1e-3)
    model = learn(now)
    with connect() as conn:
        hour = dict(conn.execute("SELECT camera_id, count(*) FROM events WHERE occurred_at > %s AND occurred_at <= %s AND NOT (type = ANY(%s)) "
                                 "AND source_kind <> 'gps' GROUP BY 1", (now - timedelta(hours=1), now, list(NOT_COUNTED))).fetchall())
        three = dict(conn.execute("SELECT camera_id, count(*) FROM events WHERE occurred_at > %s AND occurred_at <= %s AND NOT (type = ANY(%s)) "
                                  "AND source_kind <> 'gps' GROUP BY 1", (now - timedelta(hours=3), now, list(NOT_COUNTED))).fetchall())
    from .alerts import camera_label
    found = []
    for cam, m in model.items():
        if m["days"] < LEARN_DAYS:
            continue
        mid = (now - timedelta(minutes=30)).astimezone(zone)
        dt = daytype(mid.date())
        expected = m["slots"].get((dt, mid.hour), 0.0)
        observed = hour.get(cam, 0)
        flag, p = unusual(observed, expected, p_limit)
        if flag:
            found.append({"camera_id": cam, "kind": "unusual_activity", "observed": observed, "expected": round(expected, 2), "p": p,
                          "hour": mid.hour, "daytype": dt, "window_min": 60})
        if cfg["quiet"]:
            exp3 = sum(m["slots"].get((daytype(t.date()), t.hour), 0.0)
                       for t in ((now - timedelta(minutes=k)).astimezone(zone) for k in (30, 90, 150)))
            if quiet(three.get(cam, 0), exp3):
                found.append({"camera_id": cam, "kind": "unusually_quiet", "observed": 0, "expected": round(exp3, 1), "p": None,
                              "hour": mid.hour, "daytype": dt, "window_min": 180})
    stored = []
    for f in found:
        with connect() as conn:
            if _recent(conn, f["camera_id"], f["kind"]):
                continue
            sample = conn.execute("SELECT id FROM events WHERE camera_id = %s AND occurred_at > %s AND NOT (type = ANY(%s)) "
                                  "AND snapshot_ref IS NOT NULL ORDER BY occurred_at DESC LIMIT 1",
                                  (f["camera_id"], now - timedelta(hours=1), list(NOT_COUNTED))).fetchone()
            eid = uuid.uuid4()
            text = explain(f["kind"], f["observed"], f["expected"], f["hour"], f["daytype"], camera_label(f["camera_id"]) or f["camera_id"])
            raw = {**f, "text": text, "sample_event_id": str(sample[0]) if sample else None, "history_days": min(model[f["camera_id"]]["days"], HISTORY_DAYS)}
            conn.execute("INSERT INTO events (id, camera_id, source_kind, source_ref, tier, type, severity, occurred_at, raw) "
                         "VALUES (%s, %s, 'platform', 'anomaly', 'P', %s, 'warning', %s, %s)", (eid, f["camera_id"], f["kind"], now, Jsonb(raw)))
        from .alerts import add_timeline, on_event
        try:
            aid = on_event({"id": eid, "camera_id": f["camera_id"], "zone": None, "type": f["kind"], "object_class": None, "severity": "warning",
                            "confidence": None, "occurred_at": now})
            if aid:
                with connect() as conn:
                    add_timeline(conn, aid, "anomaly", text)
        except Exception:
            log.exception("alert rules failed for an anomaly")
        stored.append({**f, "event_id": str(eid), "text": text})
        log.info("%s", text)
    return stored


async def background_loop() -> None:
    await asyncio.sleep(90)
    while True:
        try:
            await asyncio.to_thread(check_once)
        except Exception as exc:
            log.warning("anomaly check: %s", exc)
        await asyncio.sleep(600)


# ------------------------------------------------------------------ endpoints

@router.get("/settings")
def get_settings(_: dict = Depends(require("admin", "cso"))) -> dict:
    return settings()


@router.put("/settings")
def put_settings(body: SettingsIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    if body.sensitivity not in SENSITIVITY:
        raise HTTPException(status_code=422, detail="sensitivity is low, normal or high")
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('anomaly', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (Jsonb(body.model_dump()),))
    audit("anomaly_settings_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), **body.model_dump())
    return settings()


@router.get("")
def overview(user: dict = Depends(require("admin", "cso", "operator", "management", "viewer"))) -> dict:
    """Per camera: learning status, the usual pattern for today's kind of day and today's hours so far; and the
    findings of the last 14 days."""
    from .access import allowed, sql as cam_sql
    from .alerts import camera_label
    zone = tz()
    now = datetime.now(timezone.utc)
    today = now.astimezone(zone).date()
    dt = daytype(today)
    model = learn(now)
    start_today = datetime.combine(today, datetime.min.time(), zone)
    with connect() as conn:
        rows = conn.execute("SELECT camera_id, extract(hour FROM occurred_at AT TIME ZONE %s)::int, count(*) FROM events WHERE occurred_at >= %s "
                            "AND NOT (type = ANY(%s)) AND source_kind <> 'gps' GROUP BY 1, 2", (str(zone), start_today, list(NOT_COUNTED))).fetchall()
        w, a = cam_sql(user, "e.camera_id")
        found = conn.execute("SELECT e.id, e.camera_id, e.type, e.occurred_at, e.raw, al.id, al.status, al.close_reason FROM events e "
                             "LEFT JOIN alerts al ON al.event_id = e.id WHERE e.type = ANY(%s) AND e.occurred_at > now() - interval '14 days'" + w
                             + " ORDER BY e.occurred_at DESC LIMIT 100", [list(KINDS)] + a).fetchall()
    todays: dict[str, list[int]] = {}
    for cam, h, c in rows:
        todays.setdefault(cam, [0] * 24)[h] = c
    cams = []
    for cam, m in sorted(model.items(), key=lambda kv: camera_label(kv[0]) or kv[0]):
        if not allowed(user, cam):
            continue
        usual = [round(m["slots"].get((dt, h), 0.0), 2) for h in range(24)]
        cams.append({"camera_id": cam, "camera": camera_label(cam) or cam, "days": m["days"], "learning": m["days"] < LEARN_DAYS,
                     "usual": usual, "today": todays.get(cam, [0] * 24), "usual_total": round(sum(usual), 1)})
    return {"daytype": dt, "now_hour": now.astimezone(zone).hour, "learn_days": LEARN_DAYS, "history_days": HISTORY_DAYS, "settings": settings(),
            "cameras": cams,
            "findings": [{"event_id": str(i), "camera_id": c, "camera": camera_label(c) or c, "kind": k, "at": at, "text": (r or {}).get("text"),
                          "observed": (r or {}).get("observed"), "expected": (r or {}).get("expected"), "sample_event_id": (r or {}).get("sample_event_id"),
                          "alert_id": str(aid) if aid else None, "alert_status": st, "close_reason": cr} for i, c, k, at, r, aid, st, cr in found]}
