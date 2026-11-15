"""Phone app for guards and supervisors (release 2.0, first batch): check-ins and SOS.

The app (web/console/m/) is a web app installed on the phone's home screen. Guards (role 'guard', which
can use nothing else) and supervisors check in at patrol checkpoints with the phone's GPS and can send an
SOS. Each person gets a tracked unit of their own ("app-<username>"), so check-ins and SOS go through the
same zone tests, events and alert rules as Traccar positions: a check-in inside a checkpoint zone counts
as a patrol visit, and SOS raises a critical alert on the zone's camera.

Continuous tracking stays with the Traccar Client app: a web page only has GPS while it is open.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

router = APIRouter(prefix="/mobile", tags=["mobile"])
PEOPLE = ("admin", "cso", "operator", "guard")
MAX_ACCURACY_M = 50


def ensure_unit(user: dict) -> dict:
    """This person's tracked unit, made on first use."""
    with connect() as conn:
        r = conn.execute("SELECT id, name, kind FROM tracked_units WHERE username = %s", (user["username"],)).fetchone()
        if r:
            return {"id": r[0], "name": r[1], "kind": r[2]}
    from .licence import require_feature
    require_feature("gps")
    name = (user.get("display_name") or user["username"]).strip()[:60]
    with connect() as conn:
        if conn.execute("SELECT 1 FROM tracked_units WHERE name = %s", (name,)).fetchone():
            name = f"{name} ({user['username']})"[:60]
        uid = conn.execute("INSERT INTO tracked_units (name, kind, device_id, username) VALUES (%s, 'guard', %s, %s) RETURNING id",
                           (name, f"app-{user['username']}"[:64], user["username"])).fetchone()[0]
    return {"id": uid, "name": name, "kind": "guard"}


def nearest_checkpoint(lat: float, lon: float) -> tuple[str, float] | None:
    with connect() as conn:
        r = conn.execute("SELECT name, ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) FROM zones "
                         "WHERE enabled AND kind = 'checkpoint' AND geom IS NOT NULL ORDER BY 2 LIMIT 1", (lon, lat)).fetchone()
    return (r[0], float(r[1])) if r else None


class Position(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=100000)


@router.get("/me")
def me(user: dict = Depends(require(*PEOPLE))) -> dict:
    with connect() as conn:
        u = conn.execute("SELECT u.id, s.last_at FROM tracked_units u LEFT JOIN unit_state s ON s.unit_id = u.id WHERE u.username = %s",
                         (user["username"],)).fetchone()
        visits = conn.execute("SELECT z.name, v.at FROM checkpoint_visits v JOIN zones z ON z.id = v.zone_id WHERE v.unit_id = %s "
                              "AND v.at > now() - interval '12 hours' ORDER BY v.at DESC LIMIT 20", (u[0] if u else -1,)).fetchall()
    return {"username": user["username"], "name": user.get("display_name") or user["username"], "role": user["role"],
            "supervisor": user["role"] in ("admin", "cso", "operator"),
            "check_ins": [{"checkpoint": n, "at": at} for n, at in visits], "last_report": u[1] if u else None}


@router.post("/checkin")
def checkin(p: Position, request: Request, user: dict = Depends(require(*PEOPLE))) -> dict:
    if p.accuracy is not None and p.accuracy > MAX_ACCURACY_M:
        raise HTTPException(status_code=422, detail=f"The phone's position is only accurate to {p.accuracy:.0f} m. Step outside or wait "
                                                    f"a few seconds and try again (needs {MAX_ACCURACY_M} m or better).")
    from .geo import record_position
    unit = ensure_unit(user)
    events = record_position(unit, p.lat, p.lon, datetime.now(timezone.utc), accuracy=p.accuracy)
    visited = [e for e in events if e["type"] == "checkpoint_visit"]
    with connect() as conn:
        inside = conn.execute("SELECT z.name FROM zones z JOIN unit_state s ON z.id = ANY(s.zones) WHERE s.unit_id = %s AND z.kind = 'checkpoint'",
                              (unit["id"],)).fetchall()
    audit("guard_checkin", user_id=user["id"], username=user["username"], ip=client_ip(request), lat=round(p.lat, 6), lon=round(p.lon, 6),
          accuracy=p.accuracy, checkpoint=inside[0][0] if inside else "")
    if inside:
        return {"ok": True, "checkpoint": inside[0][0], "new_visit": bool(visited),
                "message": f"Checked in at {inside[0][0]}." if visited else f"Already checked in at {inside[0][0]}; recorded again."}
    near = nearest_checkpoint(p.lat, p.lon)
    return {"ok": False, "checkpoint": None,
            "message": f"Not at a checkpoint. Nearest: {near[0]}, about {near[1]:.0f} m away." if near else "No checkpoints are set up on the site map yet."}


class SosIn(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    accuracy: float | None = Field(default=None, ge=0, le=100000)
    note: str = Field(default="", max_length=300)


@router.post("/sos")
def sos(body: SosIn, request: Request, user: dict = Depends(require(*PEOPLE))) -> dict:
    from .geo import record_position, store_event
    now = datetime.now(timezone.utc)
    name = user.get("display_name") or user["username"]
    if body.lat is not None and body.lon is not None:
        unit = ensure_unit(user)
        events = record_position(unit, body.lat, body.lon, now, accuracy=body.accuracy, alarm="sos")
        sos_events = [e for e in events if e["type"] == "sos"]
    else:
        sos_events = [store_event(camera_id=f"user-{user['username']}", type_="sos", severity="critical", zone=None, object_class="human",
                                  lat=None, lon=None, raw={"unit": name, "text": f"SOS from {name} (no location)" + (f": {body.note}" if body.note else "")})]
    for e in sos_events:                       # say who sent it, and from where, in the alert's history
        if e.get("alert_id"):
            from .alerts import add_timeline
            where = (f" at {body.lat:.6f}, {body.lon:.6f}" + (f" (\u00b1{body.accuracy:.0f} m)" if body.accuracy else "")) if body.lat is not None else " (no location)"
            with connect() as conn:
                add_timeline(conn, e["alert_id"], "sos", f"SOS from {name}{where}" + (f": {body.note}" if body.note else ""), user["username"])
    audit("guard_sos", user_id=user["id"], username=user["username"], ip=client_ip(request), located=body.lat is not None, note=body.note)
    return {"sent": True, "at": now, "alert_id": sos_events[0]["alert_id"] if sos_events else None, "located": body.lat is not None}
