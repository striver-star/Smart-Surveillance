"""PTZ control: pan, tilt, zoom and presets for PTZ cameras behind the NVRs.

Commands go to the NVR's PTZ proxy over ISAPI (/ISAPI/ContentMgmt/PTZCtrlProxy/channels/<ch>/...), with
the NVR's stored login, so the NVR user needs the "Remote PTZ Control" right. Only NVRs added in the
console (Devices) can be controlled.

Safety and fairness:
- A move only lasts while the operator holds the button: the console repeats it every half second and
  the API stops the camera by itself if no repeat arrives within 1.5 s (a closed browser or a dropped
  network never leaves a camera spinning).
- One person steers a camera at a time. Someone else's move is refused for 30 s after the last
  command, except for the CSO and administrators, who can always take over.
- Alert rules can send PTZ cameras to presets when they fire ("nvr4-ch05:3" = preset 3 on that camera).
"""
from __future__ import annotations

import logging
import re
import threading
import time
import xml.etree.ElementTree as ET

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from . import vault
from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.ptz")
router = APIRouter(prefix="/ptz", tags=["ptz"])
OPERATORS = ("admin", "cso", "operator")
OVERRIDE = ("admin", "cso")
HOLD_S = 30            # control stays with the last person for this long
DEADMAN_S = 1.5        # a move stops unless repeated within this time
CAMERA = re.compile(r"^([a-z][a-z0-9]{1,19})-ch(\d{2,3})$")


def _strip(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def continuous_xml(pan: int, tilt: int, zoom: int) -> str:
    return f"<?xml version='1.0' encoding='UTF-8'?><PTZData><pan>{pan}</pan><tilt>{tilt}</tilt><zoom>{zoom}</zoom></PTZData>"


def preset_xml(pid: int, name: str) -> str:
    safe = re.sub(r"[<>&\"']", "", name)[:32] or f"Preset {pid}"
    return f"<?xml version='1.0' encoding='UTF-8'?><PTZPreset><id>{pid}</id><presetName>{safe}</presetName></PTZPreset>"


def parse_presets(xml_text: str) -> list[dict]:
    """Named presets from a PTZPresetList (pure, tested). Unnamed slots and disabled ones are left out."""
    out = []
    for p in _strip(ET.fromstring(xml_text)).iter("PTZPreset"):
        pid = (p.findtext("id") or "").strip()
        name = (p.findtext("presetName") or "").strip()
        enabled = (p.findtext("enabled") or "true").strip().lower() != "false"
        if pid.isdigit() and enabled and name and not re.fullmatch(r"preset\s*\d+", name, re.I):
            out.append({"id": int(pid), "name": name})
    return sorted(out, key=lambda p: p["id"])


def supports_ptz(capabilities_xml: str) -> bool:
    """Whether a PTZ capabilities answer describes real pan/tilt or zoom (pure, tested). Hikvision spells
    the root PTZChanelCap; fixed cameras answer with an error or without the movement spaces."""
    t = capabilities_xml
    return ("PTZChanelCap" in t or "PTZChannelCap" in t) and any(
        k in t for k in ("ContinuousPanTiltSpace", "ContinuousZoomSpace", "AbsolutePanTiltPositionSpace"))


def parse_target(spec: str) -> tuple[str, int] | None:
    """'nvr4-ch05:3' -> ('nvr4-ch05', 3) (pure, tested)."""
    m = re.fullmatch(r"([a-z][a-z0-9]{1,19}-ch\d{2,3}):(\d{1,3})", spec.strip())
    return (m.group(1), int(m.group(2))) if m else None


class Device:
    """One camera's PTZ, reached through its NVR."""

    def __init__(self, camera_id: str, transport: httpx.BaseTransport | None = None):
        m = CAMERA.match(camera_id)
        if not m:
            raise HTTPException(status_code=422, detail="camera id looks like nvr4-ch05")
        with connect() as conn:
            r = conn.execute("SELECT address, username, secret, scheme FROM nvrs WHERE alias = %s AND enabled", (m.group(1),)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="PTZ works for cameras on NVRs added in Devices.")
        self.camera_id, self.channel = camera_id, int(m.group(2))
        self.http = httpx.Client(base_url=f"{r[3]}://{r[0]}", auth=httpx.DigestAuth(r[1], vault.decrypt(r[2])),
                                 timeout=5, verify=False, transport=transport)
        self.base = f"/ISAPI/ContentMgmt/PTZCtrlProxy/channels/{self.channel}"

    def _call(self, method: str, path: str, body: str | None = None) -> httpx.Response:
        try:
            r = self.http.request(method, self.base + path, content=body, headers={"Content-Type": "application/xml"} if body else None)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"The NVR didn't answer ({exc.__class__.__name__}).") from exc
        if r.status_code in (401, 403):
            raise HTTPException(status_code=502, detail="The NVR refused PTZ control: give the HSS user on the NVR the 'Remote PTZ Control' right.")
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"The NVR refused the command (HTTP {r.status_code}); the camera may not be PTZ.")
        return r

    def supported(self) -> bool:
        try:
            r = self.http.get(self.base + "/capabilities")
        except httpx.HTTPError:
            return False
        return r.status_code == 200 and supports_ptz(r.text)

    def move(self, pan: int, tilt: int, zoom: int) -> None:
        self._call("PUT", "/continuous", continuous_xml(pan, tilt, zoom))

    def stop(self) -> None:
        self._call("PUT", "/continuous", continuous_xml(0, 0, 0))

    def presets(self) -> list[dict]:
        try:
            return parse_presets(self._call("GET", "/presets").text)
        except (HTTPException, ET.ParseError):
            return []

    def goto(self, pid: int) -> None:
        self._call("PUT", f"/presets/{pid}/goto")

    def save_preset(self, pid: int, name: str) -> None:
        self._call("PUT", f"/presets/{pid}", preset_xml(pid, name))


# ------------------------------------------------------------------ who steers, and the dead-man stop

class Control:
    """In-memory: who holds each camera, and the stop timer for moves in progress."""

    def __init__(self):
        self.lock = threading.Lock()
        self.holder: dict[str, tuple[str, float]] = {}        # camera -> (username, last command time)
        self.timers: dict[str, threading.Timer] = {}
        self.audited: dict[tuple[str, str], float] = {}

    def claim(self, camera: str, user: dict, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        with self.lock:
            who, at = self.holder.get(camera, ("", 0.0))
            if who and who != user["username"] and now - at < HOLD_S and user["role"] not in OVERRIDE:
                raise HTTPException(status_code=409, detail=f"{who} is steering this camera; try again in {int(HOLD_S - (now - at)) + 1} s.")
            self.holder[camera] = (user["username"], now)

    def arm_stop(self, camera: str, stop_fn) -> None:
        with self.lock:
            old = self.timers.pop(camera, None)
            if old:
                old.cancel()
            t = threading.Timer(DEADMAN_S, self._fire, args=(camera, stop_fn))
            t.daemon = True
            self.timers[camera] = t
            t.start()

    def disarm(self, camera: str) -> None:
        with self.lock:
            t = self.timers.pop(camera, None)
        if t:
            t.cancel()

    def _fire(self, camera: str, stop_fn) -> None:
        with self.lock:
            self.timers.pop(camera, None)
        try:
            stop_fn()
            log.info("%s: no repeat from the console; stopped", camera)
        except Exception as exc:
            log.warning("%s: automatic stop failed: %s", camera, exc)

    def should_audit(self, user: str, camera: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        key = (user, camera)
        if now - self.audited.get(key, -1e9) > 300:
            self.audited[key] = now
            return True
        return False


control = Control()


# ------------------------------------------------------------------ endpoints

@router.get("/{camera_id}")
def info(camera_id: str, user: dict = Depends(require(*OPERATORS))) -> dict:
    d = Device(camera_id)
    if not d.supported():
        return {"camera_id": camera_id, "supported": False, "presets": []}
    who, at = control.holder.get(camera_id, ("", 0.0))
    busy = who if who and who != user["username"] and time.monotonic() - at < HOLD_S else None
    return {"camera_id": camera_id, "supported": True, "presets": d.presets(), "held_by": busy,
            "can_save_presets": user["role"] in OVERRIDE}


class MoveIn(BaseModel):
    pan: int = Field(default=0, ge=-100, le=100)
    tilt: int = Field(default=0, ge=-100, le=100)
    zoom: int = Field(default=0, ge=-100, le=100)


@router.post("/{camera_id}/move")
def move(camera_id: str, body: MoveIn, request: Request, user: dict = Depends(require(*OPERATORS))) -> dict:
    d = Device(camera_id)
    control.claim(camera_id, user)
    d.move(body.pan, body.tilt, body.zoom)
    control.arm_stop(camera_id, d.stop)
    if control.should_audit(user["username"], camera_id):
        audit("ptz_control", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=camera_id)
    return {"moving": True, "stops_in_s": DEADMAN_S}


@router.post("/{camera_id}/stop")
def stop(camera_id: str, user: dict = Depends(require(*OPERATORS))) -> dict:
    d = Device(camera_id)
    control.disarm(camera_id)
    d.stop()
    return {"moving": False}


@router.post("/{camera_id}/presets/{pid}/goto")
def goto(camera_id: str, pid: int, request: Request, user: dict = Depends(require(*OPERATORS))) -> dict:
    if not 1 <= pid <= 300:
        raise HTTPException(status_code=422, detail="preset numbers run from 1 to 300")
    d = Device(camera_id)
    control.claim(camera_id, user)
    d.goto(pid)
    audit("ptz_preset", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=camera_id, preset=pid)
    return {"preset": pid}


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=32)


@router.put("/{camera_id}/presets/{pid}")
def save_preset(camera_id: str, pid: int, body: PresetIn, request: Request, user: dict = Depends(require(*OVERRIDE))) -> dict:
    if not 1 <= pid <= 300:
        raise HTTPException(status_code=422, detail="preset numbers run from 1 to 300")
    d = Device(camera_id)
    d.save_preset(pid, body.name)
    audit("ptz_preset_saved", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=camera_id,
          preset=pid, name=body.name)
    return {"preset": pid, "name": body.name, "presets": d.presets()}


# ------------------------------------------------------------------ alert rules: PTZ to a preset

def run_rule_presets(targets: list[str], alert_id: str) -> list[str]:
    """Send PTZ cameras to presets when a rule fires. Runs in a thread; returns what was done for the timeline."""
    done = []
    for spec in targets:
        t = parse_target(spec)
        if not t:
            continue
        cam, pid = t
        try:
            Device(cam).goto(pid)
            with control.lock:
                control.holder[cam] = ("alert rule", time.monotonic())
            done.append(f"{cam} to preset {pid}")
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
            done.append(f"{cam} to preset {pid} failed: {detail}")
            log.warning("alert %s: PTZ %s preset %s failed: %s", alert_id, cam, pid, detail)
    return done
