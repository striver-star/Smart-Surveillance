"""Control-room large-screen mode (release 2.0, second batch).

A wall screen of kind "control" shows a status board instead of a camera grid: open alerts with their
pictures, the site map with cameras, zones and guards, device health, guards on patrol, the shift and the
latest logbook entries, and the lockdown banner. It is opened by the Wall Agent like any other screen
(/wall/?s=<id>&k=<key>, no sign-in) and refreshes every 10 seconds; with the newest critical alert it
plays that camera live.

What a key can see is limited to what this board shows: the pictures of open alerts, the screen's own
site plan, and live video of cameras with an open alert (viewing.py checks the last).
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Response

from .db import connect

log = logging.getLogger("hss.control")
router = APIRouter(tags=["wall screens"])
MAX_ALERTS = 12


def _safe(fn, default):
    """One part failing (NVR list, map) must not blank the whole board."""
    try:
        return fn()
    except Exception as exc:
        log.warning("control board: %s: %s", getattr(fn, "__name__", "part"), exc)
        return default


def order_alerts(rows: list[dict]) -> list[dict]:
    """Unacknowledged before acknowledged, critical before warning, newest first (pure, tested)."""
    rank = {"critical": 0, "warning": 1, "info": 2}
    return sorted(rows, key=lambda a: (a["status"] != "open", rank.get(a["severity"], 3), -a["created_at"].timestamp()))


def _alerts() -> tuple[list[dict], dict]:
    from .alerts import camera_label
    with connect() as conn:
        rows = conn.execute(
            "SELECT a.id, a.severity, a.status, a.created_at, a.acknowledged_by, a.escalation_level, e.type, e.camera_id, e.zone, "
            "e.object_class, e.snapshot_ref IS NOT NULL FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.status <> 'closed' "
            "ORDER BY a.created_at DESC LIMIT 500").fetchall()
    keys = ["id", "severity", "status", "created_at", "acknowledged_by", "escalation_level", "type", "camera_id", "zone", "object_class", "has_snapshot"]
    items = [dict(zip(keys, r)) for r in rows]
    now = datetime.now(timezone.utc)
    unacked = [a for a in items if a["status"] == "open"]
    counts = {"open": len(items), "critical": sum(a["severity"] == "critical" for a in items),
              "warning": sum(a["severity"] == "warning" for a in items), "unacknowledged": len(unacked),
              "oldest_unacknowledged_s": int((now - min(a["created_at"] for a in unacked)).total_seconds()) if unacked else None,
              "escalated": sum(1 for a in unacked if a["escalation_level"])}
    out = []
    for a in order_alerts(items)[:MAX_ALERTS]:
        a["id"] = str(a["id"])
        a["camera"] = camera_label(a["camera_id"]) or a["camera_id"]
        out.append(a)
    return out, counts


def _devices() -> dict:
    from .console import load_devices
    dev = load_devices()
    return {"nvrs": len(dev["nvrs"]), "nvrs_unreachable": [n["name"] for n in dev["nvrs"] if n.get("reachable") is False],
            "cameras": sum(n["total"] for n in dev["nvrs"]), "online": sum(n["online"] for n in dev["nvrs"]),
            "disk_problems": [n["name"] for n in dev["nvrs"] if n["disk_problem"]],
            "offline_cameras": [c["name"] for n in dev["nvrs"] for c in n["channels"] if c.get("online") is False][:8]}


def _guards() -> dict:
    from .geo import offline_min
    with connect() as conn:
        rows = conn.execute("SELECT u.name, u.kind, s.last_at, s.offline FROM tracked_units u LEFT JOIN unit_state s ON s.unit_id = u.id "
                            "WHERE u.active ORDER BY u.name").fetchall()
        visits = conn.execute("SELECT u.name, z.name, v.at FROM checkpoint_visits v JOIN zones z ON z.id = v.zone_id "
                              "JOIN tracked_units u ON u.id = v.unit_id ORDER BY v.at DESC LIMIT 5").fetchall()
    now = datetime.now(timezone.utc)
    units = [{"name": n, "kind": k, "last_at": at, "offline": bool(off) or not at or now - at > timedelta(minutes=offline_min() * 3)}
             for n, k, at, off in rows if at and now - at < timedelta(hours=12)]
    return {"reporting": sum(not u["offline"] for u in units), "offline": [u["name"] for u in units if u["offline"]],
            "units": units[:10], "check_ins": [{"unit": u, "checkpoint": z, "at": at} for u, z, at in visits]}


def _shift() -> dict:
    from .logbook import current_shift
    sh = current_shift()
    with connect() as conn:
        rows = conn.execute("SELECT l.at, coalesce(u.display_name, l.username), l.category, l.text FROM logbook_entries l "
                            "LEFT JOIN users u ON u.username = l.username ORDER BY l.at DESC LIMIT 4").fetchall()
        walls = conn.execute("SELECT count(*), count(*) FILTER (WHERE last_seen > now() - interval '60 seconds') FROM wall_nodes").fetchone()
    return {"label": sh["label"], "start": sh["start"], "end": sh["end"], "walls": {"total": walls[0], "online": walls[1]},
            "logbook": [{"at": at, "by": by, "category": c, "text": t[:160]} for at, by, c, t in rows]}


def _map(plan_id: int | None) -> dict | None:
    if not plan_id:
        return None
    from .geo import live
    m = live(plan_id, {"role": "admin"})
    for u in m["units"]:
        u.pop("trail", None)
    m["plan"].pop("refs", None)
    return m


def live_camera(alerts: list[dict]) -> str | None:
    """The camera to play live: the newest unacknowledged critical alert's, else the newest critical (pure, tested)."""
    crit = [a for a in alerts if a["severity"] == "critical"]
    pick = next((a for a in crit if a["status"] == "open"), crit[0] if crit else None)
    return pick["camera_id"] if pick else None


def stream_path(camera_id: str, available: list[str]) -> str | None:
    """The gateway path for a camera: the sub-stream if there is one (pure, tested)."""
    for p in (f"{camera_id}-sub", camera_id):
        if p in available:
            return p
    return None


def board(s: dict) -> dict:
    from .lockdown import public, state
    from .screens import available_paths
    alerts, counts = _safe(_alerts, ([], {}))
    cam = live_camera(alerts)
    path = None
    if cam:
        available = _safe(lambda: available_paths()[0], [])
        path = stream_path(cam, available)
    return {"kind": "control", "name": s["name"], "version": s["updated_at"].isoformat(), "refresh_s": 10, "now": datetime.now(timezone.utc),
            "lockdown": _safe(lambda: public(state()), None), "alerts": alerts, "counts": counts,
            "live": {"camera_id": cam, "path": path, "label": next((a["camera"] for a in alerts if a["camera_id"] == cam), cam)} if cam else None,
            "devices": _safe(_devices, None), "guards": _safe(_guards, None), "shift": _safe(_shift, None),
            "map": _safe(lambda: _map(s.get("plan_id")), None), "pages": []}


# ------------------------------------------------------------------ pictures, with the screen's key

def _screen(sid: int, k: str) -> dict:
    from .screens import COLS_SQL, _row
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS_SQL} FROM wall_screens WHERE id = %s", (sid,)).fetchone()
    if not r or not hmac.compare_digest(k.encode(), _row(r)["key"].encode()) or _row(r)["kind"] != "control":
        raise HTTPException(status_code=404, detail="no such control screen")
    return _row(r)


@router.get("/wall/screens/{sid}/alert-image/{alert_id}")
def alert_image(sid: int, alert_id: str, k: str) -> Response:
    _screen(sid, k)
    with connect() as conn:
        r = conn.execute("SELECT e.snapshot_ref FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.id::text = %s AND a.status <> 'closed'",
                         (alert_id,)).fetchone()
    import os
    if not r or not r[0]:
        raise HTTPException(status_code=404, detail="no picture")
    p = Path(os.environ.get("HSS_DATA_DIR", "/data")) / r[0]
    if not p.exists():
        raise HTTPException(status_code=404, detail="no picture")
    return Response(p.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "private, max-age=600"})


@router.get("/wall/screens/{sid}/plan-image")
def plan_image(sid: int, k: str) -> Response:
    s = _screen(sid, k)
    if not s.get("plan_id"):
        raise HTTPException(status_code=404, detail="no plan on this screen")
    from .geo import _data_dir, _plan
    p = _plan(s["plan_id"])
    return Response((_data_dir() / p["file"]).read_bytes(), media_type=p["mime"], headers={"Cache-Control": "private, max-age=3600"})
