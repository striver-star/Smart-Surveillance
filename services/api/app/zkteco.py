"""ZKTeco access control (release 2.0): InBio / C3 access panels and standalone face, fingerprint and card terminals
(SpeedFace, ProFace, F-series) over ZKTeco's push protocol ("PUSH SDK", also called ADMS or cloud server).

ZKTeco devices are not polled: each one is set up with the HSS server's address and port 8088 (Comm › Cloud Server
Setting) and calls in by itself over plain HTTP:

- GET  /iclock/cdata?SN=..&options=all  first contact; HSS answers with its settings (real-time upload, every 2 s)
- POST /iclock/cdata?SN=..&table=rtlog   access events (panels): time, pin, cardno, eventaddr (door), event, verifytype
- POST /iclock/cdata?SN=..&table=rtstate door states (panels): door contacts and lock relays
- POST /iclock/cdata?SN=..&table=ATTLOG  verifications (terminals): PIN, time, status, verify
- POST /iclock/cdata?SN=..&table=USERINFO or user   the device's users, so events show names
- GET  /iclock/getrequest?SN=..          asks for commands; HSS answers "C:<id>:<command>" lines or "OK"
- POST /iclock/devicecmd?SN=..           the result of each command (ID=..&Return=0&CMD=..)

Security: a device is only listened to once an administrator has added it by serial number (Doors › Access
devices › Waiting to be added), and only from the address it was added from. Until then it is listed with its
address and nothing it sends is kept. The port is open only on the security VLAN (proxy/Caddyfile, :8088).

Doors, events, alerts, commands, lockdown and retention are the same as for Hikvision (access_control.py); the
event codes and the door-command format are checked on the first real devices (docs/access-control.md).
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.zkteco")
push = APIRouter(prefix="/iclock", tags=["ZKTeco push"], include_in_schema=False)
router = APIRouter(prefix="/access/zkteco", tags=["access control"])
CMD_WAIT_S = 12            # how long a console command waits for the device to confirm it
OLD_EVENT = timedelta(minutes=10)
USER_QUERIES = ("DATA QUERY tablename=user,fielddesc=*,filter=*", "DATA QUERY USERINFO")   # panels / terminals; the other is refused

# ZKTeco access event numbers (InBio / C3 panels, rtlog "event"). Checked on the first real panel.
ZK_EVENTS = {
    **{n: "granted" for n in (0, 1, 2, 3, 4, 5, 14, 15, 16, 17, 18, 19, 26, 32)},
    **{n: "denied" for n in (20, 21, 22, 23, 24, 25, 27, 29, 30, 31, 33, 34, 35, 36)},
    8: "door_unlocked", 9: "door_locked", 28: "held_open", 101: "duress", 103: "duress", 102: "forced",
    200: "door_open", 201: "door_closed", 202: "exit_button", 205: "door_unlocked",
}
ZK_VERIFY = {0: "card or fingerprint", 1: "fingerprint", 3: "password", 4: "card", 6: "card and fingerprint", 11: "card and password",
             15: "face", 25: "palm", 200: "other"}
# Terminal ATTLOG "Verify" field
ATT_VERIFY = {0: "password", 1: "fingerprint", 2: "card", 3: "password and fingerprint", 4: "fingerprint and card", 15: "face", 25: "palm"}


# ------------------------------------------------------------------ pure helpers (tested)

def kv(line: str) -> dict:
    """'time=..\\tpin=1\\tevent=0' -> dict; a leading table word ('user uid=1 ...' / 'rtlog time=..') is ignored."""
    out = {}
    for part in line.strip().split("\t"):
        part = part.strip()
        if " " in part.split("=", 1)[0]:
            part = part.split(" ", 1)[1]            # 'user uid=1' -> 'uid=1'
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def local_time(s: str, tz: str | None = None) -> datetime:
    """Device time is local, without a zone: read it in the site's zone (HSS_TZ)."""
    t = datetime.strptime(s.strip(), "%Y-%m-%d %H:%M:%S")
    return t.replace(tzinfo=ZoneInfo(tz or os.environ.get("HSS_TZ", "Africa/Lagos"))).astimezone(timezone.utc)


def _int(v, default: int = 0) -> int:
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return default


def stable_serial(*parts: str) -> int:
    """A repeatable event number for records that have none (terminal ATTLOG), so re-sends aren't stored twice."""
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:7], "big")


def rtlog_event(f: dict, tz: str | None = None) -> dict:
    """An rtlog record -> the common event form (access_control.store_event)."""
    ev = _int(f.get("event"), -1)
    kind = ZK_EVENTS.get(ev, "other")
    pin = f.get("pin", "")
    card = f.get("cardno", "")
    return {"kind": kind, "serial_no": _int(f.get("index")) or stable_serial(f.get("time", ""), str(ev), f.get("eventaddr", ""), pin),
            "at": local_time(f["time"], tz), "door_no": _int(f.get("eventaddr")), "person": "", "employee_no": "" if pin in ("", "0") else pin,
            "card": "" if card in ("", "0") else card, "verify": ZK_VERIFY.get(_int(f.get("verifytype"), -1), "") if kind in ("granted", "denied", "duress") else "", "major": 0, "minor": ev}


def attlog_event(line: str, tz: str | None = None) -> dict | None:
    """A terminal ATTLOG line 'PIN<TAB>2026-11-16 08:01:02<TAB>status<TAB>verify...' -> a granted event at door 1."""
    p = line.rstrip("\r\n").split("\t")
    if len(p) < 2 or not p[0].strip():
        return None
    try:
        at = local_time(p[1], tz)
    except ValueError:
        return None
    verify = _int(p[3], -1) if len(p) > 3 else -1
    return {"kind": "granted", "serial_no": stable_serial(p[0].strip(), p[1].strip()), "at": at, "door_no": 1, "person": "",
            "employee_no": p[0].strip(), "card": "", "verify": ATT_VERIFY.get(verify, ""), "major": 0, "minor": None}


def rtstate_doors(f: dict, n: int) -> list[dict]:
    """rtstate 'sensor' (one byte per door, door 1 first: 0 none, 1 closed, 2 open) and 'relay' (one bit per door,
    1 = unlocked) -> per door contact and lock (checked on the first real panel)."""
    sensor, relay = f.get("sensor", ""), f.get("relay", "")
    try:
        relay_bits = int(relay, 16) if relay else None
    except ValueError:
        relay_bits = None
    out = []
    for i in range(n):
        byte = sensor[i * 2:i * 2 + 2]
        try:
            contact = {1: "closed", 2: "open"}.get(int(byte, 16)) if byte else None
        except ValueError:
            contact = None
        lock = None if relay_bits is None else ("unlocked" if relay_bits >> i & 1 else "locked")
        out.append({"door_no": i + 1, "contact_state": contact, "lock_state": lock})
    return out


def control_commands(cmd: str, door_no: int, open_s: int = 5) -> list[str]:
    """HSS door command -> ZKTeco 'CONTROL DEVICE AABBCCDDEE' commands: AA operation (01 output, 04 normal-open
    off), BB door, CC 01 = the door's lock, DD seconds (00 close, FF stay open). Checked on the first real panel."""
    d = f"{door_no:02X}"
    return {"open": [f"CONTROL DEVICE 01{d}01{open_s:02X}00"],
            "stay_open": [f"CONTROL DEVICE 01{d}01FF00"],
            "normal": [f"CONTROL DEVICE 04{d}000000", f"CONTROL DEVICE 01{d}010000"],
            "stay_locked": [f"CONTROL DEVICE 04{d}000000", f"CONTROL DEVICE 01{d}010000"]}[cmd]


def options_reply(sn: str) -> str:
    return "\n".join([f"GET OPTION FROM: {sn}", "Stamp=9999", "OpStamp=9999", "PhotoStamp=9999", "ErrorDelay=30", "Delay=2",
                      "TransTimes=", "TransInterval=1", "TransFlag=1111000000", "Realtime=1", "Encrypt=0", "ServerVer=HSS", ""])


# ------------------------------------------------------------------ which device is calling

def _known(sn: str, ip: str) -> dict | None:
    """The added device with this serial number, if the call comes from its address; otherwise list it as waiting."""
    from .access_control import DEV_COLS, _dev
    sn = (sn or "").strip()[:40]
    if not sn:
        return None
    with connect() as conn:
        r = conn.execute(f"SELECT {DEV_COLS} FROM access_devices WHERE serial = %s AND vendor = 'zkteco'", (sn,)).fetchone()
        if r is None:
            conn.execute("INSERT INTO zk_waiting (serial, ip) VALUES (%s, %s) ON CONFLICT (serial) DO UPDATE SET ip = EXCLUDED.ip, last_seen = now()", (sn, ip))
            return None
        dev = _dev(r)
        if not dev["enabled"]:
            return None
        if dev["address"] and dev["address"] != ip:  # listed so an administrator can accept the new address
            conn.execute("INSERT INTO zk_waiting (serial, ip) VALUES (%s, %s) ON CONFLICT (serial) DO UPDATE SET ip = EXCLUDED.ip, last_seen = now()", (sn, ip))
            conn.execute("UPDATE access_devices SET last_error = %s WHERE id = %s", (f"ignored: called from {ip}, added at {dev['address']}"[:200], dev["id"]))
            return None
        back = dev["online"] is False
        conn.execute("DELETE FROM zk_waiting WHERE serial = %s", (sn,))
        conn.execute("UPDATE access_devices SET online = true, last_seen = now(), last_error = CASE WHEN last_error LIKE 'ignored:%%' THEN '' ELSE last_error END "
                     "WHERE id = %s", (dev["id"],))
    if back:
        log.info("%s: back online", dev["name"])
        ask_for_users(dev["id"])
    return dev


def waiting() -> list[dict]:
    """Devices calling in that aren't added, and added ones calling from a new address (moved_from)."""
    with connect() as conn:
        rows = conn.execute("SELECT w.serial, w.ip, w.first_seen, w.last_seen, a.id, a.name, a.address FROM zk_waiting w "
                            "LEFT JOIN access_devices a ON a.serial = w.serial WHERE w.last_seen > now() - interval '7 days' ORDER BY w.last_seen DESC").fetchall()
    return [{"serial": s, "ip": ip, "first_seen": f, "last_seen": l, "device_id": did, "device": dn, "moved_from": addr}
            for s, ip, f, l, did, dn, addr in rows]


def check_offline(dev: dict, now: datetime | None = None) -> None:
    from .access_control import OFFLINE_AFTER, raise_event
    now = now or datetime.now(timezone.utc)
    if dev["online"] is not False and dev["last_seen"] and now - dev["last_seen"] > OFFLINE_AFTER:
        with connect() as conn:
            conn.execute("UPDATE access_devices SET online = false WHERE id = %s", (dev["id"],))
        raise_event("access_device_offline", "warning", dev, None, f"{dev['name']} hasn't called in for {int((now - dev['last_seen']).total_seconds() // 60)} minutes.",
                    {"device": dev["id"]})


# ------------------------------------------------------------------ what a device sends

def _names(dev_id: int) -> dict[str, str]:
    with connect() as conn:
        return dict(conn.execute("SELECT pin, name FROM zk_people WHERE device_id = %s", (dev_id,)).fetchall())


def receive(dev: dict, table: str, body: str, now: datetime | None = None) -> int:
    """Store what a device sent (one table, many lines). Returns how many records were read."""
    from .access_control import _doors, _publish, store_event
    now = now or datetime.now(timezone.utc)
    table = table.lower()
    lines = [x for x in body.splitlines() if x.strip()]
    doors = {x["door_no"]: x for x in _doors(dev["id"])}
    if table in ("userinfo", "user"):
        with connect() as conn:
            for line in lines:
                f = kv(line)
                pin, name = f.get("pin", "").strip(), f.get("name", "").strip()
                if pin:
                    conn.execute("INSERT INTO zk_people (device_id, pin, name) VALUES (%s, %s, %s) ON CONFLICT (device_id, pin) DO UPDATE SET name = EXCLUDED.name",
                                 (dev["id"], pin[:40], name[:80]))
        return len(lines)
    if table == "rtstate":
        _clock(dev, [kv(x) for x in lines], now)
        changed = False
        with connect() as conn:
            for line in lines:
                for s in rtstate_doors(kv(line), max(doors) if doors else 1):
                    door = doors.get(s["door_no"])
                    if door and (door["contact_state"], door["lock_state"]) != (s["contact_state"], s["lock_state"]):
                        conn.execute("UPDATE doors SET contact_state = %s, lock_state = %s, status_at = now() WHERE id = %s",
                                     (s["contact_state"], s["lock_state"], door["id"]))
                        door.update(s)
                        changed = True
        if changed:
            _publish({"kind": "door", "door_id": None})
        return len(lines)
    if table not in ("rtlog", "attlog"):
        return 0                                   # OPERLOG, photos, templates: not needed
    names = _names(dev["id"])
    off = timedelta(seconds=(dev.get("info") or {}).get("clock_offset_s", 0))
    n = 0
    for line in lines:
        try:
            e = rtlog_event(kv(line)) if table == "rtlog" else attlog_event(line)
        except (KeyError, ValueError):
            e = None
        if not e or (table == "rtlog" and _int(kv(line).get("event"), -1) == 255):
            continue                               # 255 = a status record, not an event
        e["person"] = names.get(e["employee_no"], "")
        e["at"] += off                             # the device's clock is off: use the real time (cameras, alerts)
        store_event(dev, doors, e, alert=now - e["at"] <= OLD_EVENT)
        n += 1
    return n


CLOCK_SLACK = timedelta(seconds=60)


def clock_offset(state_times: list[datetime], now: datetime) -> timedelta:
    """How far behind (positive) or ahead the device's clock is, from its newest status report, which it sends as it
    happens; under a minute counts as right (pure, tested)."""
    if not state_times:
        return timedelta(0)
    off = now - max(state_times)
    return off if abs(off) > CLOCK_SLACK else timedelta(0)


def _clock(dev: dict, states: list[dict], now: datetime) -> None:
    times = []
    for f in states:
        try:
            times.append(local_time(f["time"]))
        except (KeyError, ValueError):
            pass
    if not times:
        return
    secs = int(clock_offset(times, now).total_seconds())
    old = (dev.get("info") or {}).get("clock_offset_s", 0)
    if abs(secs - old) < 30:
        return
    with connect() as conn:
        conn.execute("UPDATE access_devices SET info = info || %s, last_error = %s WHERE id = %s",
                     (Jsonb({"clock_offset_s": secs}), f"the device's clock is {abs(secs) // 60} min {'slow' if secs > 0 else 'fast'}: set its time and zone (HSS corrects event times meanwhile)" if secs else "", dev["id"]))
    dev.setdefault("info", {})["clock_offset_s"] = secs
    log.warning("%s: clock offset %s s", dev["name"], secs)


def _text(s: str) -> PlainTextResponse:
    return PlainTextResponse(s)


@push.get("/cdata")
def cdata_get(request: Request, SN: str = "", options: str = "") -> PlainTextResponse:
    dev = _known(SN, client_ip(request))
    return _text(options_reply(dev["serial"]) if dev else "OK")


@push.post("/cdata")
async def cdata_post(request: Request, SN: str = "", table: str = "") -> PlainTextResponse:
    import asyncio
    body = (await request.body())[:2_000_000].decode("utf-8", "replace")
    dev = await asyncio.to_thread(_known, SN, client_ip(request))
    if not dev:
        return _text("OK")                        # not added (yet): read nothing
    try:
        n = await asyncio.to_thread(receive, dev, table, body)
    except Exception:
        log.exception("%s: couldn't read %s", dev["name"], table)
        return _text("OK")
    return _text(f"OK: {n}")


@push.post("/querydata")
async def querydata(request: Request, SN: str = "", tablename: str = "", table: str = "") -> PlainTextResponse:
    """Answers to HSS's DATA QUERY (newer firmware sends them here rather than to /cdata)."""
    return await cdata_post(request, SN, tablename or table)


def ask_for_users(dev_id: int) -> None:
    """Ask the device for its user list, so events show names (sent when added and when it comes back online)."""
    with connect() as conn:
        for c in USER_QUERIES:
            conn.execute("INSERT INTO zk_commands (device_id, command) VALUES (%s, %s)", (dev_id, c))


@push.get("/getrequest")
def getrequest(request: Request, SN: str = "") -> PlainTextResponse:
    dev = _known(SN, client_ip(request))
    if not dev:
        return _text("OK")
    with connect() as conn:
        rows = conn.execute("UPDATE zk_commands SET sent_at = now() WHERE id IN (SELECT id FROM zk_commands WHERE device_id = %s AND sent_at IS NULL "
                            "AND queued_at > now() - interval '1 minute' ORDER BY id LIMIT 10) RETURNING id, command", (dev["id"],)).fetchall()
    return _text("".join(f"C:{i}:{c}\n" for i, c in sorted(rows)) or "OK")


@push.post("/devicecmd")
async def devicecmd(request: Request, SN: str = "") -> PlainTextResponse:
    import asyncio
    body = (await request.body())[:100_000].decode("utf-8", "replace")
    dev = await asyncio.to_thread(_known, SN, client_ip(request))
    if dev:
        def save():
            with connect() as conn:
                for line in body.splitlines():
                    f = dict(parse_qsl(line.strip()))
                    if f.get("ID", "").isdigit():
                        conn.execute("UPDATE zk_commands SET done_at = now(), result = %s WHERE id = %s AND device_id = %s",
                                     (_int(f.get("Return"), -1), int(f["ID"]), dev["id"]))
        await asyncio.to_thread(save)
    return _text("OK")


@push.get("/ping")
def ping(request: Request, SN: str = "") -> PlainTextResponse:
    _known(SN, client_ip(request))
    return _text("OK")


# ------------------------------------------------------------------ commands from the console

def send_command(dev: dict, door: dict, cmd: str) -> None:
    """Queue the command for the device to collect, and wait (a few seconds) for it to say it's done."""
    if not dev["online"]:
        raise HTTPException(status_code=502, detail=f"{dev['name']} isn't calling in, so it can't collect the command.")
    ids = []
    with connect() as conn:
        for c in control_commands(cmd, door["door_no"]):
            ids.append(conn.execute("INSERT INTO zk_commands (device_id, command) VALUES (%s, %s) RETURNING id", (dev["id"], c)).fetchone()[0])
    deadline = time.monotonic() + CMD_WAIT_S
    while time.monotonic() < deadline:
        with connect() as conn:
            rows = conn.execute("SELECT result FROM zk_commands WHERE id = ANY(%s) AND done_at IS NOT NULL", (ids,)).fetchall()
        if len(rows) == len(ids):
            bad = [r for (r,) in rows if r != 0]
            if bad:
                raise HTTPException(status_code=502, detail=f"{dev['name']} refused the command (code {bad[0]}).")
            return
        time.sleep(0.5)
    with connect() as conn:
        conn.execute("UPDATE zk_commands SET sent_at = coalesce(sent_at, now()), done_at = coalesce(done_at, now()), result = coalesce(result, -999) "
                     "WHERE id = ANY(%s)", (ids,))       # not sent later by surprise
    raise HTTPException(status_code=504, detail=f"{dev['name']} didn't confirm the command within {CMD_WAIT_S} seconds. Check the door before trying again.")


# ------------------------------------------------------------------ adding a device (administrators)

class ZkIn(BaseModel):
    serial: str = Field(min_length=3, max_length=40)
    name: str = Field(min_length=2, max_length=60)
    doors: int = Field(default=1, ge=1, le=4)


@router.post("/devices", status_code=201)
def add(body: ZkIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        w = conn.execute("SELECT ip FROM zk_waiting WHERE serial = %s", (body.serial.strip(),)).fetchone()
        if not w:
            raise HTTPException(status_code=404, detail="That serial number hasn't called in. Set the device's cloud server to this server, port 8088, and wait a minute.")
        if conn.execute("SELECT 1 FROM access_devices WHERE serial = %s", (body.serial.strip(),)).fetchone():
            raise HTTPException(status_code=409, detail="That device is already added.")
        did = conn.execute("INSERT INTO access_devices (name, kind, address, scheme, username, secret, vendor, serial, info, online, last_seen) "
                           "VALUES (%s, 'controller', %s, 'http', '', '', 'zkteco', %s, %s, true, now()) RETURNING id",
                           (body.name, w[0], body.serial.strip(), Jsonb({"model": "ZKTeco", "serialNumber": body.serial}))).fetchone()[0]
        for i in range(1, body.doors + 1):
            conn.execute("INSERT INTO doors (device_id, door_no, name) VALUES (%s, %s, %s)", (did, i, body.name if body.doors == 1 else f"{body.name} door {i}"))
        conn.execute("DELETE FROM zk_waiting WHERE serial = %s", (body.serial.strip(),))
    ask_for_users(did)
    audit("access_device_added", user_id=user["id"], username=user["username"], ip=client_ip(request), device=body.name, kind="zkteco",
          address=w[0], serial=body.serial)
    return {"id": did, "doors": body.doors, "address": w[0]}


@router.post("/devices/{did}/accept-address")
def accept_address(did: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    """An added device now calls in from a new address (e.g. it was moved, or its DHCP lease changed)."""
    with connect() as conn:
        r = conn.execute("SELECT a.name, a.address, w.ip FROM access_devices a JOIN zk_waiting w ON w.serial = a.serial WHERE a.id = %s", (did,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="That device isn't calling from a new address.")
        conn.execute("UPDATE access_devices SET address = %s, last_error = '' WHERE id = %s", (r[2], did))
        conn.execute("DELETE FROM zk_waiting WHERE serial = (SELECT serial FROM access_devices WHERE id = %s)", (did,))
    audit("zk_address_accepted", user_id=user["id"], username=user["username"], ip=client_ip(request), device=r[0], old=r[1], new=r[2])
    return {"address": r[2]}


@router.delete("/waiting/{serial}")
def forget(serial: str, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        conn.execute("DELETE FROM zk_waiting WHERE serial = %s", (serial,))
    audit("zk_waiting_removed", user_id=user["id"], username=user["username"], ip=client_ip(request), serial=serial)
    return {"ok": True}
