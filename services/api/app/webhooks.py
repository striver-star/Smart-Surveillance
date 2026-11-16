"""Webhooks (release 2.0, third batch): push alerts and lockdowns to other systems.

Events: alert.created, alert.acknowledged, alert.closed, alert.reopened, lockdown.started, lockdown.ended,
and ping (the console's Test button). Each webhook chooses its events, a minimum severity and optionally a
camera list (patterns, as for users). Face and plate matches are never sent.

Every delivery is a JSON POST signed with the webhook's secret:
    X-HSS-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>">
    X-HSS-Event: alert.created      X-HSS-Delivery: <uuid, the same on every retry>
Receivers should check the signature, reject a t more than 5 minutes old, and treat X-HSS-Delivery as an
idempotency key. A delivery that doesn't get a 2xx answer is retried after 1, 5 and 30 minutes, then 2 and
6 hours (6 attempts over about 9 hours). After 50 failures in a row the webhook is paused.

URLs must be https, or http on the site's private network; the platform's own internal services (Docker
names without a dot, loopback, link-local) can't be targeted.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import ipaddress
import json
import logging
import queue
import secrets
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import vault
from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.webhooks")
router = APIRouter(prefix="/webhooks", tags=["webhooks"])
EVENTS = ("alert.created", "alert.acknowledged", "alert.closed", "alert.reopened", "lockdown.started", "lockdown.ended")
RETRY_MIN = (1, 5, 30, 120, 360)
PAUSE_AFTER = 50
SEV = {"info": 0, "warning": 1, "critical": 2}
HIDDEN_TYPES = ("face_match", "plate_match")


# ------------------------------------------------------------------ pure helpers (tested)

def sign(secret: str, body: bytes, t: int) -> str:
    return "t=%d,v1=%s" % (t, hmac.new(secret.encode(), str(t).encode() + b"." + body, hashlib.sha256).hexdigest())


def verify(secret: str, body: bytes, header: str, now: int, tolerance: int = 300) -> bool:
    """What a receiver does (pure, tested; the same code is in docs/api.md)."""
    try:
        parts = dict(p.split("=", 1) for p in header.split(","))
        t = int(parts["t"])
    except (ValueError, KeyError):
        return False
    return abs(now - t) <= tolerance and hmac.compare_digest(sign(secret, body, t), header)


def next_delay(attempts: int) -> timedelta | None:
    """After the n-th failed attempt, when to try again; None = give up (pure, tested)."""
    return timedelta(minutes=RETRY_MIN[attempts - 1]) if 1 <= attempts <= len(RETRY_MIN) else None


def wants(hook: dict, etype: str, severity: str | None, camera_id: str | None) -> bool:
    """Whether a webhook takes this event (pure, tested)."""
    if not hook["enabled"] or etype not in hook["events"]:
        return False
    if etype.startswith("alert.") and SEV.get(severity or "info", 0) < SEV.get(hook["min_severity"], 1):
        return False
    if etype.startswith("alert.") and hook.get("cameras"):
        from .access import allowed
        return allowed({"role": "api", "cameras": hook["cameras"]}, camera_id)
    return True


def check_url(url: str) -> str:
    u = urlparse(url.strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise HTTPException(status_code=422, detail="Give a full URL starting with https://")
    host = u.hostname
    if "." not in host and host != "localhost":
        raise HTTPException(status_code=422, detail="That looks like one of the platform's own services; give the receiver's real address.")
    try:
        addrs = {ipaddress.ip_address(a[4][0]) for a in socket.getaddrinfo(host, u.port or (443 if u.scheme == "https" else 80))}
    except socket.gaierror:
        addrs = set()                                # can't resolve now (e.g. outside DNS): checked again at delivery
    for a in addrs:
        if a.is_loopback or a.is_link_local or a.is_unspecified or a.is_multicast:
            raise HTTPException(status_code=422, detail="That address isn't allowed (loopback or link-local).")
        if u.scheme == "http" and not a.is_private:
            raise HTTPException(status_code=422, detail="Use https for receivers on the internet; plain http only on the site's network.")
    return url.strip()


def alert_payload(a: dict) -> dict:
    """The public shape of an alert (stable for integrators)."""
    return {"id": a["id"], "status": a["status"], "severity": a["severity"], "rule": a.get("rule"), "type": a["type"],
            "camera_id": a["camera_id"], "camera": a.get("camera_name") or a["camera_id"], "zone": a.get("zone"),
            "object": a.get("object_class"), "confidence": a.get("confidence"), "occurred_at": a["occurred_at"],
            "created_at": a.get("created_at"), "acknowledged_by": a.get("acknowledged_by"), "acknowledged_at": a.get("acknowledged_at"),
            "closed_at": a.get("closed_at"), "close_reason": a.get("close_reason"),
            "snapshot": f"/api/v1/events/{a['event_id']}/snapshot" if a.get("snapshot_url") else None}


# ------------------------------------------------------------------ from the alert broker to the delivery queue

_q: queue.Queue = queue.Queue(maxsize=5000)


def enqueue(message: dict) -> None:
    """Called by the alert broker for every message; never blocks alerting."""
    try:
        _q.put_nowait(message)
    except queue.Full:
        log.error("webhook queue full; a message was dropped")


def _hooks() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, events, min_severity, cameras, enabled FROM webhooks WHERE enabled").fetchall()
    return [{"id": i, "events": list(e), "min_severity": m, "cameras": c or [], "enabled": en} for i, e, m, c, en in rows]


def _translate(message: dict) -> tuple[str, dict, str | None, str | None] | None:
    kind = message.get("kind")
    if kind == "lockdown":
        lk = message.get("lockdown")
        return ("lockdown.started" if lk else "lockdown.ended"), {"lockdown": lk}, None, None
    a = message.get("alert")
    if kind not in ("new", "updated") or not a or a.get("type") in HIDDEN_TYPES:
        return None
    with connect() as conn:                        # announce each status once, also across restarts
        r = conn.execute("UPDATE alerts SET notified_status = status WHERE id = %s AND notified_status IS DISTINCT FROM status RETURNING status",
                         (a["id"],)).fetchone()
    if not r:
        return None
    etype = {"open": "alert.created" if kind == "new" else "alert.reopened", "acknowledged": "alert.acknowledged", "closed": "alert.closed"}[r[0]]
    return etype, {"alert": alert_payload(a)}, a["severity"], a["camera_id"]


def queue_event(etype: str, data: dict, severity: str | None, camera_id: str | None, only_hook: int | None = None) -> int:
    hooks = _hooks() if only_hook is None else [h for h in _hooks_all() if h["id"] == only_hook]
    n = 0
    for h in hooks:
        if only_hook is None and not wants(h, etype, severity, camera_id):
            continue
        eid = uuid.uuid4()
        payload = {"id": str(eid), "type": etype, "created_at": datetime.now(timezone.utc).isoformat(), "data": data}
        with connect() as conn:
            conn.execute("INSERT INTO webhook_deliveries (hook_id, event_id, type, payload) VALUES (%s, %s, %s, %s)",
                         (h["id"], eid, etype, Jsonb(json.loads(json.dumps(payload, default=str)))))
        n += 1
    return n


def _hooks_all() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, events, min_severity, cameras, enabled FROM webhooks").fetchall()
    return [{"id": i, "events": list(e), "min_severity": m, "cameras": c or [], "enabled": en} for i, e, m, c, en in rows]


def _translator() -> None:
    while True:
        message = _q.get()
        try:
            t = _translate(message)
            if t:
                queue_event(*t)
        except Exception:
            log.exception("webhook event not queued")


threading.Thread(target=_translator, name="webhook-translator", daemon=True).start()


# ------------------------------------------------------------------ delivering

def deliver_due(transport: httpx.BaseTransport | None = None, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    with connect() as conn:
        rows = conn.execute("SELECT d.id, d.event_id, d.type, d.payload, d.attempts, w.id, w.url, w.secret FROM webhook_deliveries d "
                            "JOIN webhooks w ON w.id = d.hook_id WHERE d.status = 'pending' AND d.next_at <= %s AND w.enabled "
                            "ORDER BY d.id LIMIT 50", (now,)).fetchall()
    done = 0
    for did, eid, etype, payload, attempts, hid, url, enc in rows:
        body = json.dumps(payload, separators=(",", ":")).encode()
        t = int(time.time())
        code, err = None, ""
        try:
            check_url(url)
            with httpx.Client(timeout=10, transport=transport, follow_redirects=False) as http:
                r = http.post(url, content=body, headers={"Content-Type": "application/json", "User-Agent": "HSS-Webhooks/1",
                                                          "X-HSS-Event": etype, "X-HSS-Delivery": str(eid),
                                                          "X-HSS-Signature": sign(vault.decrypt(enc), body, t)})
            code = r.status_code
            ok = 200 <= code < 300
            err = "" if ok else f"HTTP {code}"
        except (httpx.HTTPError, HTTPException) as exc:
            ok, err = False, getattr(exc, "detail", None) or exc.__class__.__name__
        attempts += 1
        with connect() as conn:
            if ok:
                conn.execute("UPDATE webhook_deliveries SET status = 'sent', attempts = %s, last_code = %s, last_error = '', sent_at = now() WHERE id = %s",
                             (attempts, code, did))
                conn.execute("UPDATE webhooks SET failures = 0 WHERE id = %s", (hid,))
            else:
                delay = next_delay(attempts)
                conn.execute("UPDATE webhook_deliveries SET status = %s, attempts = %s, last_code = %s, last_error = %s, next_at = %s WHERE id = %s",
                             ("pending" if delay else "failed", attempts, code, str(err)[:300], now + (delay or timedelta(0)), did))
                f = conn.execute("UPDATE webhooks SET failures = failures + 1 WHERE id = %s RETURNING failures", (hid,)).fetchone()[0]
                if f >= PAUSE_AFTER:
                    conn.execute("UPDATE webhooks SET enabled = false, paused_reason = %s WHERE id = %s",
                                 (f"Paused after {f} failed deliveries in a row (last: {err}).", hid))
        done += 1
    return done


async def background_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(deliver_due)
        except Exception as exc:
            log.warning("webhook delivery: %s", exc)
        await asyncio.sleep(5)


# ------------------------------------------------------------------ console endpoints (administrators)

class HookIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    url: str = Field(min_length=8, max_length=500)
    events: list[str] = Field(min_length=1)
    min_severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
    cameras: list[str] = Field(default_factory=list, max_length=200)
    enabled: bool = True


def _row(r) -> dict:
    keys = ["id", "name", "url", "events", "min_severity", "cameras", "enabled", "created_by", "created_at", "failures", "paused_reason"]
    return dict(zip(keys, r))


COLS = "id, name, url, events, min_severity, cameras, enabled, created_by, created_at, failures, paused_reason"


@router.get("")
def list_hooks(_: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        hooks = [_row(r) for r in conn.execute(f"SELECT {COLS} FROM webhooks ORDER BY name").fetchall()]
        rows = conn.execute("SELECT hook_id, status, count(*) FROM webhook_deliveries WHERE created_at > now() - interval '7 days' GROUP BY 1, 2").fetchall()
    for h in hooks:
        h["last_7_days"] = {s: n for hid, s, n in rows if hid == h["id"]}
    return {"hooks": hooks, "events": list(EVENTS)}


def _validate(body: HookIn) -> list[str]:
    bad = [e for e in body.events if e not in EVENTS]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown event(s): {', '.join(bad)}")
    from .access import clean_patterns
    return clean_patterns(body.cameras)


@router.post("", status_code=201)
def add_hook(body: HookIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    cams = _validate(body)
    url = check_url(body.url)
    secret = "whsec_" + secrets.token_urlsafe(24)
    with connect() as conn:
        r = conn.execute(f"INSERT INTO webhooks (name, url, secret, events, min_severity, cameras, enabled, created_by) "
                         f"VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING {COLS}",
                         (body.name, url, vault.encrypt(secret), body.events, body.min_severity, Jsonb(cams), body.enabled, user["username"])).fetchone()
    audit("webhook_added", user_id=user["id"], username=user["username"], ip=client_ip(request), name=body.name, url=urlparse(url).netloc, events=body.events)
    return {**_row(r), "secret": secret}


@router.put("/{hid}")
def edit_hook(hid: int, body: HookIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    cams = _validate(body)
    url = check_url(body.url)
    with connect() as conn:
        r = conn.execute(f"UPDATE webhooks SET name = %s, url = %s, events = %s, min_severity = %s, cameras = %s, enabled = %s, "
                         f"failures = CASE WHEN %s THEN 0 ELSE failures END, paused_reason = CASE WHEN %s THEN '' ELSE paused_reason END "
                         f"WHERE id = %s RETURNING {COLS}",
                         (body.name, url, body.events, body.min_severity, Jsonb(cams), body.enabled, body.enabled, body.enabled, hid)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such webhook")
    audit("webhook_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), name=body.name, url=urlparse(url).netloc,
          events=body.events, enabled=body.enabled)
    return _row(r)


@router.post("/{hid}/secret")
def new_secret(hid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    secret = "whsec_" + secrets.token_urlsafe(24)
    with connect() as conn:
        if not conn.execute("UPDATE webhooks SET secret = %s WHERE id = %s RETURNING id", (vault.encrypt(secret), hid)).fetchone():
            raise HTTPException(status_code=404, detail="no such webhook")
    audit("webhook_secret_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), webhook=hid)
    return {"secret": secret}


@router.delete("/{hid}")
def delete_hook(hid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM webhooks WHERE id = %s RETURNING name", (hid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such webhook")
    audit("webhook_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), name=r[0])
    return {"deleted": True}


@router.post("/{hid}/test")
def test_hook(hid: int, user: dict = Depends(require("admin"))) -> dict:
    n = queue_event("ping", {"message": "Test from HSS", "by": user["username"]}, None, None, only_hook=hid)
    if not n:
        raise HTTPException(status_code=404, detail="no such webhook")
    deliver_due()
    return recent(hid, user)


@router.get("/{hid}/deliveries")
def recent(hid: int, _: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        rows = conn.execute("SELECT id, event_id, type, status, attempts, last_code, last_error, created_at, sent_at, next_at FROM webhook_deliveries "
                            "WHERE hook_id = %s ORDER BY id DESC LIMIT 30", (hid,)).fetchall()
    keys = ["id", "event_id", "type", "status", "attempts", "last_code", "last_error", "created_at", "sent_at", "next_at"]
    return {"deliveries": [dict(zip(keys, r)) for r in rows]}


@router.post("/deliveries/{did}/retry")
def retry(did: int, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        r = conn.execute("UPDATE webhook_deliveries SET status = 'pending', next_at = now() WHERE id = %s AND status = 'failed' RETURNING hook_id",
                         (did,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no failed delivery with that number")
    deliver_due()
    return {"retried": True}
