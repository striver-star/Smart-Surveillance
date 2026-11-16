"""Master lockdown mode (release 2.0, second batch).

One button for a serious threat (intruders on site, armed robbery, unrest at the gate). While the site is
in lockdown:
- every enabled alert rule is armed, whatever its armed times;
- every new alert (except device faults) is raised to critical, so it sounds, records a clip and escalates
  like any critical alert;
- the outputs chosen for lockdown (floodlights, sirens) are switched on and stay on until it ends;
- a red banner shows in the console, on the wall screens and in the phone app.

Starting it notifies everyone subscribed to "lockdown" (WhatsApp, e-mail fallback, push), and writes to
the logbook and the audit log; so does ending it. Operators, the CSO and administrators can start a
lockdown; only the CSO and administrators can end it.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.lockdown")
router = APIRouter(prefix="/lockdown", tags=["lockdown"])
STARTERS = ("admin", "cso", "operator")
ENDERS = ("admin", "cso")
EVERYONE = ("admin", "cso", "operator", "management", "guard")

_cache: dict = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _read(key: str, default):
    with connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return r[0] if r else default


def _write(key: str, value) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                     (key, Jsonb(value)))


def state() -> dict | None:
    """The lockdown in force, or None. Cached for 3 s: it is read for every event."""
    with _lock:
        if time.monotonic() - _cache["at"] < 3:
            return _cache["value"]
    try:
        v = _read("lockdown", None)
    except Exception:             # the database is busy: keep what we knew
        with _lock:
            return _cache["value"]
    v = v if v and v.get("active") else None
    with _lock:
        _cache.update(at=time.monotonic(), value=v)
    return v


def _forget() -> None:
    with _lock:
        _cache["at"] = 0.0


def config() -> dict:
    c = _read("lockdown_config", {}) or {}
    return {"outputs": [str(x) for x in c.get("outputs", [])]}


def public(s: dict | None) -> dict | None:
    """What every screen may see (no output details)."""
    return {"since": s["since"], "by": s["by_name"], "reason": s["reason"]} if s else None


# ------------------------------------------------------------------ outputs and messages

def _outputs(names: list[str], on: bool, by: str) -> list[str]:
    from .outputs import _by_name, active, switch, turn_off
    done = []
    for name in names:
        o = _by_name(name)
        if not o:
            done.append(f"{name}: no such output")
            continue
        if not o["enabled"]:
            done.append(f"{o['name']} is paused")
            continue
        try:
            if on:
                switch(o, True)
                active.start({**o, "duration_s": 0}, None, by, lambda o=o: switch(o, False))   # stays on until the lockdown ends
                done.append(f"{o['name']} on")
            else:
                turn_off(o)
                done.append(f"{o['name']} off")
        except HTTPException as exc:
            done.append(f"{o['name']} failed: {exc.detail}")
    return done


def _notify(title: str, body: str) -> str:
    try:
        from .notify import dispatch, load_recipients, record, senders
        wa, email, push = senders()
        attempts = dispatch("lockdown", title, body, None, load_recipients(), wa, email, push)
        record("lockdown", attempts)
        ok = sum(a.status == "sent" for a in attempts)
        return f"{ok} of {len(attempts)} messages delivered" if attempts else "nobody is subscribed to 'lockdown'"
    except Exception as exc:          # messages must never stop the lockdown itself
        log.exception("lockdown notification failed")
        return f"messages failed: {exc.__class__.__name__}"


def _logbook(username: str, text: str) -> None:
    try:
        with connect() as conn:
            conn.execute("INSERT INTO logbook_entries (username, category, text) VALUES (%s, 'incident', %s)", (username, text))
    except Exception:
        log.exception("lockdown logbook entry failed")


def _publish(s: dict | None) -> None:
    from .alerts import broker
    broker.publish({"kind": "lockdown", "lockdown": public(s)})


def _after(title: str, body: str, outputs: list[str], on: bool, by: str, key: str) -> None:
    """Outputs and messages take seconds; do them after answering, then record what happened."""
    done = _outputs(outputs, on, by) if outputs else []
    try:                                          # doors marked "lock in lockdown" (access_control.py)
        from .access_control import lockdown_doors
        done += lockdown_doors(on, by)
    except Exception:
        log.exception("lockdown doors failed")
    sent = _notify(title, body)
    try:
        s = _read("lockdown", {}) or {}
        s[key] = {"outputs": done, "messages": sent}
        _write("lockdown", s)
        _forget()
    except Exception:
        log.exception("recording lockdown results failed")


# ------------------------------------------------------------------ endpoints

@router.get("")
def get(_: dict = Depends(require(*EVERYONE))) -> dict:
    s = _read("lockdown", None) or {}
    out = {"active": bool(s.get("active")), "lockdown": public(s) if s.get("active") else None}
    if s:
        out["last"] = {k: s.get(k) for k in ("since", "by_name", "reason", "ended_at", "ended_by", "end_note", "start_result", "end_result")}
    return out


class StartIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("")
def start(body: StartIn, request: Request, user: dict = Depends(require(*STARTERS))) -> dict:
    if state():
        raise HTTPException(status_code=409, detail="The site is already in lockdown.")
    now = datetime.now(timezone.utc)
    name = user.get("display_name") or user["username"]
    s = {"active": True, "since": now.isoformat(), "by": user["username"], "by_name": name, "reason": body.reason.strip()}
    cfg = config()
    _write("lockdown", s)
    _forget()
    audit("lockdown_started", user_id=user["id"], username=user["username"], ip=client_ip(request), reason=s["reason"])
    from .alerts import tz
    local = now.astimezone(tz())
    _logbook(user["username"], f"LOCKDOWN started at {local:%H:%M} by {name}: {s['reason']}")
    _publish(s)
    threading.Thread(target=_after, daemon=True, args=(
        f"LOCKDOWN at {local:%H:%M}", f"{name} put the site in lockdown: {s['reason']}\nAll alert rules are armed and every alert is critical "
        "until the CSO ends it. Follow the emergency plan.", cfg["outputs"], True, user["username"], "start_result")).start()
    return {"active": True, "lockdown": public(s), "outputs": cfg["outputs"]}


class EndIn(BaseModel):
    note: str = Field(default="", max_length=300)


@router.post("/end")
def end(body: EndIn, request: Request, user: dict = Depends(require(*ENDERS))) -> dict:
    s = _read("lockdown", None) or {}
    if not s.get("active"):
        raise HTTPException(status_code=409, detail="The site isn't in lockdown.")
    now = datetime.now(timezone.utc)
    name = user.get("display_name") or user["username"]
    s.update(active=False, ended_at=now.isoformat(), ended_by=name, end_note=body.note.strip())
    _write("lockdown", s)
    _forget()
    started = datetime.fromisoformat(s["since"])
    mins = max(1, round((now - started).total_seconds() / 60))
    audit("lockdown_ended", user_id=user["id"], username=user["username"], ip=client_ip(request), minutes=mins, note=s["end_note"])
    from .alerts import tz
    local = now.astimezone(tz())
    _logbook(user["username"], f"Lockdown ended at {local:%H:%M} by {name} after {mins} min" + (f": {s['end_note']}" if s["end_note"] else ""))
    _publish(None)
    threading.Thread(target=_after, daemon=True, args=(
        f"Lockdown ended at {local:%H:%M}", f"{name} ended the lockdown after {mins} min." + (f" {s['end_note']}" if s["end_note"] else "")
        + "\nAlert rules are back to their normal times.", config()["outputs"], False, user["username"], "end_result")).start()
    return {"active": False, "minutes": mins}


class ConfigIn(BaseModel):
    outputs: list[str] = Field(default_factory=list, max_length=50)


@router.get("/config")
def get_config(_: dict = Depends(require("admin", "cso"))) -> dict:
    return config()


@router.put("/config")
def put_config(body: ConfigIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    from .outputs import _by_name
    unknown = [n for n in body.outputs if not _by_name(n)]
    if unknown:
        raise HTTPException(status_code=422, detail=f"no such output: {', '.join(unknown)}")
    _write("lockdown_config", {"outputs": body.outputs})
    audit("lockdown_config_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), outputs=body.outputs)
    return config()
