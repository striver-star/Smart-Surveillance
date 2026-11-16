"""Access control and video intercom (release 2.0): Hikvision (and ZKTeco, see zkteco.py) access controllers, face and card terminals
(DS-K series) and video intercom door stations (DS-KV / DS-KD), over ISAPI.

- Devices are added in the console (Doors); the login is kept encrypted (vault.py); doors are found from the
  device's door status and each can be linked to the camera that watches it.
- Every few seconds each device is asked for new access events (/ISAPI/AccessControl/AcsEvent), its door
  states (/ISAPI/AccessControl/AcsWorkStatus) and, for door stations, its call state
  (/ISAPI/VideoIntercom/callStatus). Events are stored with the door, person and verification mode; card
  numbers are masked to their last 4 digits. Kept HSS_ACCESS_DAYS (90).
- HSS events (through the alert rules, on the door's camera so pictures and playback work): door_forced
  (critical), door_held_open (warning), access_denied_repeated (3 refused in 2 minutes at one door, warning),
  access_device_offline (warning), intercom_call (info; operators get a pop-up with the door station's video).
- Door commands (/ISAPI/AccessControl/RemoteControl/door/<n>): open (operators and up, on doors allowed for it,
  with a reason), stay_locked, stay_open and normal (CSO and administrators). All audited.
- Lockdown: doors marked "lock in lockdown" are kept locked for the whole lockdown and set back to normal after.

ZKTeco access panels and terminals (zkteco.py) use the same doors, events, alerts and commands: they call in to
HSS over ZKTeco's push protocol instead of being polled.

Event codes differ a little between models and firmware: the mapping (EVENT_KINDS) is checked on the first real
devices; unknown codes are stored as "other" with their numbers, never dropped.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import vault
from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.access")
router = APIRouter(prefix="/access", tags=["access control"])
WATCH = ("admin", "cso", "operator")
MANAGE = ("admin", "cso")
POLL_S = 3
OFFLINE_AFTER = timedelta(minutes=2)

# (major, minor) -> kind. Major 5 = access events; checked against the first real devices (docs/access-control.md).
EVENT_KINDS = {
    (5, 1): "granted", (5, 38): "granted", (5, 75): "granted", (5, 104): "granted",
    (5, 6): "denied", (5, 7): "denied", (5, 8): "denied", (5, 9): "denied", (5, 39): "denied", (5, 76): "denied",
    (5, 21): "door_unlocked", (5, 22): "door_locked", (5, 23): "exit_button", (5, 25): "door_open", (5, 26): "door_closed",
    (5, 27): "forced", (5, 28): "held_open",
}
KIND_TEXT = {"granted": "Access granted", "denied": "Access refused", "door_unlocked": "Door unlocked", "door_locked": "Door locked",
             "exit_button": "Exit button", "door_open": "Door opened", "door_closed": "Door closed", "forced": "Door forced open",
             "held_open": "Door held open", "duress": "Duress code used", "remote": "Remote command", "call": "Intercom call", "other": "Other event"}
COMMANDS = {"open": "open", "normal": "close", "stay_open": "alwaysOpen", "stay_locked": "alwaysClose"}


# ------------------------------------------------------------------ pure helpers (tested)

def mask_card(card: str) -> str:
    card = (card or "").strip()
    return f"…{card[-4:]}" if len(card) > 4 else card


def classify(major: int, minor: int) -> str:
    return EVENT_KINDS.get((int(major or 0), int(minor or 0)), "other")


def door_states(status: dict, n: int) -> list[dict]:
    """AcsWorkStatus -> per door lock, contact and mode (pure, tested). Hikvision lists are per door, 1-based by position."""
    lock = status.get("doorLockStatus") or []
    mode = status.get("doorStatus") or []
    contact = status.get("magneticStatus") or []
    out = []
    for i in range(n):
        out.append({"door_no": i + 1,
                    "lock_state": {0: "locked", 1: "unlocked"}.get(lock[i] if i < len(lock) else None),
                    "mode": {1: "sleep", 2: "stay_open", 3: "stay_locked", 4: "normal"}.get(mode[i] if i < len(mode) else None),
                    "contact_state": {0: "closed", 1: "open"}.get(contact[i] if i < len(contact) else None)})
    return out


def repeated_denials(times: list[datetime], now: datetime, n: int = 3, window: timedelta = timedelta(minutes=2)) -> bool:
    """n or more refusals at one door within the window (pure, tested)."""
    return sum(1 for t in times if now - t <= window) >= n


def remote_xml(cmd: str) -> str:
    return f"<?xml version='1.0' encoding='UTF-8'?><RemoteControlDoor><cmd>{COMMANDS[cmd]}</cmd></RemoteControlDoor>"


# ------------------------------------------------------------------ talking to a device

class Device:
    def __init__(self, row: dict, transport: httpx.BaseTransport | None = None):
        self.row = row
        self.http = httpx.Client(base_url=f"{row['scheme']}://{row['address']}", auth=httpx.DigestAuth(row["username"], vault.decrypt(row["secret"])),
                                 timeout=6, verify=False, transport=transport)

    def close(self) -> None:
        self.http.close()

    def _ok(self, r: httpx.Response) -> httpx.Response:
        if r.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="The device refused the user name or password.")
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"The device answered HTTP {r.status_code}.")
        return r

    def info(self) -> dict:
        root = ET.fromstring(self._ok(self.http.get("/ISAPI/System/deviceInfo")).text)
        for el in root.iter():
            if isinstance(el.tag, str) and "}" in el.tag:
                el.tag = el.tag.split("}", 1)[1]
        return {k: (root.findtext(k) or "") for k in ("deviceName", "model", "serialNumber", "firmwareVersion", "deviceType")}

    def work_status(self) -> dict:
        return self._ok(self.http.get("/ISAPI/AccessControl/AcsWorkStatus", params={"format": "json"})).json().get("AcsWorkStatus", {})

    def events(self, since: datetime, until: datetime) -> list[dict]:
        out, pos = [], 0
        for _ in range(20):
            body = {"AcsEventCond": {"searchID": uuid.uuid4().hex, "searchResultPosition": pos, "maxResults": 50, "major": 0, "minor": 0,
                                     "startTime": since.isoformat(timespec="seconds"), "endTime": until.isoformat(timespec="seconds")}}
            d = self._ok(self.http.post("/ISAPI/AccessControl/AcsEvent", params={"format": "json"}, json=body)).json().get("AcsEvent", {})
            items = d.get("InfoList") or []
            out += items
            if d.get("responseStatusStrg") != "MORE" or not items:
                break
            pos += len(items)
        return out

    def command(self, door_no: int, cmd: str) -> None:
        self._ok(self.http.put(f"/ISAPI/AccessControl/RemoteControl/door/{door_no}", content=remote_xml(cmd),
                               headers={"Content-Type": "application/xml"}))

    def call_status(self) -> str:
        return (self._ok(self.http.get("/ISAPI/VideoIntercom/callStatus", params={"format": "json"})).json()
                .get("CallStatus", {}).get("status", "idle"))

    def call_signal(self, cmd: str) -> None:
        self._ok(self.http.put("/ISAPI/VideoIntercom/callSignal", params={"format": "json"}, json={"CallSignal": {"cmdType": cmd}}))


# ------------------------------------------------------------------ storage helpers

DEV_COLS = "id, name, kind, address, scheme, username, secret, enabled, info, online, last_seen, last_error, cursor_at, call_status, created_at, vendor, serial"
DOOR_COLS = "id, device_id, door_no, name, camera_id, remote_open, lock_in_lockdown, lock_state, contact_state, mode, status_at"


def _dev(r) -> dict:
    return dict(zip([c.strip() for c in DEV_COLS.split(",")], r))


def _door(r) -> dict:
    return dict(zip([c.strip() for c in DOOR_COLS.split(",")], r))


def _devices(enabled_only: bool = False) -> list[dict]:
    with connect() as conn:
        return [_dev(r) for r in conn.execute(f"SELECT {DEV_COLS} FROM access_devices" + (" WHERE enabled" if enabled_only else "") + " ORDER BY name").fetchall()]


def _doors(device_id: int | None = None) -> list[dict]:
    with connect() as conn:
        sql = (f"SELECT {', '.join('d.' + c.strip() for c in DOOR_COLS.split(','))}, v.vendor FROM doors d JOIN access_devices v ON v.id = d.device_id"
               + (" WHERE d.device_id = %s" if device_id else "") + " ORDER BY d.device_id, d.door_no")
        return [{**_door(r[:-1]), "vendor": r[-1]} for r in conn.execute(sql, (device_id,) if device_id else ()).fetchall()]


def _event_camera(door: dict | None, dev: dict) -> str:
    return (door or {}).get("camera_id") or f"access-{dev['id']}" + (f"-door{door['door_no']}" if door else "")


def raise_event(kind: str, severity: str, dev: dict, door: dict | None, text: str, raw: dict, at: datetime | None = None) -> str | None:
    from .alerts import add_timeline, on_event
    at = at or datetime.now(timezone.utc)
    eid = uuid.uuid4()
    cam = _event_camera(door, dev)
    zone = (door or {}).get("name") or dev["name"]
    with connect() as conn:
        conn.execute("INSERT INTO events (id, camera_id, source_kind, source_ref, tier, type, zone, severity, occurred_at, raw) "
                     "VALUES (%s, %s, 'access', %s, 'A', %s, %s, %s, %s, %s)", (eid, cam, dev["name"], kind, zone, severity, at, Jsonb({**raw, "text": text})))
    try:
        aid = on_event({"id": eid, "camera_id": cam, "zone": zone, "type": kind, "object_class": None, "severity": severity, "confidence": None, "occurred_at": at})
        if aid:
            with connect() as conn:
                add_timeline(conn, aid, "access", text)
    except Exception:
        log.exception("alert rules failed for %s", kind)
    return str(eid)


# ------------------------------------------------------------------ polling

_denials: dict[int, list[datetime]] = {}


def poll_device(dev: dict, transport: httpx.BaseTransport | None = None, now: datetime | None = None) -> None:
    now = now or datetime.now(timezone.utc)
    d = Device(dev, transport)
    try:
        doors = {x["door_no"]: x for x in _doors(dev["id"])}
        if dev["kind"] == "controller":
            st = door_states(d.work_status(), max(len(doors), 1))
            with connect() as conn:
                for s in st:
                    if s["door_no"] in doors:
                        conn.execute("UPDATE doors SET lock_state = %s, contact_state = %s, mode = %s, status_at = now() WHERE id = %s",
                                     (s["lock_state"], s["contact_state"], s["mode"], doors[s["door_no"]]["id"]))
            since = (dev["cursor_at"] or now - timedelta(minutes=10)) - timedelta(seconds=5)
            newest = dev["cursor_at"]
            for e in d.events(since, now + timedelta(seconds=5)):
                store_event(dev, doors, hik_event(e))
                try:
                    t = datetime.fromisoformat(e["time"])
                    newest = max(newest, t) if newest else t
                except (KeyError, ValueError):
                    pass
            if newest and newest != dev["cursor_at"]:
                with connect() as conn:
                    conn.execute("UPDATE access_devices SET cursor_at = %s WHERE id = %s", (newest, dev["id"]))
        else:
            call = d.call_status()
            if call == "ring" and dev["call_status"] != "ring":
                ring(dev, doors.get(1))
            if call != dev["call_status"]:
                with connect() as conn:
                    conn.execute("UPDATE access_devices SET call_status = %s WHERE id = %s", (call, dev["id"]))
                if call != "ring":
                    _publish({"kind": "intercom", "device_id": dev["id"], "status": call})
        if dev["online"] is False:
            log.info("%s: back online", dev["name"])
        with connect() as conn:
            conn.execute("UPDATE access_devices SET online = true, last_seen = now(), last_error = '' WHERE id = %s", (dev["id"],))
    except (httpx.HTTPError, HTTPException, ValueError, ET.ParseError) as exc:
        err = getattr(exc, "detail", None) or exc.__class__.__name__
        with connect() as conn:
            conn.execute("UPDATE access_devices SET last_error = %s WHERE id = %s", (str(err)[:200], dev["id"]))
            if dev["online"] is not False and (not dev["last_seen"] or now - dev["last_seen"] > OFFLINE_AFTER):
                conn.execute("UPDATE access_devices SET online = false WHERE id = %s", (dev["id"],))
                raise_event("access_device_offline", "warning", dev, None, f"{dev['name']} isn't answering ({err}).", {"device": dev["id"]})
    finally:
        d.close()


def hik_event(e: dict) -> dict:
    """A Hikvision AcsEvent item -> the common event form store_event takes (pure, tested)."""
    try:
        at = datetime.fromisoformat(e["time"])
    except (KeyError, ValueError):
        at = datetime.now(timezone.utc)
    return {"kind": classify(e.get("major"), e.get("minor")), "serial_no": e.get("serialNo"), "at": at, "door_no": int(e.get("doorNo") or 0),
            "person": e.get("name") or "", "employee_no": e.get("employeeNoString") or "", "card": e.get("cardNo") or "",
            "verify": e.get("currentVerifyMode") or "", "major": e.get("major"), "minor": e.get("minor")}


def store_event(dev: dict, doors: dict[int, dict], n: dict, alert: bool = True) -> None:
    """Store one access event (common form, from hik_event or zkteco) and raise HSS events from it (not for old
    records a device sends late, e.g. after being offline: alert=False)."""
    kind, at = n["kind"], n["at"]
    door = doors.get(int(n.get("door_no") or 0))
    with connect() as conn:
        r = conn.execute("INSERT INTO access_events (device_id, door_id, serial_no, at, kind, major, minor, person, employee_no, card, verify_mode) "
                         "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (device_id, serial_no) WHERE serial_no IS NOT NULL DO NOTHING RETURNING id",
                         (dev["id"], door["id"] if door else None, n.get("serial_no"), at, kind, n.get("major"), n.get("minor"), (n.get("person") or "")[:80],
                          (n.get("employee_no") or "")[:40], mask_card(n.get("card") or ""), (n.get("verify") or "")[:30])).fetchone()
    if not r:
        return                                     # seen before
    where = (door or {}).get("name") or dev["name"]
    raw = {"device": dev["id"], "door": (door or {}).get("id"), "access_event": r[0], "major": n.get("major"), "minor": n.get("minor")}
    if not alert:
        eid = None
    elif kind == "duress":
        who = f" by {n.get('person') or n.get('employee_no')}" if (n.get("person") or n.get("employee_no")) else ""
        eid = raise_event("access_duress", "critical", dev, door, f"Duress code used at {where}{who}: someone may be forcing them to open the door.", raw, at)
    elif kind == "forced":
        eid = raise_event("door_forced", "critical", dev, door, f"{where} was forced open (opened without a valid card, face or exit button).", raw, at)
    elif kind == "held_open":
        eid = raise_event("door_held_open", "warning", dev, door, f"{where} has been held open too long.", raw, at)
    elif kind == "denied" and door:
        times = [t for t in _denials.get(door["id"], []) if at - t <= timedelta(minutes=2)] + [at]
        _denials[door["id"]] = times
        eid = None
        if repeated_denials(times, at):
            _denials[door["id"]] = []
            who = f" ({n.get('person')})" if n.get("person") else ""
            eid = raise_event("access_denied_repeated", "warning", dev, door, f"Access refused 3 times in 2 minutes at {where}{who}.", raw, at)
    else:
        eid = None
    if eid:
        with connect() as conn:
            conn.execute("UPDATE access_events SET event_id = %s WHERE id = %s", (eid, r[0]))
    if kind in ("door_open", "door_closed", "door_unlocked", "door_locked", "forced", "held_open"):
        _publish({"kind": "door", "door_id": (door or {}).get("id")})


def ring(dev: dict, door: dict | None) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO access_events (device_id, door_id, at, kind) VALUES (%s, %s, now(), 'call')", (dev["id"], (door or {}).get("id")))
    raise_event("intercom_call", "info", dev, door, f"{dev['name']} is calling.", {"device": dev["id"]})
    _publish({"kind": "intercom", "device_id": dev["id"], "status": "ring", "name": dev["name"], "door_id": (door or {}).get("id"),
              "stream": f"door-{dev['id']}", "remote_open": bool((door or {}).get("remote_open"))})


def _publish(msg: dict) -> None:
    from .alerts import broker
    broker.publish(msg)


def poll_once() -> None:
    from . import zkteco
    for dev in _devices(enabled_only=True):
        try:
            if dev["vendor"] == "zkteco":
                zkteco.check_offline(dev)            # ZKTeco devices call in (zkteco.py); nothing to poll
            else:
                poll_device(dev)
        except Exception:
            log.exception("%s: poll failed", dev["name"])


async def background_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(poll_once)
        except Exception as exc:
            log.warning("access polling: %s", exc)
        await asyncio.sleep(POLL_S)


# ------------------------------------------------------------------ door commands, lockdown

def command(door_id: int, cmd: str, by: str, reason: str = "") -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {DOOR_COLS} FROM doors WHERE id = %s", (door_id,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="no such door")
        door = _door(r)
        dev = _dev(conn.execute(f"SELECT {DEV_COLS} FROM access_devices WHERE id = %s", (door["device_id"],)).fetchone())
    if dev["vendor"] == "zkteco":
        from . import zkteco
        zkteco.send_command(dev, door, cmd)
    else:
        d = Device(dev)
        try:
            d.command(door["door_no"], cmd)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"The door's device didn't answer ({exc.__class__.__name__}).") from exc
        finally:
            d.close()
    with connect() as conn:
        conn.execute("INSERT INTO access_events (device_id, door_id, at, kind, by_user, verify_mode) VALUES (%s, %s, now(), 'remote', %s, %s)",
                     (dev["id"], door_id, by, f"{cmd}: {reason}"[:30] if reason else cmd))
        if cmd != "open":                          # ZKTeco can't refuse valid cards remotely: "keep locked" just locks it now
            mode = "normal" if dev["vendor"] == "zkteco" and cmd == "stay_locked" else cmd
            conn.execute("UPDATE doors SET mode = %s, status_at = now() WHERE id = %s", (mode, door_id))
    _publish({"kind": "door", "door_id": door_id})
    return door


def lockdown_doors(on: bool, by: str) -> list[str]:
    """Called by lockdown.py: keep the marked doors locked during a lockdown, back to normal after."""
    done = []
    for door in [x for x in _doors() if x["lock_in_lockdown"]]:
        try:
            command(door["id"], "stay_locked" if on else "normal", by, "lockdown")
            done.append(f"{door['name']} {'locked' if on else 'back to normal'}")
            if on and door.get("vendor") == "zkteco":
                done[-1] += " (ZKTeco: valid cards still open it)"
        except HTTPException as exc:
            done.append(f"{door['name']} failed: {exc.detail}")
    return done


# ------------------------------------------------------------------ endpoints

class DeviceIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    kind: str = Field(pattern="^(controller|doorstation)$")
    address: str = Field(min_length=3, max_length=255)
    scheme: str = Field(default="http", pattern="^https?$")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/devices", status_code=201)
def add_device(body: DeviceIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    row = {**body.model_dump(), "secret": vault.encrypt(body.password)}
    d = Device(row)
    try:
        info = d.info()
        n = 1
        if body.kind == "controller":
            st = d.work_status()
            n = max(len(st.get("doorLockStatus") or []), len(st.get("magneticStatus") or []), 1)
        else:
            d.call_status()
    except (httpx.HTTPError, ET.ParseError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Couldn't talk to the device: {exc.__class__.__name__}. Check the address, user and that ISAPI is on.") from exc
    finally:
        d.close()
    with connect() as conn:
        if conn.execute("SELECT 1 FROM access_devices WHERE address = %s AND vendor = 'hikvision'", (body.address,)).fetchone():
            raise HTTPException(status_code=409, detail=f"{body.address} is already added.")
        did = conn.execute("INSERT INTO access_devices (name, kind, address, scheme, username, secret, info, online, last_seen, cursor_at) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s, true, now(), now()) RETURNING id",
                           (body.name, body.kind, body.address, body.scheme, body.username, row["secret"], Jsonb(info))).fetchone()[0]
        for i in range(1, n + 1):
            conn.execute("INSERT INTO doors (device_id, door_no, name) VALUES (%s, %s, %s)", (did, i, body.name if n == 1 else f"{body.name} door {i}"))
    if body.kind == "doorstation":
        _gateway_path(did, body)
    audit("access_device_added", user_id=user["id"], username=user["username"], ip=client_ip(request), device=body.name, kind=body.kind,
          address=body.address, model=info.get("model"))
    return {"id": did, "info": info, "doors": n}


def _gateway_path(did: int, body: DeviceIn) -> None:
    """The door station's camera in the stream gateway as door-<id>, so the console can show who is calling."""
    import os
    from urllib.parse import quote
    host = body.address.split(":")[0]
    src = f"rtsp://{quote(body.username, safe='')}:{quote(body.password, safe='')}@{host}:554/Streaming/Channels/101"
    try:
        with httpx.Client(base_url=os.environ.get("HSS_GATEWAY_API", "http://gateway:9997"), timeout=5) as gw:
            gw.post(f"/v3/config/paths/add/door-{did}", json={"source": src, "sourceOnDemand": True, "rtspTransport": "tcp"})
    except httpx.HTTPError as exc:
        log.warning("door station %s: gateway path not added: %s", did, exc)


@router.delete("/devices/{did}")
def delete_device(did: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM access_devices WHERE id = %s RETURNING name", (did,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such device")
    audit("access_device_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), device=r[0])
    return {"deleted": True}


class DoorEdit(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    camera_id: str | None = Field(default=None, max_length=64)
    remote_open: bool = False
    lock_in_lockdown: bool = False


@router.put("/doors/{door_id}")
def edit_door(door_id: int, body: DoorEdit, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    with connect() as conn:
        r = conn.execute(f"UPDATE doors SET name = %s, camera_id = %s, remote_open = %s, lock_in_lockdown = %s WHERE id = %s RETURNING {DOOR_COLS}",
                         (body.name, body.camera_id or None, body.remote_open, body.lock_in_lockdown, door_id)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such door")
    audit("door_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), door=body.name, camera=body.camera_id,
          remote_open=body.remote_open, lock_in_lockdown=body.lock_in_lockdown)
    return _door(r)


class CommandIn(BaseModel):
    cmd: str = Field(pattern="^(open|normal|stay_open|stay_locked)$")
    reason: str = Field(min_length=3, max_length=200)


@router.post("/doors/{door_id}/command")
def door_command(door_id: int, body: CommandIn, request: Request, user: dict = Depends(require(*WATCH))) -> dict:
    from .access import check
    from .lockdown import state as lockdown_state
    with connect() as conn:
        r = conn.execute(f"SELECT {DOOR_COLS} FROM doors WHERE id = %s", (door_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such door")
    door = _door(r)
    if door["camera_id"]:
        check(user, door["camera_id"])
    if body.cmd != "open" and user["role"] not in MANAGE:
        raise HTTPException(status_code=403, detail="Only the CSO or an administrator can keep a door open or locked.")
    if body.cmd == "open":
        if not door["remote_open"]:
            raise HTTPException(status_code=403, detail="This door can't be opened from the console (Doors › door settings).")
        if lockdown_state() and user["role"] not in MANAGE:
            raise HTTPException(status_code=423, detail="The site is in lockdown: only the CSO or an administrator can open doors.")
    command(door_id, body.cmd, user["username"], body.reason)
    audit("door_command", user_id=user["id"], username=user["username"], ip=client_ip(request), door=door["name"], cmd=body.cmd, reason=body.reason)
    return {"door": door["name"], "cmd": body.cmd}


class CallIn(BaseModel):
    action: str = Field(pattern="^(reject|hangUp)$")


@router.post("/devices/{did}/call")
def call(did: int, body: CallIn, request: Request, user: dict = Depends(require(*WATCH))) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {DEV_COLS} FROM access_devices WHERE id = %s AND kind = 'doorstation'", (did,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such door station")
    d = Device(_dev(r))
    try:
        d.call_signal(body.action)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="The door station didn't answer.") from exc
    finally:
        d.close()
    audit("intercom_" + body.action.lower(), user_id=user["id"], username=user["username"], ip=client_ip(request), device=_dev(r)["name"])
    return {"ok": True}


@router.get("")
def overview(user: dict = Depends(require(*WATCH))) -> dict:
    from .access import allowed
    devs = _devices()
    doors = [x for x in _doors() if not x["camera_id"] or allowed(user, x["camera_id"])]
    from .zkteco import waiting
    return {"devices": [{k: v for k, v in d.items() if k not in ("secret", "username")} for d in devs], "doors": doors,
            "can_manage": user["role"] in MANAGE, "zk_waiting": waiting() if user["role"] == "admin" else []}


@router.get("/events")
def events(door_id: int | None = None, kind: str = "", person: str = "", since: datetime | None = None, limit: int = 200,
           user: dict = Depends(require(*WATCH))) -> list[dict]:
    from .access import allowed
    sql = ("SELECT e.id, e.at, e.kind, e.person, e.employee_no, e.card, e.verify_mode, e.by_user, e.event_id, d.id, d.name, d.camera_id, v.name "
           "FROM access_events e JOIN access_devices v ON v.id = e.device_id LEFT JOIN doors d ON d.id = e.door_id WHERE true")
    args: list = []
    for cond, val in (("e.door_id = %s", door_id), ("e.kind = %s", kind or None), ("e.person ILIKE %s", f"%{person}%" if person else None), ("e.at >= %s", since)):
        if val is not None:
            sql += f" AND {cond}"
            args.append(val)
    sql += " ORDER BY e.at DESC LIMIT %s"
    with connect() as conn:
        rows = conn.execute(sql, args + [max(1, min(limit, 1000))]).fetchall()
    return [{"id": i, "at": at, "kind": k, "what": KIND_TEXT.get(k, k), "person": p, "employee_no": en, "card": c, "verify": vm, "by": by,
             "event_id": str(ev) if ev else None, "door_id": did, "door": dn, "camera_id": cam, "device": vn}
            for i, at, k, p, en, c, vm, by, ev, did, dn, cam, vn in rows if not cam or allowed(user, cam)]
