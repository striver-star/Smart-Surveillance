"""Sirens, lights and relays (release 2.0, first batch).

An output is either an NVR alarm output (a relay on the NVR's back panel wired to a siren, strobe or
floodlight, switched over ISAPI: PUT /ISAPI/System/IO/outputs/<n>/trigger) or a network device switched by
a web address (an IP relay box, a siren controller). Alert rules switch outputs on ("Switch on" in the rule);
each output turns itself off after its duration, and acknowledging the alert that started it silences it.
Operators can switch outputs on and off from the console; everything is in the alert timeline and the
audit log.

Cameras with their own strobe and speaker (AcuSense -SU models) are best set in the camera's own event
linkage: they then react at once, even if this server is down (docs/outputs.md).
"""
from __future__ import annotations

import logging
import re
import threading
import time

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator

from . import vault
from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.outputs")
router = APIRouter(prefix="/outputs", tags=["outputs"])
MANAGERS = ("admin", "cso")
OPERATORS = ("admin", "cso", "operator")
COLS = "id, name, kind, nvr_alias, port, url_on, url_off, method, username, secret, duration_s, enabled"


def relay_xml(on: bool) -> str:
    return ("<?xml version='1.0' encoding='UTF-8'?><IOPortData version='2.0' xmlns='http://www.hikvision.com/ver20/XMLSchema'>"
            f"<outputState>{'high' if on else 'low'}</outputState></IOPortData>")


def _row(r) -> dict:
    return dict(zip([c.strip() for c in COLS.split(",")], r))


def _get(oid: int) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS} FROM outputs WHERE id = %s", (oid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such output")
    return _row(r)


def _by_name(name: str) -> dict | None:
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS} FROM outputs WHERE lower(name) = lower(%s)", (name.strip(),)).fetchone()
    return _row(r) if r else None


def switch(o: dict, on: bool, transport: httpx.BaseTransport | None = None) -> None:
    """Switch an output on or off. Raises HTTPException with a plain reason."""
    try:
        if o["kind"] == "nvr_relay":
            with connect() as conn:
                n = conn.execute("SELECT address, username, secret, scheme FROM nvrs WHERE alias = %s", (o["nvr_alias"],)).fetchone()
            if not n:
                raise HTTPException(status_code=404, detail=f"NVR {o['nvr_alias']} is not in Devices.")
            with httpx.Client(base_url=f"{n[3]}://{n[0]}", auth=httpx.DigestAuth(n[1], vault.decrypt(n[2])), timeout=5,
                              verify=False, transport=transport) as http:
                r = http.put(f"/ISAPI/System/IO/outputs/{int(o['port'])}/trigger", content=relay_xml(on),
                             headers={"Content-Type": "application/xml"})
            if r.status_code in (401, 403):
                raise HTTPException(status_code=502, detail="The NVR refused: give the HSS user the 'Remote Alarm Output' right "
                                                            "(or 'Remote Parameters Settings').")
            if r.status_code >= 400:
                raise HTTPException(status_code=502, detail=f"The NVR refused output {o['port']} (HTTP {r.status_code}); check the output number.")
            return
        url = o["url_on"] if on else o["url_off"]
        if not url:
            return                                     # a device with no 'off' address switches itself off
        auth = httpx.DigestAuth(o["username"], vault.decrypt(o["secret"])) if o["username"] else None
        with httpx.Client(timeout=5, verify=False, transport=transport, auth=auth) as http:
            r = http.request(o["method"], url)
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"The device answered HTTP {r.status_code}.")
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"No answer from the output's device ({exc.__class__.__name__}).") from exc


# ------------------------------------------------------------------ what is on, and the timers that switch it off

class Active:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[int, dict] = {}              # output id -> {until, alert_id, by, timer}

    def start(self, o: dict, alert_id: str | None, by: str, off_fn) -> None:
        with self.lock:
            cur = self.items.pop(o["id"], None)
            if cur and cur.get("timer"):
                cur["timer"].cancel()
            timer = None
            if o["duration_s"]:
                timer = threading.Timer(o["duration_s"], self._expire, args=(o["id"], off_fn))
                timer.daemon = True
                timer.start()
            alerts = set(cur["alerts"]) if cur else set()
            if alert_id:
                alerts.add(alert_id)
            self.items[o["id"]] = {"since": time.time(), "until": time.time() + o["duration_s"] if o["duration_s"] else None,
                                   "alerts": alerts, "by": by, "timer": timer, "name": o["name"]}

    def _expire(self, oid: int, off_fn) -> None:
        with self.lock:
            self.items.pop(oid, None)
        try:
            off_fn()
        except Exception as exc:
            log.warning("output %s: switching off failed: %s", oid, exc)

    def stop(self, oid: int) -> dict | None:
        with self.lock:
            cur = self.items.pop(oid, None)
        if cur and cur.get("timer"):
            cur["timer"].cancel()
        return cur

    def for_alert(self, alert_id: str) -> list[int]:
        with self.lock:
            return [oid for oid, v in self.items.items() if alert_id in v["alerts"]]

    def snapshot(self) -> dict[int, dict]:
        with self.lock:
            return {oid: {k: (sorted(v) if k == "alerts" else v) for k, v in item.items() if k != "timer"} for oid, item in self.items.items()}


active = Active()


def turn_on(o: dict, alert_id: str | None, by: str) -> None:
    switch(o, True)
    active.start(o, alert_id, by, lambda: switch(o, False))


def turn_off(o: dict) -> None:
    active.stop(o["id"])
    switch(o, False)


def run_rule_outputs(names: list[str], alert_id: str) -> list[str]:
    """Switch on outputs for a new alert (runs in a thread); returns what happened, for the timeline."""
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
            turn_on(o, alert_id, "alert rule")
            done.append(f"{o['name']} on" + (f" for {o['duration_s']} s" if o["duration_s"] else ""))
        except HTTPException as exc:
            done.append(f"{o['name']} failed: {exc.detail}")
    return done


def silence_alert(alert_id: str) -> list[str]:
    """Switch off the outputs an alert started (on acknowledge or close)."""
    out = []
    for oid in active.for_alert(alert_id):
        try:
            o = _get(oid)
            turn_off(o)
            out.append(o["name"])
        except Exception as exc:
            log.warning("silencing output %s: %s", oid, exc)
    return out


# ------------------------------------------------------------------ endpoints

class OutputIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(pattern=r"^(nvr_relay|http)$")
    nvr_alias: str | None = Field(default=None, max_length=20)
    port: int | None = Field(default=None, ge=1, le=64)
    url_on: str | None = Field(default=None, max_length=500)
    url_off: str | None = Field(default=None, max_length=500)
    method: str = Field(default="GET", pattern=r"^(GET|POST|PUT)$")
    username: str = Field(default="", max_length=64)
    password: str = Field(default="", max_length=128)        # blank on edit = keep
    duration_s: int = Field(default=60, ge=0, le=3600)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if "," in v:
            raise ValueError("names can't contain commas (rules list outputs separated by commas)")
        return v.strip()

    @field_validator("url_on", "url_off")
    @classmethod
    def _url(cls, v):
        if v and not re.match(r"^https?://[^\s]+$", v.strip()):
            raise ValueError("addresses start with http:// or https://")
        return v.strip() if v else v


def _check(body: OutputIn) -> None:
    if body.kind == "nvr_relay":
        if not body.nvr_alias or not body.port:
            raise HTTPException(status_code=422, detail="Choose the NVR and the alarm output number.")
        with connect() as conn:
            if not conn.execute("SELECT 1 FROM nvrs WHERE alias = %s", (body.nvr_alias,)).fetchone():
                raise HTTPException(status_code=422, detail="That NVR is not in Devices.")
    elif not body.url_on:
        raise HTTPException(status_code=422, detail="Give the address that switches the device on.")


def _public(o: dict) -> dict:
    a = active.snapshot().get(o["id"])
    return {k: v for k, v in o.items() if k != "secret"} | {"has_password": bool(o["secret"]), "on": bool(a),
                                                            "on_until": a["until"] if a else None, "on_by": a["by"] if a else None}


@router.get("")
def list_outputs(_: dict = Depends(require(*OPERATORS))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(f"SELECT {COLS} FROM outputs ORDER BY name").fetchall()
    return [_public(_row(r)) for r in rows]


@router.post("", status_code=201)
def add_output(body: OutputIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    _check(body)
    with connect() as conn:
        if conn.execute("SELECT 1 FROM outputs WHERE lower(name) = lower(%s)", (body.name,)).fetchone():
            raise HTTPException(status_code=409, detail=f"An output called {body.name} exists already.")
        oid = conn.execute("INSERT INTO outputs (name, kind, nvr_alias, port, url_on, url_off, method, username, secret, duration_s, enabled) "
                           "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                           (body.name, body.kind, body.nvr_alias, body.port, body.url_on, body.url_off, body.method, body.username,
                            vault.encrypt(body.password) if body.password else "", body.duration_s, body.enabled)).fetchone()[0]
    audit("output_added", user_id=user["id"], username=user["username"], ip=client_ip(request), output=body.name, kind=body.kind)
    return _public(_get(oid))


@router.put("/{oid}")
def edit_output(oid: int, body: OutputIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    old = _get(oid)
    _check(body)
    with connect() as conn:
        conn.execute("UPDATE outputs SET name = %s, kind = %s, nvr_alias = %s, port = %s, url_on = %s, url_off = %s, method = %s, "
                     "username = %s, secret = %s, duration_s = %s, enabled = %s WHERE id = %s",
                     (body.name, body.kind, body.nvr_alias, body.port, body.url_on, body.url_off, body.method, body.username,
                      vault.encrypt(body.password) if body.password else old["secret"], body.duration_s, body.enabled, oid))
    audit("output_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), output=body.name)
    return _public(_get(oid))


@router.delete("/{oid}")
def delete_output(oid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    o = _get(oid)
    if active.snapshot().get(oid):
        try:
            turn_off(o)
        except HTTPException:
            pass
    with connect() as conn:
        conn.execute("DELETE FROM outputs WHERE id = %s", (oid,))
    audit("output_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), output=o["name"])
    return {"deleted": o["name"]}


class SwitchIn(BaseModel):
    on: bool
    seconds: int | None = Field(default=None, ge=1, le=3600)     # a manual 'on' for this long (default: the output's duration)


@router.post("/{oid}/switch")
def manual_switch(oid: int, body: SwitchIn, request: Request, user: dict = Depends(require(*OPERATORS))) -> dict:
    o = _get(oid)
    if body.on:
        if not o["enabled"]:
            raise HTTPException(status_code=409, detail=f"{o['name']} is paused.")
        turn_on({**o, "duration_s": body.seconds or o["duration_s"]}, None, user["username"])
    else:
        turn_off(o)
    audit("output_switched", user_id=user["id"], username=user["username"], ip=client_ip(request), output=o["name"],
          state="on" if body.on else "off", **({"seconds": body.seconds} if body.on and body.seconds else {}))
    return _public(_get(oid))


@router.post("/{oid}/test")
def test_output(oid: int, request: Request, user: dict = Depends(require(*MANAGERS))) -> dict:
    """On for 3 seconds, then off."""
    o = _get(oid)
    turn_on({**o, "duration_s": 3}, None, f"test by {user['username']}")
    audit("output_tested", user_id=user["id"], username=user["username"], ip=client_ip(request), output=o["name"])
    return {"tested": o["name"], "seconds": 3}


@router.post("/nvr/{alias}/ports")
def nvr_ports(alias: str, _: dict = Depends(require("admin"))) -> dict:
    """The alarm outputs an NVR has, to pick from when adding a relay."""
    import xml.etree.ElementTree as ET
    with connect() as conn:
        n = conn.execute("SELECT address, username, secret, scheme FROM nvrs WHERE alias = %s", (alias,)).fetchone()
    if not n:
        raise HTTPException(status_code=404, detail="That NVR is not in Devices.")
    try:
        with httpx.Client(base_url=f"{n[3]}://{n[0]}", auth=httpx.DigestAuth(n[1], vault.decrypt(n[2])), timeout=8, verify=False) as http:
            r = http.get("/ISAPI/System/IO/outputs")
            r.raise_for_status()
        root = ET.fromstring(r.text)
        ids = sorted({int(el.text) for el in root.iter() if el.tag.endswith("id") and el.text and el.text.strip().isdigit()})
    except (httpx.HTTPError, ET.ParseError) as exc:
        raise HTTPException(status_code=502, detail=f"Couldn't read the NVR's alarm outputs ({exc.__class__.__name__}).") from exc
    return {"ports": ids}
