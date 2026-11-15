"""Geo features (Phase 5): site plans, camera geotags, zones (geofences), guard and vehicle tracking.

- Site plans are uploaded images (a drawing, or a satellite or drone picture of the site). Two
  reference points with latitude and longitude tie a plan to the earth; after that, zones drawn on it
  are stored as PostGIS polygons and GPS positions are drawn on it.
- Guard phones run the open-source Traccar Client app and report to Traccar (compose profile "geo"),
  which forwards every position here. Positions are tested against the zones in PostGIS.
- Changes become ordinary events, so the alert rules, escalation, WhatsApp and the video wall handle
  them: zone_enter, zone_exit, sos, unit_offline, unit_online, low_battery, checkpoint_visit and
  missed_patrol. An event in a zone that cameras cover carries the first camera's id, so the wall
  pins that camera.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import hmac
import io
import logging
import math
import os
import re
import uuid
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.geo")
router = APIRouter(prefix="/geo", tags=["geo"])
VIEWERS = ("admin", "cso", "operator")
EDITORS = ("admin", "cso")
EARTH_R = 6371008.8
PLAN_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
MAX_PLAN = 8 * 1024 * 1024
UNKNOWN_SEEN: deque = deque(maxlen=20)          # device ids Traccar forwarded that aren't registered here


def offline_min() -> int:
    return int(os.environ.get("HSS_UNIT_OFFLINE_MIN", "10"))


def low_battery_pct() -> int:
    return int(os.environ.get("HSS_UNIT_LOW_BATTERY", "15"))


# ------------------------------------------------------------------ georeference (pure, tested)

class Georef:
    """Plan pixels <-> latitude/longitude from two reference points (a similarity transform: scale,
    rotation and shift, on a local flat projection; accurate to well under a metre across a site)."""

    def __init__(self, refs: list[dict]):
        if len(refs) != 2:
            raise ValueError("two reference points are needed")
        p1, p2 = refs
        if math.hypot(p1["x"] - p2["x"], p1["y"] - p2["y"]) < 20:
            raise ValueError("put the two reference points further apart on the plan")
        self.lat0, self.lon0 = p1["lat"], p1["lon"]
        self.k = math.cos(math.radians((p1["lat"] + p2["lat"]) / 2))
        w2 = self._en(p2["lat"], p2["lon"])
        if abs(w2) < 5:
            raise ValueError("the two reference points must be at least 5 metres apart on the ground")
        z1, z2 = complex(p1["x"], -p1["y"]), complex(p2["x"], -p2["y"])
        self.a = w2 / (z2 - z1)
        self.b = -self.a * z1

    def _en(self, lat: float, lon: float) -> complex:
        return complex(math.radians(lon - self.lon0) * self.k * EARTH_R, math.radians(lat - self.lat0) * EARTH_R)

    def to_latlon(self, x: float, y: float) -> tuple[float, float]:
        w = self.a * complex(x, -y) + self.b
        return self.lat0 + math.degrees(w.imag / EARTH_R), self.lon0 + math.degrees(w.real / (self.k * EARTH_R))

    def to_px(self, lat: float, lon: float) -> tuple[float, float]:
        z = (self._en(lat, lon) - self.b) / self.a
        return z.real, -z.imag

    @property
    def metres_per_px(self) -> float:
        return abs(self.a)


def georef(refs) -> Georef | None:
    try:
        return Georef(refs) if refs and len(refs) == 2 else None
    except (ValueError, KeyError, ZeroDivisionError):
        return None


def polygon_wkt(points: list[list[float]], g: Georef) -> str:
    ring = [g.to_latlon(x, y) for x, y in points]
    ring.append(ring[0])
    return "POLYGON((" + ", ".join(f"{lon:.8f} {lat:.8f}" for lat, lon in ring) + "))"


def zone_changes(before: set[int], now: set[int], zones: dict[int, dict], unit_kind: str, armed: dict[int, bool]) -> list[dict]:
    """Events for a unit moving between zones (pure, tested). zones: id -> {name, kind, applies_to,
    alert_on, severity, cameras}; armed: id -> whether the zone is armed now."""
    out = []
    for zid in sorted((now - before) | (before - now)):
        z = zones.get(zid)
        if not z or z["applies_to"] not in ("all", unit_kind):
            continue
        entered = zid in now
        if z["kind"] == "checkpoint":
            if entered:
                out.append({"zone_id": zid, "type": "checkpoint_visit", "severity": "info"})
            continue
        if not armed.get(zid, True):
            continue
        if z["alert_on"] == "both" or z["alert_on"] == ("enter" if entered else "exit"):
            out.append({"zone_id": zid, "type": "zone_enter" if entered else "zone_exit", "severity": z["severity"]})
    return out


# ------------------------------------------------------------------ helpers

def _data_dir() -> Path:
    d = Path(os.environ.get("HSS_DATA_DIR", "/data")) / "plans"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _tz():
    from .alerts import tz
    return tz()


def _armed(windows) -> bool:
    from .alerts import armed_now
    return armed_now([tuple(w) for w in windows], datetime.now(_tz()))


def _plan(pid: int) -> dict:
    with connect() as conn:
        r = conn.execute("SELECT id, name, file, mime, width, height, refs FROM site_plans WHERE id = %s", (pid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such plan")
    return dict(zip(["id", "name", "file", "mime", "width", "height", "refs"], r))


def _refresh_geometry(conn, pid: int, refs) -> None:
    """Recompute PostGIS geometry of the plan's cameras and zones after its reference points change."""
    g = georef(refs)
    for cam, x, y in conn.execute("SELECT camera_id, x, y FROM camera_geo WHERE plan_id = %s", (pid,)).fetchall():
        if g:
            lat, lon = g.to_latlon(x, y)
            conn.execute("UPDATE camera_geo SET geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography WHERE camera_id = %s", (lon, lat, cam))
        else:
            conn.execute("UPDATE camera_geo SET geom = NULL WHERE camera_id = %s", (cam,))
    for zid, pts in conn.execute("SELECT id, points FROM zones WHERE plan_id = %s", (pid,)).fetchall():
        conn.execute("UPDATE zones SET geom = " + ("ST_GeomFromText(%s, 4326)" if g else "NULL") + " WHERE id = %s",
                     ((polygon_wkt(pts, g), zid) if g else (zid,)))


def store_event(*, camera_id: str, type_: str, severity: str, zone: str | None, object_class: str | None,
                lat: float | None, lon: float | None, raw: dict, at: datetime | None = None) -> dict:
    from .alerts import on_event
    eid = uuid.uuid4()
    at = at or datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute("INSERT INTO events (id, camera_id, source_kind, source_ref, tier, type, object_class, zone, severity, "
                     "occurred_at, geotag, raw) VALUES (%s, %s, 'gps', %s, 'G', %s, %s, %s, %s, %s, "
                     + ("ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography" if lat is not None else "NULL") + ", %s)",
                     (eid, camera_id, raw.get("unit", ""), type_, object_class, zone, severity, at,
                      *((lon, lat) if lat is not None else ()), Jsonb(raw)))
    try:
        alert_id = on_event({"id": eid, "camera_id": camera_id, "zone": zone, "type": type_, "object_class": object_class,
                             "severity": severity, "confidence": None, "occurred_at": at})
    except Exception:
        log.exception("alert rules failed for %s", type_)
        alert_id = None
    return {"event_id": str(eid), "type": type_, "alert_id": alert_id}


# ------------------------------------------------------------------ positions (from Traccar)

def _zone_meta(conn) -> dict[int, dict]:
    rows = conn.execute("SELECT id, name, kind, applies_to, alert_on, severity, armed, cameras FROM zones WHERE enabled").fetchall()
    return {r[0]: dict(zip(["id", "name", "kind", "applies_to", "alert_on", "severity", "armed", "cameras"], r)) for r in rows}


def record_position(unit: dict, lat: float, lon: float, at: datetime, *, accuracy=None, speed_kmh=None, battery=None,
                    alarm: str | None = None, simulated: bool = False) -> list[dict]:
    events = []
    with connect() as conn:
        point = "ST_SetSRID(ST_MakePoint(%s, %s), 4326)"
        conn.execute(f"INSERT INTO unit_positions (unit_id, at, geom, accuracy, speed_kmh, battery, alarm) VALUES (%s, %s, {point}::geography, %s, %s, %s, %s)",
                     (unit["id"], at, lon, lat, accuracy, speed_kmh, battery, alarm))
        inside = {r[0] for r in conn.execute(f"SELECT id FROM zones WHERE enabled AND geom IS NOT NULL AND ST_Covers(geom, {point})", (lon, lat)).fetchall()}
        st = conn.execute("SELECT zones, offline, low_battery FROM unit_state WHERE unit_id = %s", (unit["id"],)).fetchone()
        before, was_offline, was_low = (set(st[0]), st[1], st[2]) if st else (set(), False, False)
        zones = _zone_meta(conn)
        low = battery is not None and battery < low_battery_pct()
        conn.execute("INSERT INTO unit_state (unit_id, last_at, lat, lon, battery, speed_kmh, zones, offline, low_battery) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, false, %s) ON CONFLICT (unit_id) DO UPDATE SET last_at = EXCLUDED.last_at, "
                     "lat = EXCLUDED.lat, lon = EXCLUDED.lon, battery = EXCLUDED.battery, speed_kmh = EXCLUDED.speed_kmh, "
                     "zones = EXCLUDED.zones, offline = false, low_battery = EXCLUDED.low_battery",
                     (unit["id"], at, lat, lon, battery, speed_kmh, sorted(inside), low))
        for zid in inside - before:
            if zones.get(zid, {}).get("kind") == "checkpoint":
                conn.execute("INSERT INTO checkpoint_visits (zone_id, unit_id, at) VALUES (%s, %s, %s)", (zid, unit["id"], at))
    obj = "human" if unit["kind"] == "guard" else "vehicle"
    base = {"unit": unit["name"], "unit_kind": unit["kind"], "lat": lat, "lon": lon, "simulated": simulated}
    armed = {zid: _armed(z["armed"]) for zid, z in zones.items()}
    for ch in zone_changes(before, inside, zones, unit["kind"], armed):
        z = zones[ch["zone_id"]]
        verb = {"zone_enter": "entered", "zone_exit": "left", "checkpoint_visit": "checked in at"}[ch["type"]]
        events.append(store_event(camera_id=(z["cameras"] or [f"unit-{unit['id']}"])[0], type_=ch["type"], severity=ch["severity"],
                                  zone=z["name"], object_class=obj, lat=lat, lon=lon, at=at,
                                  raw={**base, "text": f"{unit['name']} {verb} {z['name']}", "zone_kind": z["kind"]}))
    if alarm and alarm.lower() in ("sos", "panic", "alarm"):
        z = next((zones[i] for i in inside if zones.get(i, {}).get("cameras")), None)
        events.append(store_event(camera_id=z["cameras"][0] if z else f"unit-{unit['id']}", type_="sos", severity="critical",
                                  zone=z["name"] if z else None, object_class=obj, lat=lat, lon=lon, at=at,
                                  raw={**base, "text": f"SOS from {unit['name']}"}))
    if was_offline:
        events.append(store_event(camera_id=f"unit-{unit['id']}", type_="unit_online", severity="info", zone=None, object_class=obj,
                                  lat=lat, lon=lon, raw={**base, "text": f"{unit['name']} reporting again"}))
    if low and not was_low:
        events.append(store_event(camera_id=f"unit-{unit['id']}", type_="low_battery", severity="warning", zone=None, object_class=obj,
                                  lat=lat, lon=lon, raw={**base, "text": f"{unit['name']} phone battery at {battery:.0f}%"}))
    return events


def parse_traccar(body: dict) -> dict | None:
    """Traccar's JSON forward ({"position": ..., "device": ...}) to one position (pure, tested)."""
    pos, dev = body.get("position") or {}, body.get("device") or {}
    uid = str(dev.get("uniqueId") or pos.get("uniqueId") or "").strip()
    if not uid or pos.get("latitude") is None or pos.get("longitude") is None:
        return None
    if pos.get("valid") is False:
        return None
    attrs = pos.get("attributes") or {}
    t = pos.get("fixTime") or pos.get("deviceTime") or pos.get("serverTime")
    try:
        at = datetime.fromisoformat(str(t).replace("Z", "+00:00")) if t else datetime.now(timezone.utc)
    except ValueError:
        at = datetime.now(timezone.utc)
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    speed = pos.get("speed")
    return {"device_id": uid, "lat": float(pos["latitude"]), "lon": float(pos["longitude"]), "at": at,
            "accuracy": pos.get("accuracy"), "speed_kmh": round(float(speed) * 1.852, 1) if speed is not None else None,
            "battery": attrs.get("batteryLevel"), "alarm": attrs.get("alarm")}


@router.post("/traccar")
async def traccar_forward(request: Request, token: str = "") -> dict:
    """Traccar posts each position here (forward.url in gateway/traccar.xml)."""
    expected = os.environ.get("HSS_WORKER_TOKEN", "")
    if not expected or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="invalid token")
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(status_code=422, detail="JSON expected")
    p = parse_traccar(body if isinstance(body, dict) else {})
    if not p:
        return {"ignored": "no valid position"}
    with connect() as conn:
        r = conn.execute("SELECT id, name, kind FROM tracked_units WHERE device_id = %s AND active", (p["device_id"],)).fetchone()
    if not r:
        if p["device_id"] not in UNKNOWN_SEEN:
            UNKNOWN_SEEN.append(p["device_id"])
        return {"ignored": "device not registered in HSS"}
    unit = {"id": r[0], "name": r[1], "kind": r[2]}
    events = await asyncio.to_thread(record_position, unit, p["lat"], p["lon"], p["at"], accuracy=p["accuracy"],
                                     speed_kmh=p["speed_kmh"], battery=p["battery"], alarm=p["alarm"])
    return {"unit": unit["name"], "events": events}


# ------------------------------------------------------------------ background: offline units, missed patrols

_missed_alerted: dict[int, datetime] = {}


def check_once(now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    out = []
    with connect() as conn:
        stale = conn.execute("SELECT u.id, u.name, u.kind, s.last_at, s.lat, s.lon FROM tracked_units u JOIN unit_state s ON s.unit_id = u.id "
                             "WHERE u.active AND NOT s.offline AND s.last_at < %s", (now - timedelta(minutes=offline_min()),)).fetchall()
        for uid, *_ in stale:
            conn.execute("UPDATE unit_state SET offline = true WHERE unit_id = %s", (uid,))
        checkpoints = conn.execute("SELECT z.id, z.name, z.visit_every_min, z.armed, z.cameras, "
                                   "(SELECT max(at) FROM checkpoint_visits v WHERE v.zone_id = z.id), z.created_at "
                                   "FROM zones z WHERE z.enabled AND z.kind = 'checkpoint' AND z.visit_every_min IS NOT NULL").fetchall()
    for uid, name, kind, last, lat, lon in stale:
        out.append(store_event(camera_id=f"unit-{uid}", type_="unit_offline", severity="warning", zone=None,
                               object_class="human" if kind == "guard" else "vehicle", lat=lat, lon=lon,
                               raw={"unit": name, "text": f"{name} has not reported since {last.astimezone(_tz()):%H:%M}"}))
    for zid, name, every, armed, cams, last, created in checkpoints:
        if not _armed(armed):
            _missed_alerted.pop(zid, None)
            continue
        due = missed_due(last, created, every, _armed_since(armed, now))
        if now >= due and _missed_alerted.get(zid, datetime.min.replace(tzinfo=timezone.utc)) < due:
            _missed_alerted[zid] = now
            out.append(store_event(camera_id=(cams or [f"checkpoint-{zid}"])[0], type_="missed_patrol", severity="warning", zone=name,
                                   object_class=None, lat=None, lon=None,
                                   raw={"text": f"No guard at {name} for {every} min" + (f" (last {last.astimezone(_tz()):%H:%M})" if last else "")}))
    return out


def missed_due(last_visit: datetime | None, created: datetime, every_min: int, armed_since: datetime | None) -> datetime:
    """When a checkpoint becomes overdue (pure, tested): `every_min` after the last visit, counting from
    whichever is latest of the last visit, the checkpoint's creation and the start of its armed window."""
    start = max(t for t in (last_visit, created, armed_since) if t is not None)
    return start + timedelta(minutes=every_min)


def _armed_since(windows, now: datetime) -> datetime | None:
    """Start of the armed window we're in (None for always armed)."""
    if not windows:
        return None
    from datetime import time as dtime
    local = now.astimezone(_tz())
    for start, end in windows:
        s = dtime.fromisoformat(start)
        begin = local.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
        if begin > local:
            begin -= timedelta(days=1)
        if _armed([[start, end]]) and local - begin < timedelta(days=1):
            return begin.astimezone(timezone.utc)
    return None


async def background_loop() -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await asyncio.to_thread(check_once)
        except Exception as exc:
            log.warning("geo check: %s", exc)
        await asyncio.sleep(60)


# ------------------------------------------------------------------ plans

class PlanIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    image_data_url: str = Field(max_length=12_000_000)


@router.get("/plans")
def list_plans(_: dict = Depends(require(*VIEWERS))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, width, height, refs FROM site_plans ORDER BY sort, id").fetchall()
    out = []
    for pid, name, w, h, refs in rows:
        g = georef(refs)
        out.append({"id": pid, "name": name, "width": w, "height": h, "refs": refs, "georeferenced": bool(g),
                    "metres_per_px": round(g.metres_per_px, 4) if g else None})
    return out


@router.post("/plans", status_code=201)
def add_plan(body: PlanIn, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", body.image_data_url, re.S)
    if not m or m.group(1) not in PLAN_TYPES:
        raise HTTPException(status_code=422, detail="The plan must be a PNG, JPEG or WebP image (export a PDF plan as an image first).")
    try:
        data = base64.b64decode(m.group(2), validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=422, detail="The image isn't valid base64.") from exc
    if len(data) > MAX_PLAN:
        raise HTTPException(status_code=422, detail="The plan must be 8 MB or smaller.")
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception as exc:
        raise HTTPException(status_code=422, detail="That file isn't a readable image.") from exc
    name = f"{uuid.uuid4().hex}.{PLAN_TYPES[m.group(1)]}"
    (_data_dir() / name).write_bytes(data)
    with connect() as conn:
        if conn.execute("SELECT 1 FROM site_plans WHERE name = %s", (body.name,)).fetchone():
            raise HTTPException(status_code=409, detail=f"A plan called {body.name} exists already.")
        pid = conn.execute("INSERT INTO site_plans (name, file, mime, width, height, sort) VALUES (%s, %s, %s, %s, %s, "
                           "(SELECT coalesce(max(sort), 0) + 1 FROM site_plans)) RETURNING id", (body.name, name, m.group(1), w, h)).fetchone()[0]
    audit("plan_added", user_id=user["id"], username=user["username"], ip=client_ip(request), plan=body.name)
    return {"id": pid, "name": body.name, "width": w, "height": h}


@router.get("/plans/{pid}/image")
def plan_image(pid: int, _: dict = Depends(require(*VIEWERS))) -> Response:
    p = _plan(pid)
    return Response((_data_dir() / p["file"]).read_bytes(), media_type=p["mime"],
                    headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


class RefPoint(BaseModel):
    x: float
    y: float
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class PlanEdit(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    refs: list[RefPoint] = Field(default_factory=list, max_length=2)


@router.put("/plans/{pid}")
def edit_plan(pid: int, body: PlanEdit, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    _plan(pid)
    refs = [r.model_dump() for r in body.refs]
    if len(refs) == 1:
        raise HTTPException(status_code=422, detail="Set both reference points, or none.")
    if refs:
        try:
            Georef(refs)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc).capitalize() + ".") from exc
    with connect() as conn:
        conn.execute("UPDATE site_plans SET name = %s, refs = %s WHERE id = %s", (body.name, Jsonb(refs), pid))
        _refresh_geometry(conn, pid, refs)
    audit("plan_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), plan=body.name,
          georeferenced=bool(refs))
    return next(p for p in list_plans(user) if p["id"] == pid)


@router.delete("/plans/{pid}")
def delete_plan(pid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    p = _plan(pid)
    with connect() as conn:
        conn.execute("DELETE FROM site_plans WHERE id = %s", (pid,))
    (_data_dir() / p["file"]).unlink(missing_ok=True)
    audit("plan_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), plan=p["name"])
    return {"deleted": p["name"]}


# ------------------------------------------------------------------ camera geotags

class CameraGeoIn(BaseModel):
    plan_id: int
    x: float
    y: float
    bearing: float = Field(default=0, ge=0, lt=360)
    fov: float = Field(default=90, ge=5, le=360)
    reach: float = Field(default=120, ge=10, le=5000)


@router.put("/cameras/{camera_id}")
def place_camera(camera_id: str, body: CameraGeoIn, _: dict = Depends(require(*EDITORS))) -> dict:
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", camera_id):
        raise HTTPException(status_code=422, detail="not a camera id")
    p = _plan(body.plan_id)
    with connect() as conn:
        conn.execute("INSERT INTO camera_geo (camera_id, plan_id, x, y, bearing, fov, reach) VALUES (%s, %s, %s, %s, %s, %s, %s) "
                     "ON CONFLICT (camera_id) DO UPDATE SET plan_id = EXCLUDED.plan_id, x = EXCLUDED.x, y = EXCLUDED.y, "
                     "bearing = EXCLUDED.bearing, fov = EXCLUDED.fov, reach = EXCLUDED.reach",
                     (camera_id, body.plan_id, body.x, body.y, body.bearing, body.fov, body.reach))
        _refresh_geometry(conn, body.plan_id, p["refs"])
    return {"camera_id": camera_id, **body.model_dump()}


@router.delete("/cameras/{camera_id}")
def unplace_camera(camera_id: str, _: dict = Depends(require(*EDITORS))) -> dict:
    with connect() as conn:
        conn.execute("DELETE FROM camera_geo WHERE camera_id = %s", (camera_id,))
    return {"removed": camera_id}


# ------------------------------------------------------------------ zones

class ZoneIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(pattern=r"^(restricted|perimeter|checkpoint|area)$")
    plan_id: int
    points: list[list[float]] = Field(min_length=3, max_length=200)
    applies_to: str = Field(default="all", pattern=r"^(all|guard|vehicle)$")
    alert_on: str = Field(default="enter", pattern=r"^(enter|exit|both|none)$")
    severity: str = Field(default="warning", pattern=r"^(info|warning|critical)$")
    armed: list[list[str]] = Field(default_factory=list, max_length=6)
    cameras: list[str] = Field(default_factory=list, max_length=32)
    visit_every_min: int | None = Field(default=None, ge=5, le=1440)
    enabled: bool = True

    @field_validator("points")
    @classmethod
    def _pts(cls, v):
        if any(len(p) != 2 for p in v):
            raise ValueError("each point is [x, y]")
        return v

    @field_validator("armed")
    @classmethod
    def _armed(cls, v):
        for w in v:
            if len(w) != 2 or not all(re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t) for t in w):
                raise ValueError("armed windows look like [\"18:00\", \"06:00\"]")
        return v


ZONE_COLS = "id, name, kind, plan_id, points, applies_to, alert_on, severity, armed, cameras, visit_every_min, enabled, geom IS NOT NULL"


def _zone_row(r) -> dict:
    d = dict(zip(["id", "name", "kind", "plan_id", "points", "applies_to", "alert_on", "severity", "armed", "cameras",
                  "visit_every_min", "enabled", "has_geo"], r))
    d["armed_now"] = _armed(d["armed"])
    return d


@router.get("/zones")
def list_zones(plan_id: int | None = None, _: dict = Depends(require(*VIEWERS))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(f"SELECT {ZONE_COLS} FROM zones" + (" WHERE plan_id = %s" if plan_id else "") + " ORDER BY name",
                            (plan_id,) if plan_id else ()).fetchall()
    return [_zone_row(r) for r in rows]


def _save_zone(conn, zid: int | None, z: ZoneIn) -> int:
    p = _plan(z.plan_id)
    g = georef(p["refs"])
    vals = (z.name, z.kind, z.plan_id, Jsonb(z.points), z.applies_to, z.alert_on, z.severity, Jsonb(z.armed), Jsonb(z.cameras),
            z.visit_every_min if z.kind == "checkpoint" else None, z.enabled)
    geom = "ST_GeomFromText(%s, 4326)" if g else "NULL"
    gparam = (polygon_wkt(z.points, g),) if g else ()
    if zid is None:
        return conn.execute("INSERT INTO zones (name, kind, plan_id, points, applies_to, alert_on, severity, armed, cameras, visit_every_min, "
                            f"enabled, geom) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, {geom}) RETURNING id", vals + gparam).fetchone()[0]
    conn.execute("UPDATE zones SET name = %s, kind = %s, plan_id = %s, points = %s, applies_to = %s, alert_on = %s, severity = %s, "
                 f"armed = %s, cameras = %s, visit_every_min = %s, enabled = %s, geom = {geom} WHERE id = %s", vals + gparam + (zid,))
    return zid


@router.post("/zones", status_code=201)
def add_zone(body: ZoneIn, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    with connect() as conn:
        zid = _save_zone(conn, None, body)
        r = conn.execute(f"SELECT {ZONE_COLS} FROM zones WHERE id = %s", (zid,)).fetchone()
    audit("zone_added", user_id=user["id"], username=user["username"], ip=client_ip(request), zone=body.name, kind=body.kind)
    return _zone_row(r)


@router.put("/zones/{zid}")
def edit_zone(zid: int, body: ZoneIn, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    with connect() as conn:
        if not conn.execute("SELECT 1 FROM zones WHERE id = %s", (zid,)).fetchone():
            raise HTTPException(status_code=404, detail="no such zone")
        _save_zone(conn, zid, body)
        r = conn.execute(f"SELECT {ZONE_COLS} FROM zones WHERE id = %s", (zid,)).fetchone()
    audit("zone_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), zone=body.name)
    return _zone_row(r)


@router.delete("/zones/{zid}")
def delete_zone(zid: int, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM zones WHERE id = %s RETURNING name", (zid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such zone")
    audit("zone_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), zone=r[0])
    return {"deleted": r[0]}


# ------------------------------------------------------------------ tracked units

class UnitIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(default="guard", pattern=r"^(guard|vehicle)$")
    device_id: str = Field(min_length=4, max_length=64, pattern=r"^[A-Za-z0-9._-]+$")
    active: bool = True


@router.get("/units")
def list_units(_: dict = Depends(require(*VIEWERS))) -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT u.id, u.name, u.kind, u.device_id, u.active, s.last_at, s.lat, s.lon, s.battery, s.speed_kmh, "
                            "s.zones, s.offline FROM tracked_units u LEFT JOIN unit_state s ON s.unit_id = u.id ORDER BY u.name").fetchall()
    keys = ["id", "name", "kind", "device_id", "active", "last_at", "lat", "lon", "battery", "speed_kmh", "zones", "offline"]
    return {"units": [dict(zip(keys, r)) for r in rows], "unknown_devices": list(UNKNOWN_SEEN), "offline_min": offline_min()}


@router.post("/units", status_code=201)
def add_unit(body: UnitIn, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    from .licence import require_feature
    require_feature("gps")
    with connect() as conn:
        if conn.execute("SELECT 1 FROM tracked_units WHERE name = %s OR device_id = %s", (body.name, body.device_id)).fetchone():
            raise HTTPException(status_code=409, detail="That name or device identifier is already used.")
        uid = conn.execute("INSERT INTO tracked_units (name, kind, device_id, active) VALUES (%s, %s, %s, %s) RETURNING id",
                           (body.name, body.kind, body.device_id, body.active)).fetchone()[0]
    if body.device_id in UNKNOWN_SEEN:
        UNKNOWN_SEEN.remove(body.device_id)
    audit("unit_added", user_id=user["id"], username=user["username"], ip=client_ip(request), unit=body.name, kind=body.kind)
    return {"id": uid, **body.model_dump()}


@router.put("/units/{uid}")
def edit_unit(uid: int, body: UnitIn, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    with connect() as conn:
        if conn.execute("SELECT 1 FROM tracked_units WHERE (name = %s OR device_id = %s) AND id <> %s", (body.name, body.device_id, uid)).fetchone():
            raise HTTPException(status_code=409, detail="That name or device identifier is already used.")
        n = conn.execute("UPDATE tracked_units SET name = %s, kind = %s, device_id = %s, active = %s WHERE id = %s",
                         (body.name, body.kind, body.device_id, body.active, uid)).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="no such unit")
    audit("unit_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), unit=body.name)
    return {"id": uid, **body.model_dump()}


@router.delete("/units/{uid}")
def delete_unit(uid: int, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM tracked_units WHERE id = %s RETURNING name", (uid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such unit")
    audit("unit_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), unit=r[0])
    return {"deleted": r[0]}


class SimIn(BaseModel):
    plan_id: int
    x: float
    y: float
    alarm: str | None = Field(default=None, pattern=r"^sos$")


@router.post("/units/{uid}/simulate")
def simulate(uid: int, body: SimIn, request: Request, user: dict = Depends(require(*EDITORS))) -> dict:
    """Walk-through without a phone: put a unit at a point on a plan, as if its phone reported there.
    Marked as simulated in each event."""
    with connect() as conn:
        r = conn.execute("SELECT id, name, kind FROM tracked_units WHERE id = %s", (uid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such unit")
    g = georef(_plan(body.plan_id)["refs"])
    if not g:
        raise HTTPException(status_code=422, detail="Set this plan's two reference points first.")
    lat, lon = g.to_latlon(body.x, body.y)
    events = record_position({"id": r[0], "name": r[1], "kind": r[2]}, lat, lon, datetime.now(timezone.utc),
                             alarm=body.alarm, simulated=True)
    audit("unit_simulated", user_id=user["id"], username=user["username"], ip=client_ip(request), unit=r[1],
          lat=round(lat, 6), lon=round(lon, 6))
    return {"lat": lat, "lon": lon, "events": events}


# ------------------------------------------------------------------ live map data

@router.get("/live")
def live(plan_id: int, _: dict = Depends(require(*VIEWERS))) -> dict:
    p = _plan(plan_id)
    g = georef(p["refs"])
    from .console import load_devices
    from .screens import alert_cameras
    dev = load_devices()
    status = {c["camera_id"]: {"name": c["name"], "online": c["online"], "tier": c["tier"]} for n in dev["nvrs"] for c in n["channels"]}
    alerts = alert_cameras()
    with connect() as conn:
        cams = conn.execute("SELECT camera_id, x, y, bearing, fov, reach FROM camera_geo WHERE plan_id = %s", (plan_id,)).fetchall()
        units = conn.execute("SELECT u.id, u.name, u.kind, s.last_at, s.lat, s.lon, s.battery, s.offline, s.zones FROM tracked_units u "
                             "JOIN unit_state s ON s.unit_id = u.id WHERE u.active AND s.last_at > now() - interval '12 hours'").fetchall()
        trails = conn.execute("SELECT unit_id, ST_Y(geom::geometry), ST_X(geom::geometry) FROM unit_positions "
                              "WHERE at > now() - interval '15 minutes' ORDER BY unit_id, at").fetchall() if g else []
    trail_px: dict[int, list] = {}
    for uid, lat, lon in trails:
        trail_px.setdefault(uid, []).append([round(v, 1) for v in g.to_px(lat, lon)])
    out_units = []
    for uid, name, kind, last, lat, lon, battery, offline, zones in units:
        if not g or lat is None:
            continue
        x, y = g.to_px(lat, lon)
        out_units.append({"id": uid, "name": name, "kind": kind, "last_at": last, "x": round(x, 1), "y": round(y, 1), "battery": battery,
                          "offline": offline, "zones": zones, "trail": trail_px.get(uid, []),
                          "on_plan": -0.1 * p["width"] <= x <= 1.1 * p["width"] and -0.1 * p["height"] <= y <= 1.1 * p["height"]})
    return {"plan": {k: p[k] for k in ("id", "name", "width", "height", "refs")}, "georeferenced": bool(g),
            "cameras": [{"camera_id": c, "x": x, "y": y, "bearing": b, "fov": f, "reach": r, **status.get(c, {"name": c, "online": None, "tier": "?"}),
                         "alert": alerts.get(c)} for c, x, y, b, f, r in cams],
            "zones": list_zones(plan_id, _), "units": out_units}
