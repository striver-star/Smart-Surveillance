"""Recorded video playback (release 2.0, first batch).

The recordings stay on the NVRs. To play one, the API asks the stream gateway (MediaMTX) for a
temporary path with a random name whose source is the NVR's RTSP playback address from the chosen time
(/Streaming/tracks/<ch>01?starttime=..., in the NVR's local time written with a Z). The console plays that
path over WebRTC exactly like live view. A jump to another time is a new session. Sessions the console
stops pinging are removed after 3 minutes.

The timeline for a day comes from the NVR's recording search (which spans were recorded) and from the
events and alerts HSS stored for that camera. Every playback is written to the audit log.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from . import vault
from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.playback")
router = APIRouter(prefix="/playback", tags=["playback"])
WATCHERS = ("admin", "cso", "operator")
IDLE_S = 180
CAMERA = re.compile(r"^([a-z][a-z0-9]{1,19})-ch(\d{2,3})$")


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))


def nvr_time(t: datetime, zone: ZoneInfo) -> str:
    """Hikvision playback time: the NVR's local time, written with a Z (pure, tested)."""
    return t.astimezone(zone).strftime("%Y%m%dT%H%M%SZ")


def playback_source(host: str, port: int, user: str, password: str, channel: int, start: datetime, zone: ZoneInfo) -> str:
    return (f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
            f"/Streaming/tracks/{channel}01?starttime={nvr_time(start, zone)}")


def day_search_body(channel: int, day: date, zone: ZoneInfo, position: int, search_id: str) -> str:
    start = datetime.combine(day, datetime.min.time(), zone)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    f = lambda t: t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731  (local time with a Z, as the NVR expects)
    return (f"<?xml version='1.0' encoding='UTF-8'?><CMSearchDescription><searchID>{search_id}</searchID>"
            f"<trackList><trackID>{channel}01</trackID></trackList><timeSpanList><timeSpan>"
            f"<startTime>{f(start)}</startTime><endTime>{f(end)}</endTime></timeSpan></timeSpanList>"
            f"<maxResults>100</maxResults><searchResultPostion>{position}</searchResultPostion>"
            "<metadataList><metadataDescriptor>//recordType.meta.std-cgi.com</metadataDescriptor></metadataList>"
            "</CMSearchDescription>")


def _strip(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def parse_spans(xml_text: str, zone: ZoneInfo) -> tuple[list[tuple[datetime, datetime]], bool]:
    """Recorded spans from a CMSearchResult, and whether more results follow (pure, tested). The NVR
    writes local time with a Z, so the Z is read as the NVR's own time zone."""
    root = _strip(ET.fromstring(xml_text))
    spans = []
    for item in root.iter("searchMatchItem"):
        s, e = item.findtext("timeSpan/startTime"), item.findtext("timeSpan/endTime")
        if not s or not e:
            continue
        try:
            a = datetime.fromisoformat(s.strip().rstrip("Z")).replace(tzinfo=zone)
            b = datetime.fromisoformat(e.strip().rstrip("Z")).replace(tzinfo=zone)
        except ValueError:
            continue
        if b > a:
            spans.append((a, b))
    more = (root.findtext("responseStatusStrg") or "").strip().upper() == "MORE"
    return spans, more


def merge_spans(spans: list[tuple[datetime, datetime]], gap_s: int = 5) -> list[tuple[datetime, datetime]]:
    """Join spans that touch or overlap (pure, tested): NVRs return a file per segment."""
    out: list[tuple[datetime, datetime]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1] + timedelta(seconds=gap_s):
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _nvr(camera_id: str) -> dict:
    m = CAMERA.match(camera_id)
    if not m:
        raise HTTPException(status_code=422, detail="camera id looks like nvr4-ch22")
    with connect() as conn:
        r = conn.execute("SELECT address, username, secret, scheme, rtsp_port FROM nvrs WHERE alias = %s", (m.group(1),)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Playback works for cameras on NVRs added in Devices.")
    address, user, secret, scheme, port = r
    return {"address": address, "host": address.rsplit(":", 1)[0] if address.count(":") == 1 else address, "user": user,
            "password": vault.decrypt(secret), "scheme": scheme, "rtsp_port": port, "channel": int(m.group(2))}


# ------------------------------------------------------------------ sessions in the gateway

class Sessions:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[str, dict] = {}

    def add(self, sid: str, info: dict) -> None:
        with self.lock:
            self.items[sid] = {**info, "touched": time.monotonic()}

    def touch(self, sid: str) -> bool:
        with self.lock:
            if sid in self.items:
                self.items[sid]["touched"] = time.monotonic()
                return True
            return False

    def pop(self, sid: str) -> dict | None:
        with self.lock:
            return self.items.pop(sid, None)

    def idle(self, now: float | None = None) -> list[str]:
        now = now if now is not None else time.monotonic()
        with self.lock:
            return [s for s, v in self.items.items() if now - v["touched"] > IDLE_S]


sessions = Sessions()


def _gateway() -> httpx.Client:
    return httpx.Client(base_url=os.environ.get("HSS_GATEWAY_API", "http://gateway:9997"), timeout=5)


def _remove_path(path: str) -> None:
    try:
        with _gateway() as gw:
            gw.delete(f"/v3/config/paths/delete/{path}")
    except httpx.HTTPError as exc:
        log.warning("removing playback path %s: %s", path, exc)


class StartIn(BaseModel):
    camera_id: str
    start: datetime


@router.post("/sessions")
def start(body: StartIn, request: Request, user: dict = Depends(require(*WATCHERS))) -> dict:
    if body.start.tzinfo is None:
        raise HTTPException(status_code=422, detail="start needs a time zone")
    if body.start > datetime.now(timezone.utc) - timedelta(seconds=5):
        raise HTTPException(status_code=422, detail="That time hasn't been recorded yet; use Live view.")
    n = _nvr(body.camera_id)
    path = f"pb-{secrets.token_hex(8)}"
    source = playback_source(n["host"], n["rtsp_port"], n["user"], n["password"], n["channel"], body.start, tz())
    try:
        with _gateway() as gw:
            r = gw.post(f"/v3/config/paths/add/{path}", json={"source": source, "sourceOnDemand": True, "rtspTransport": "tcp",
                                                               "sourceOnDemandCloseAfter": "10s"})
            r.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"The stream gateway didn't accept the playback ({exc.__class__.__name__}).") from exc
    sid = str(uuid.uuid4())
    sessions.add(sid, {"path": path, "camera_id": body.camera_id, "user": user["username"], "start": body.start})
    from .viewing import log_playback
    log_playback(user, body.camera_id, body.start, client_ip(request))
    audit("playback", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=body.camera_id,
          start=body.start.astimezone(tz()).strftime("%Y-%m-%d %H:%M:%S"))
    return {"session": sid, "path": path, "start": body.start, "keepalive_s": 30}


@router.post("/sessions/{sid}/keepalive")
def keepalive(sid: str, _: dict = Depends(require(*WATCHERS))) -> dict:
    if not sessions.touch(sid):
        raise HTTPException(status_code=404, detail="playback ended")
    return {"ok": True}


@router.delete("/sessions/{sid}")
def stop(sid: str, _: dict = Depends(require(*WATCHERS))) -> dict:
    s = sessions.pop(sid)
    if s:
        _remove_path(s["path"])
    return {"stopped": bool(s)}


def sweep() -> int:
    """Remove idle sessions, and playback paths left over from before a restart."""
    n = 0
    for sid in sessions.idle():
        s = sessions.pop(sid)
        if s:
            _remove_path(s["path"])
            n += 1
    try:
        with _gateway() as gw:
            names = [i["name"] for i in gw.get("/v3/config/paths/list", params={"itemsPerPage": 1000}).json().get("items", [])]
        live = {v["path"] for v in sessions.items.values()}
        for name in names:
            if name.startswith("pb-") and name not in live:
                _remove_path(name)
                n += 1
    except (httpx.HTTPError, ValueError):
        pass
    return n


async def background_loop() -> None:
    while True:
        await asyncio.sleep(60)
        try:
            await asyncio.to_thread(sweep)
        except Exception as exc:
            log.warning("playback sweep: %s", exc)


# ------------------------------------------------------------------ the day's timeline

@router.get("/timeline")
def timeline(camera_id: str, day: date, user: dict = Depends(require(*WATCHERS))) -> dict:
    zone = tz()
    n = _nvr(camera_id)
    spans, note = [], ""
    try:
        with httpx.Client(base_url=f"{n['scheme']}://{n['address']}", auth=httpx.DigestAuth(n["user"], n["password"]),
                          timeout=15, verify=False) as http:
            pos = 0
            for _ in range(20):                       # at most 2,000 segments a day
                r = http.post("/ISAPI/ContentMgmt/search", content=day_search_body(n["channel"], day, zone, pos, str(uuid.uuid4()).upper()),
                              headers={"Content-Type": "application/xml"})
                r.raise_for_status()
                found, more = parse_spans(r.text, zone)
                spans += found
                if not more or not found:
                    break
                pos += len(found)
    except (httpx.HTTPError, ET.ParseError) as exc:
        note = f"The NVR's recording list couldn't be read ({exc.__class__.__name__}); events are still shown."
    day_start = datetime.combine(day, datetime.min.time(), zone)
    with connect() as conn:
        rows = conn.execute(
            "SELECT e.id, e.type, e.severity, e.occurred_at, e.zone, a.id, a.status FROM events e LEFT JOIN alerts a ON a.event_id = e.id "
            "WHERE e.camera_id = %s AND e.occurred_at >= %s AND e.occurred_at < %s ORDER BY e.occurred_at LIMIT 2000",
            (camera_id, day_start, day_start + timedelta(days=1))).fetchall()
    return {"camera_id": camera_id, "day": str(day), "timezone": str(zone), "note": note,
            "recorded": [{"start": a, "end": b} for a, b in merge_spans(spans)],
            "events": [{"id": str(i), "type": t, "severity": s, "at": at, "zone": z, "alert_id": str(aid) if aid else None,
                        "alert_status": st} for i, t, s, at, z, aid, st in rows]}
