"""Who may watch a stream, and the viewing log (release 2.0, first batch).

Every request for video goes through the proxy to the stream gateway at /stream/<path>/whep. The proxy
first asks GET /live/authorize here (Caddy forward_auth), with the browser's cookies and headers:

- A signed-in admin, CSO or operator may watch live cameras; a playback stream (pb-...) only by the
  person who started it. Guards and management can't watch video.
- A wall screen (header X-HSS-Wall: "<screen>:<key>", sent by the wall page) may watch only the cameras
  of that screen. Wall viewing isn't logged per person: the wall is a shared display.
- Anything else, including the gateway's own test pages, is refused.

Each time a person opens a live camera it is written to the viewing log. Reconnects of the same camera
by the same person within 10 minutes extend that entry instead of adding one. Playback is logged when it
starts (playback.py). The CSO and administrators can search and export the log (Viewing log page).
"""
from __future__ import annotations

import csv
import hmac
import io
import logging
import re
import threading
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from .auth import audit, client_ip, require, session_user
from .db import connect

log = logging.getLogger("hss.viewing")
router = APIRouter(tags=["viewing"])
WATCHERS = ("admin", "cso", "operator")
READERS = ("admin", "cso")
MERGE_S = 600
WHEP = re.compile(r"^(?:/stream)?/([A-Za-z0-9_.~-]{1,80})/whep(?:/[A-Za-z0-9_-]{1,80})?/?$")


def stream_path(uri: str, method: str) -> str | None:
    """The gateway path a forwarded request is for, or None if it isn't a WHEP request we serve (pure, tested)."""
    m = WHEP.match((uri or "").split("?", 1)[0])
    if not m or method.upper() not in ("POST", "PATCH", "DELETE"):
        return None
    return m.group(1)


def camera_of(path: str) -> str:
    return path.removesuffix("-sub")


# ------------------------------------------------------------------ wall screens

_wall_cache: dict[str, tuple[float, set[str] | None]] = {}
_wall_lock = threading.Lock()


def wall_paths(header: str) -> set[str] | None:
    """The paths a wall screen may play, from its "<screen>:<key>" header; None if the key is wrong."""
    with _wall_lock:
        hit = _wall_cache.get(header)
        if hit and time.monotonic() - hit[0] < 30:
            return hit[1]
    sid, _, key = header.partition(":")
    allowed = None
    if sid.isdigit() and key:
        from .screens import COLS_SQL, _row, available_paths, resolve_cameras
        with connect() as conn:
            r = conn.execute(f"SELECT {COLS_SQL} FROM wall_screens WHERE id = %s", (int(sid),)).fetchone()
        if r:
            s = _row(r)
            if hmac.compare_digest(key.encode(), s["key"].encode()):
                available, _labels = available_paths()
                allowed = set(resolve_cameras(s["source"], s["cameras"], available))
    with _wall_lock:
        _wall_cache[header] = (time.monotonic(), allowed)
        if len(_wall_cache) > 500:
            _wall_cache.clear()
    return allowed


# ------------------------------------------------------------------ the log

class Merger:
    """Reconnects within MERGE_S extend the open entry instead of adding rows (in memory)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.open: dict[tuple[str, str], tuple[int, float]] = {}

    def entry(self, user: str, camera: str, now: float | None = None) -> int | None:
        now = now if now is not None else time.monotonic()
        with self.lock:
            hit = self.open.get((user, camera))
            if hit and now - hit[1] < MERGE_S:
                self.open[(user, camera)] = (hit[0], now)
                return hit[0]
            return None

    def remember(self, user: str, camera: str, row_id: int, now: float | None = None) -> None:
        with self.lock:
            self.open[(user, camera)] = (row_id, now if now is not None else time.monotonic())
            if len(self.open) > 5000:
                cutoff = time.monotonic() - MERGE_S
                self.open = {k: v for k, v in self.open.items() if v[1] >= cutoff}


merger = Merger()


def log_live(user: dict, camera: str, ip: str) -> None:
    row = merger.entry(user["username"], camera)
    with connect() as conn:
        if row is not None:
            conn.execute("UPDATE view_log SET last_at = now() WHERE id = %s", (row,))
            return
        rid = conn.execute("INSERT INTO view_log (user_id, username, role, camera_id, kind, ip) VALUES (%s, %s, %s, %s, 'live', %s) "
                           "RETURNING id", (user["id"], user["username"], user["role"], camera, ip)).fetchone()[0]
    merger.remember(user["username"], camera, rid)


def log_playback(user: dict, camera: str, recorded_at: datetime, ip: str) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO view_log (user_id, username, role, camera_id, kind, recorded_at, ip) VALUES (%s, %s, %s, %s, 'playback', %s, %s)",
                     (user["id"], user["username"], user["role"], camera, recorded_at, ip))


# ------------------------------------------------------------------ the proxy's question

@router.get("/live/authorize", include_in_schema=False)
def authorize(request: Request) -> Response:
    method = request.headers.get("x-forwarded-method", "")
    path = stream_path(request.headers.get("x-forwarded-uri", ""), method)
    if not path:
        raise HTTPException(status_code=403, detail="not a video request")
    wall = request.headers.get("x-hss-wall")
    if wall:
        allowed = wall_paths(wall)
        if allowed is None:
            raise HTTPException(status_code=401, detail="wall screen key not valid")
        if path not in allowed:
            raise HTTPException(status_code=403, detail="camera not on this wall screen")
        return Response(status_code=204)
    user = session_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="sign in to watch cameras")
    if user["role"] not in WATCHERS or user["must_change_password"]:
        raise HTTPException(status_code=403, detail="your role can't watch cameras")
    if path.startswith("pb-"):
        from .playback import sessions
        with sessions.lock:
            mine = any(v["path"] == path and v["user"] == user["username"] for v in sessions.items.values())
        if not mine:
            raise HTTPException(status_code=403, detail="this recording was opened by someone else")
        return Response(status_code=204)
    if method.upper() == "POST":
        try:
            log_live(user, camera_of(path), client_ip(request))
        except Exception as exc:          # never block video because the log failed, but say so
            log.error("viewing log: %s", exc)
    return Response(status_code=204)


# ------------------------------------------------------------------ searching the log

def _query(camera: str, user: str, kind: str, since: datetime, until: datetime) -> list[dict]:
    where, args = ["started_at >= %s", "started_at < %s"], [since, until]
    if camera:
        where.append("camera_id = %s")
        args.append(camera)
    if user:
        where.append("username ILIKE %s")
        args.append(f"%{user}%")
    if kind in ("live", "playback"):
        where.append("kind = %s")
        args.append(kind)
    with connect() as conn:
        rows = conn.execute("SELECT started_at, last_at, username, role, camera_id, kind, recorded_at, ip FROM view_log "
                            f"WHERE {' AND '.join(where)} ORDER BY started_at DESC LIMIT 5000", args).fetchall()
    from .alerts import camera_label
    return [{"started_at": a, "last_at": b, "username": u, "role": r, "camera_id": c, "camera": camera_label(c) or c, "kind": k,
             "recorded_at": rec, "ip": ip} for a, b, u, r, c, k, rec, ip in rows]


def _range(since: datetime | None, until: datetime | None) -> tuple[datetime, datetime]:
    until = until or datetime.now(timezone.utc)
    since = since or until - timedelta(days=7)
    if since.tzinfo is None or until.tzinfo is None:
        raise HTTPException(status_code=422, detail="times need a time zone")
    if until - since > timedelta(days=366):
        raise HTTPException(status_code=422, detail="search at most a year at a time")
    return since, until


@router.get("/viewing")
def viewing(camera: str = "", user: str = "", kind: str = "", since: datetime | None = None, until: datetime | None = None,
            _: dict = Depends(require(*READERS))) -> dict:
    since, until = _range(since, until)
    rows = _query(camera, user, kind, since, until)
    return {"since": since, "until": until, "rows": rows[:1000], "total": len(rows),
            "people": len({r["username"] for r in rows}), "cameras": len({r["camera_id"] for r in rows})}


@router.get("/viewing.csv")
def viewing_csv(request: Request, camera: str = "", user: str = "", kind: str = "", since: datetime | None = None,
                until: datetime | None = None, who: dict = Depends(require(*READERS))) -> Response:
    since, until = _range(since, until)
    rows = _query(camera, user, kind, since, until)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["started", "last_connected", "user", "role", "camera_id", "camera", "what", "recording_time", "from_ip"])
    for r in rows:
        w.writerow([r["started_at"].isoformat(), r["last_at"].isoformat() if r["kind"] == "live" else "", r["username"], r["role"],
                    r["camera_id"], r["camera"], r["kind"], r["recorded_at"].isoformat() if r["recorded_at"] else "", r["ip"]])
    audit("viewing_log_exported", user_id=who["id"], username=who["username"], ip=client_ip(request), rows=len(rows),
          camera=camera or "all", user_filter=user or "all")
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="hss-viewing-{since:%Y%m%d}-{until:%Y%m%d}.csv"'})
