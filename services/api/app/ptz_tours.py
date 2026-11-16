"""PTZ patrol tours (release 2.0): HSS takes a PTZ camera round its presets, waiting a set time at each, all day or
only in set hours and on set days (e.g. the fence line every night from 18:00 to 06:00).

HSS runs the tour itself (not the camera's own patrol function) so that it can give way:
- An operator who steers the camera, or sends it to a preset, has it: the tour waits until nobody has touched it
  for HSS_PTZ_RESUME_S (default 120 s), then carries on from the next preset.
- An alert rule that turns the camera to a preset holds it for HSS_PTZ_ALERT_HOLD_S (default 300 s).
- Operators can pause a tour (5 minutes to 4 hours) and resume it; the CSO and administrators set tours up.
A camera has at most one tour in force at any time (tours on one camera can't overlap in their hours).
Every change, pause and resume is audited. Tours only use presets saved on the camera (PTZ panel › Save view).
"""
from __future__ import annotations

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, time as dtime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.ptz.tours")
router = APIRouter(prefix="/ptz-tours", tags=["ptz"])
OPERATORS = ("admin", "cso", "operator")
MANAGE = ("admin", "cso")
TICK_S = 1
TOUR = "tour:"               # how a tour shows as the camera's holder (ptz.control)
COLS = "id, camera_id, name, steps, days, start_local, end_local, enabled, paused_until, paused_by, created_by, updated_at"


def resume_s() -> int:
    return int(os.environ.get("HSS_PTZ_RESUME_S", "120"))


def alert_hold_s() -> int:
    return int(os.environ.get("HSS_PTZ_ALERT_HOLD_S", "300"))


# ------------------------------------------------------------------ pure helpers (tested)

def in_window(days: list[int], start: dtime | None, end: dtime | None, local: datetime) -> bool:
    """Whether a tour is in force at this local time. No times = all day on its days; start after end = overnight,
    counted as the day it started (Friday 18:00-06:00 runs into Saturday morning)."""
    wd, t = local.isoweekday(), local.time()
    if start is None or end is None or start == end:
        return wd in days
    if start < end:
        return wd in days and start <= t < end
    yesterday = (local - timedelta(days=1)).isoweekday()
    return (wd in days and t >= start) or (yesterday in days and t < end)


def overlaps(a: dict, b: dict) -> bool:
    """Whether two tours are ever in force at the same time (checked minute by minute over a week)."""
    monday = datetime(2026, 1, 5)                  # a Monday
    for m in range(0, 7 * 24 * 60, 1):
        t = monday + timedelta(minutes=m)
        if in_window(a["days"], a["start_local"], a["end_local"], t) and in_window(b["days"], b["start_local"], b["end_local"], t):
            return True
    return False


def held_by_other(holder: tuple[str, float] | None, now: float, resume: int, alert_hold: int) -> str | None:
    """Who has the camera, if not a tour and recently enough that the tour must wait (pure, tested)."""
    if not holder:
        return None
    who, at = holder
    if not who or who.startswith(TOUR):
        return None
    wait = alert_hold if who == "alert rule" else resume
    return who if now - at < wait else None


def next_step(step: int, n: int) -> int:
    return 0 if step < 0 else (step + 1) % n


# ------------------------------------------------------------------ the runner

class Runner:
    """In memory: where each tour is (step, when the next move is due) and what it's doing, for the console."""

    def __init__(self):
        self.lock = threading.Lock()
        self.state: dict[int, dict] = {}

    def status(self, tid: int) -> dict:
        with self.lock:
            return dict(self.state.get(tid, {"status": "starting"}))

    def _set(self, tid: int, **kw) -> dict:
        with self.lock:
            st = self.state.setdefault(tid, {"step": -1, "due": 0.0, "fails": 0, "status": "starting", "error": ""})
            st.update(kw)
            return st

    def tick(self, tours: list[dict], now_utc: datetime | None = None, now: float | None = None, goto=None) -> None:
        from .alerts import tz
        from .ptz import Device, control
        now_utc = now_utc or datetime.now(timezone.utc)
        now = now if now is not None else time.monotonic()
        local = now_utc.astimezone(tz())
        goto = goto or (lambda cam, pid: Device(cam).goto(pid))
        live = set()
        for t in tours:
            tid, cam, steps = t["id"], t["camera_id"], t["steps"]
            live.add(tid)
            st = self._set(tid)
            if not t["enabled"]:
                self._set(tid, status="off", step=-1, due=0.0)
                continue
            if not in_window(t["days"], t["start_local"], t["end_local"], local):
                self._set(tid, status="outside its hours", step=-1, due=0.0)
                continue
            if t["paused_until"] and t["paused_until"] > now_utc:
                self._set(tid, status=f"paused by {t['paused_by']}", due=0.0)
                continue
            who = held_by_other(control.holder.get(cam), now, resume_s(), alert_hold_s())
            if who:
                self._set(tid, status=f"waiting: {who} has the camera", due=0.0)
                continue
            if now < st["due"]:
                continue
            step = next_step(st["step"], len(steps))
            s = steps[step]
            try:
                goto(cam, s["preset"])
                with control.lock:
                    control.holder[cam] = (TOUR + t["name"], now)
                self._set(tid, step=step, due=now + s["dwell_s"], fails=0, error="", status="running", at_preset=s["preset"])
            except Exception as exc:
                err = getattr(exc, "detail", None) or str(exc) or exc.__class__.__name__
                fails = st["fails"] + 1
                self._set(tid, step=step, due=now + min(60, 10 * fails), fails=fails, error=str(err)[:200], status="can't reach the camera")
                if fails in (1, 10):
                    log.warning("tour %s (%s): preset %s failed: %s", t["name"], cam, s["preset"], err)
        with self.lock:
            for tid in list(self.state):
                if tid not in live:
                    del self.state[tid]


runner = Runner()


def _row(r) -> dict:
    return dict(zip([c.strip() for c in COLS.split(",")], r))


def _tours(camera_id: str | None = None) -> list[dict]:
    with connect() as conn:
        sql = f"SELECT {COLS} FROM ptz_tours" + (" WHERE camera_id = %s" if camera_id else "") + " ORDER BY camera_id, id"
        return [_row(r) for r in conn.execute(sql, (camera_id,) if camera_id else ()).fetchall()]


def tick_once() -> None:
    runner.tick(_tours())


async def background_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(tick_once)
        except Exception as exc:
            log.warning("patrol tours: %s", exc)
        await asyncio.sleep(TICK_S)


# ------------------------------------------------------------------ endpoints

def _public(t: dict) -> dict:
    st = runner.status(t["id"])
    step = st.get("step", -1)
    return {**{k: v for k, v in t.items()}, "start_local": t["start_local"].strftime("%H:%M") if t["start_local"] else None,
            "end_local": t["end_local"].strftime("%H:%M") if t["end_local"] else None,
            "status": st.get("status"), "step": step + 1 if step >= 0 else None, "at_preset": st.get("at_preset") if step >= 0 else None,
            "error": st.get("error", "")}


class Step(BaseModel):
    preset: int = Field(ge=1, le=300)
    dwell_s: int = Field(ge=10, le=3600)


class TourIn(BaseModel):
    camera_id: str = Field(pattern=r"^[a-z][a-z0-9]{1,19}-ch\d{2,3}$")
    name: str = Field(min_length=2, max_length=40)
    steps: list[Step] = Field(min_length=2, max_length=32)
    days: list[int] = Field(default=[1, 2, 3, 4, 5, 6, 7], min_length=1, max_length=7)
    start_local: dtime | None = None
    end_local: dtime | None = None
    enabled: bool = True

    @field_validator("days")
    @classmethod
    def _days(cls, v: list[int]) -> list[int]:
        if any(d not in range(1, 8) for d in v):
            raise ValueError("days are 1 (Monday) to 7 (Sunday)")
        return sorted(set(v))


def _check(body: TourIn, tid: int | None) -> None:
    if (body.start_local is None) != (body.end_local is None):
        raise HTTPException(status_code=422, detail="Give both a start and an end time, or neither (all day).")
    try:                                           # presets must be saved on the camera (skipped if it can't be reached now)
        from .ptz import Device
        saved = {p["id"] for p in Device(body.camera_id).presets()}
    except HTTPException:
        saved = set()
    missing = sorted({s.preset for s in body.steps} - saved) if saved else []
    if missing:
        raise HTTPException(status_code=422, detail=f"Preset {', '.join(map(str, missing))} isn't saved on this camera (PTZ panel › Save view).")
    if body.enabled:
        me = body.model_dump()
        for other in _tours(body.camera_id):
            if other["id"] != tid and other["enabled"] and overlaps(me, other):
                raise HTTPException(status_code=409, detail=f"\"{other['name']}\" already patrols this camera at some of these times.")


@router.get("")
def list_tours(camera_id: str | None = None, user: dict = Depends(require(*OPERATORS))) -> dict:
    from .access import allowed
    return {"tours": [_public(t) for t in _tours(camera_id) if allowed(user, t["camera_id"])], "can_manage": user["role"] in MANAGE,
            "resume_s": resume_s()}


@router.post("", status_code=201)
def create(body: TourIn, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    from .access import check
    check(user, body.camera_id)
    _check(body, None)
    with connect() as conn:
        r = conn.execute(f"INSERT INTO ptz_tours (camera_id, name, steps, days, start_local, end_local, enabled, created_by) "
                         f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLS}",
                         (body.camera_id, body.name, Jsonb([s.model_dump() for s in body.steps]), body.days, body.start_local, body.end_local,
                          body.enabled, user["username"])).fetchone()
    audit("ptz_tour_added", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=body.camera_id, tour=body.name,
          presets=[s.preset for s in body.steps])
    return _public(_row(r))


@router.put("/{tid}")
def change(tid: int, body: TourIn, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    from .access import check
    check(user, body.camera_id)
    _check(body, tid)
    with connect() as conn:
        r = conn.execute(f"UPDATE ptz_tours SET camera_id = %s, name = %s, steps = %s, days = %s, start_local = %s, end_local = %s, enabled = %s, "
                         f"updated_at = now() WHERE id = %s RETURNING {COLS}",
                         (body.camera_id, body.name, Jsonb([s.model_dump() for s in body.steps]), body.days, body.start_local, body.end_local,
                          body.enabled, tid)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such tour")
    runner._set(tid, step=-1, due=0.0)
    audit("ptz_tour_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=body.camera_id, tour=body.name,
          enabled=body.enabled)
    return _public(_row(r))


@router.delete("/{tid}")
def delete(tid: int, request: Request, user: dict = Depends(require(*MANAGE))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM ptz_tours WHERE id = %s RETURNING camera_id, name", (tid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such tour")
    audit("ptz_tour_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=r[0], tour=r[1])
    return {"deleted": True}


class PauseIn(BaseModel):
    minutes: int = Field(ge=5, le=240)
    reason: str = Field(default="", max_length=200)


def _get(tid: int, user: dict) -> dict:
    from .access import check
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS} FROM ptz_tours WHERE id = %s", (tid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such tour")
    t = _row(r)
    check(user, t["camera_id"])
    return t


@router.post("/{tid}/pause")
def pause(tid: int, body: PauseIn, request: Request, user: dict = Depends(require(*OPERATORS))) -> dict:
    t = _get(tid, user)
    until = datetime.now(timezone.utc) + timedelta(minutes=body.minutes)
    with connect() as conn:
        conn.execute("UPDATE ptz_tours SET paused_until = %s, paused_by = %s WHERE id = %s", (until, user["username"], tid))
    audit("ptz_tour_paused", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=t["camera_id"], tour=t["name"],
          minutes=body.minutes, reason=body.reason)
    return {"paused_until": until}


@router.post("/{tid}/resume")
def resume(tid: int, request: Request, user: dict = Depends(require(*OPERATORS))) -> dict:
    t = _get(tid, user)
    with connect() as conn:
        conn.execute("UPDATE ptz_tours SET paused_until = NULL, paused_by = '' WHERE id = %s", (tid,))
    runner._set(tid, due=0.0)
    audit("ptz_tour_resumed", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=t["camera_id"], tour=t["name"])
    return {"resumed": True}
