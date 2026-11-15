"""Wall screens (Phase 2): camera grids for the video wall, NVR screens and rotation screens.

A screen is a grid (1 to 64 tiles) fed by all cameras, one NVR's cameras or a hand-picked list. When it
has more cameras than tiles it shows them a page at a time, changing every `dwell_s` seconds. With
`pin_alerts`, cameras with an open warning or critical alert are put first on every page and outlined
until the alert is closed.

Wall PCs don't sign in: each screen has a random key in its URL (/wall/?s=<id>&k=<key>). The key only
lets a page see which camera paths to play; it can be regenerated from the console.
"""
from __future__ import annotations

import hmac
import math
import re
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from .auth import audit, client_ip, require
from .db import connect

router = APIRouter(tags=["wall screens"])
TILES = (1, 4, 6, 9, 16, 25, 32, 36, 64)
COLS = {1: 1, 4: 2, 6: 3, 9: 3, 16: 4, 25: 5, 32: 8, 36: 6, 64: 8}
COLS_SQL = "id, name, source, cameras, tiles, dwell_s, labels, pin_alerts, key, created_at, updated_at"


def grid_shape(tiles: int) -> tuple[int, int]:
    cols = COLS[tiles]
    return cols, math.ceil(tiles / cols)


def resolve_cameras(source: str, cameras: list[str], available: list[str]) -> list[str]:
    """The cameras a screen shows, in order (pure function, tested)."""
    if source == "all":
        return list(available)
    if source.startswith("nvr:"):
        prefix = source[4:] + "-ch"
        return [p for p in available if p.startswith(prefix)]
    return list(dict.fromkeys(cameras))                 # hand-picked, duplicates dropped, order kept


def build_pages(cameras: list[str], tiles: int, pinned: list[str]) -> list[list[str]]:
    """Split cameras into pages of `tiles`; pinned cameras (open alerts) lead every page (pure function)."""
    pinned = [c for c in dict.fromkeys(pinned) if c in cameras][:tiles]
    rest = [c for c in cameras if c not in pinned]
    room = tiles - len(pinned)
    if not rest or room == 0:
        return [pinned or cameras[:tiles]] if cameras else [[]]
    return [pinned + rest[i:i + room] for i in range(0, len(rest), room)]


_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, ttl: float, fn, stale_s: float = 600):
    """fn's value, kept for ttl seconds. If fn fails (gateway restarting, database busy), the last good
    value is used for up to stale_s seconds, so the wall keeps its cameras through a short outage."""
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < ttl:
        return hit[1]
    try:
        val = fn()
    except Exception:
        if hit and time.monotonic() - hit[0] < stale_s:
            return hit[1]
        raise
    _cache[key] = (time.monotonic(), val)
    return val


def available_paths() -> tuple[list[str], dict[str, str]]:
    from .console import gateway_paths
    items = _cached("paths", 15, gateway_paths)
    return [i["path"] for i in items], {i["path"]: i["label"] for i in items}


def alert_cameras() -> dict[str, str]:
    """Camera id -> worst severity among open (not closed) warning and critical alerts."""
    def q():
        with connect() as conn:
            rows = conn.execute("SELECT e.camera_id, max(CASE a.severity WHEN 'critical' THEN 2 ELSE 1 END) FROM alerts a "
                                "JOIN events e ON e.id = a.event_id WHERE a.status <> 'closed' AND a.severity IN ('warning', 'critical') "
                                "GROUP BY 1").fetchall()
        return {c: ("critical" if s == 2 else "warning") for c, s in rows}
    return _cached("alerts", 5, q)


def _row(r) -> dict:
    return dict(zip([c.strip() for c in COLS_SQL.split(",")], r))


def _get(sid: int) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS_SQL} FROM wall_screens WHERE id = %s", (sid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such screen")
    return _row(r)


def screen_url(s: dict) -> str:
    return f"/wall/?s={s['id']}&k={s['key']}"


class ScreenIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    source: str = Field(default="cameras", max_length=40)
    cameras: list[str] = Field(default_factory=list, max_length=512)
    tiles: int = 16
    dwell_s: int = Field(default=20, ge=5, le=600)
    labels: bool = True
    pin_alerts: bool = True

    @field_validator("source")
    @classmethod
    def _src(cls, v):
        if v not in ("all", "cameras") and not re.fullmatch(r"nvr:[a-z][a-z0-9]{1,19}", v):
            raise ValueError("source is all, cameras or nvr:<short name>")
        return v

    @field_validator("tiles")
    @classmethod
    def _tiles(cls, v):
        if v not in TILES:
            raise ValueError(f"tiles must be one of {', '.join(map(str, TILES))}")
        return v

    @field_validator("cameras")
    @classmethod
    def _cams(cls, v):
        for c in v:
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", c):
                raise ValueError(f"not a camera path: {c[:40]}")
        return v


def _summary(s: dict, available: list[str]) -> dict:
    cams = resolve_cameras(s["source"], s["cameras"], available)
    return {k: s[k] for k in ("id", "name", "source", "cameras", "tiles", "dwell_s", "labels", "pin_alerts", "updated_at")} | {
        "camera_count": len(cams), "pages": max(1, math.ceil(len(cams) / s["tiles"])), "url": screen_url(s)}


@router.get("/wall/screens")
def list_screens(_: dict = Depends(require("admin", "cso"))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(f"SELECT {COLS_SQL} FROM wall_screens ORDER BY name").fetchall()
    try:
        available = available_paths()[0]
    except Exception:
        available = []
    return [_summary(_row(r), available) for r in rows]


@router.post("/wall/screens", status_code=201)
def create_screen(body: ScreenIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM wall_screens WHERE name = %s", (body.name,)).fetchone():
            raise HTTPException(status_code=409, detail=f"A screen called {body.name} exists already.")
        sid = conn.execute("INSERT INTO wall_screens (name, source, cameras, tiles, dwell_s, labels, pin_alerts, key) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                           (body.name, body.source, Jsonb(body.cameras), body.tiles, body.dwell_s, body.labels, body.pin_alerts,
                            secrets.token_urlsafe(18))).fetchone()[0]
    audit("screen_created", user_id=user["id"], username=user["username"], ip=client_ip(request), screen=body.name)
    return _summary(_get(sid), [])


@router.put("/wall/screens/{sid}")
def edit_screen(sid: int, body: ScreenIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    _get(sid)
    with connect() as conn:
        if conn.execute("SELECT 1 FROM wall_screens WHERE name = %s AND id <> %s", (body.name, sid)).fetchone():
            raise HTTPException(status_code=409, detail=f"A screen called {body.name} exists already.")
        conn.execute("UPDATE wall_screens SET name = %s, source = %s, cameras = %s, tiles = %s, dwell_s = %s, labels = %s, "
                     "pin_alerts = %s, updated_at = now() WHERE id = %s",
                     (body.name, body.source, Jsonb(body.cameras), body.tiles, body.dwell_s, body.labels, body.pin_alerts, sid))
    audit("screen_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), screen=body.name)
    return _summary(_get(sid), [])


@router.post("/wall/screens/{sid}/new-key")
def new_key(sid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    """New URL key: the old link stops working. Wall PCs showing this screen are moved to the new link."""
    old = _get(sid)
    key = secrets.token_urlsafe(18)
    with connect() as conn:
        conn.execute("UPDATE wall_screens SET key = %s, updated_at = now() WHERE id = %s", (key, sid))
        conn.execute("UPDATE wall_layouts SET path = %s, updated_at = now() WHERE path = %s", (screen_url({**old, "key": key}), screen_url(old)))
    audit("screen_key_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), screen=old["name"])
    return _summary(_get(sid), [])


@router.delete("/wall/screens/{sid}")
def delete_screen(sid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    s = _get(sid)
    with connect() as conn:
        used = conn.execute("SELECT node_id, monitor FROM wall_layouts WHERE path = %s", (screen_url(s),)).fetchall()
        if used:
            raise HTTPException(status_code=409, detail="Shown on " + ", ".join(f"{n} TV {m + 1}" for n, m in used)
                                + "; assign another screen there first.")
        conn.execute("DELETE FROM wall_screens WHERE id = %s", (sid,))
    audit("screen_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), screen=s["name"])
    return {"deleted": s["name"]}


@router.get("/wall/screens/{sid}/play")
def play(sid: int, k: str) -> dict:
    """For the wall page: what to show now. Needs the screen's key, not a sign-in."""
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS_SQL} FROM wall_screens WHERE id = %s", (sid,)).fetchone()
    if not r or not hmac.compare_digest(k.encode(), _row(r)["key"].encode()):
        raise HTTPException(status_code=404, detail="no such screen, or its link was changed")
    s = _row(r)
    available, labels = available_paths()
    cams = resolve_cameras(s["source"], s["cameras"], available)
    alerts = alert_cameras() if s["pin_alerts"] else {}
    pages = build_pages(cams, s["tiles"], [c for c in cams if c in alerts])
    cols, rows = grid_shape(s["tiles"])
    return {"name": s["name"], "tiles": s["tiles"], "cols": cols, "rows": rows, "dwell_s": s["dwell_s"], "labels": s["labels"],
            "pages": [[{"path": p, "label": labels.get(p, p), "alert": alerts.get(p), "configured": p in available} for p in page]
                      for page in pages],
            "version": s["updated_at"].isoformat(), "refresh_s": 10}
