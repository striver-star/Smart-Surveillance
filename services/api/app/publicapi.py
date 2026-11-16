"""The open API, version 1 (release 2.0, third batch): /api/v1/... for other systems (a PSIM, an access
control system, a ticketing tool, a client's own dashboard).

Authentication: an API key made by an administrator (console: API and webhooks), sent as
    Authorization: Bearer hss_<id>_<secret>
Each key has scopes and, optionally, a camera list (patterns, as for users) and an expiry date. Keys are
stored as a hash and shown once. Each key may make 300 requests a minute.

Scopes: events:read, alerts:read, alerts:write (acknowledge and close), cameras:read.
Face and plate matches are never returned. Machine-readable description: /api/v1/openapi.json; guide:
docs/api.md. This version's shapes stay stable; changes that break them will come as /api/v2.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

SCOPES = ("events:read", "alerts:read", "alerts:write", "cameras:read")
HIDDEN_TYPES = ("face_match", "plate_match")
RATE_PER_MIN = 300
KEY = re.compile(r"^hss_([a-z0-9]{12})_([A-Za-z0-9_-]{32,64})$")


def hash_secret(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


class Bucket:
    """Requests per key per minute (in memory; pure apart from the clock, tested)."""
    def __init__(self, per_min: int):
        self.per_min, self.lock, self.hits = per_min, threading.Lock(), {}

    def take(self, key: str, now: float | None = None) -> bool:
        now = now if now is not None else time.monotonic()
        with self.lock:
            window = [t for t in self.hits.get(key, []) if now - t < 60]
            if len(window) >= self.per_min:
                self.hits[key] = window
                return False
            window.append(now)
            self.hits[key] = window
            return True


bucket = Bucket(RATE_PER_MIN)


def api_key(request: Request, authorization: str | None = Header(default=None)) -> dict:
    m = KEY.match((authorization or "").removeprefix("Bearer ").strip())
    if not m:
        raise HTTPException(status_code=401, detail="send an API key: Authorization: Bearer hss_...", headers={"WWW-Authenticate": "Bearer"})
    kid, secret = m.groups()
    with connect() as conn:
        r = conn.execute("SELECT name, secret_hash, scopes, cameras, expires_at, revoked_at, last_used FROM api_keys WHERE id = %s", (kid,)).fetchone()
    if not r or not hmac.compare_digest(r[1], hash_secret(secret)) or r[5] is not None:
        raise HTTPException(status_code=401, detail="unknown or revoked API key")
    if r[4] and r[4] < date.today():
        raise HTTPException(status_code=401, detail="this API key has expired")
    if not bucket.take(kid):
        raise HTTPException(status_code=429, detail=f"more than {RATE_PER_MIN} requests a minute", headers={"Retry-After": "10"})
    if not r[6] or datetime.now(timezone.utc) - r[6] > timedelta(minutes=1):
        with connect() as conn:
            conn.execute("UPDATE api_keys SET last_used = now(), last_ip = %s WHERE id = %s", (client_ip(request), kid))
    # Shaped like a user, so the per-camera checks (access.py) apply unchanged.
    return {"id": None, "username": f"api:{r[0]}", "role": "api", "cameras": r[3] or [], "scopes": list(r[2]), "key_id": kid}


def scope(name: str):
    def dep(key: dict = Depends(api_key)) -> dict:
        if name not in key["scopes"]:
            raise HTTPException(status_code=403, detail=f"this key lacks the {name} scope")
        return key
    return dep


v1 = FastAPI(title="HSS open API", version="1", docs_url=None, redoc_url=None,
             description="Events, alerts and cameras of an HSS site. Authenticate with an API key: Authorization: Bearer hss_... "
                         "Webhooks push alerts as they happen; see docs/api.md.")


def _page(limit: int) -> int:
    return max(1, min(limit, 500))


@v1.get("/health")
def health() -> dict:
    return {"ok": True, "version": "1"}


@v1.get("/events", summary="Events, newest first")
def events(since: datetime | None = None, until: datetime | None = None, camera_id: str | None = None, type: str | None = None,
           before: str | None = None, limit: int = 100, key: dict = Depends(scope("events:read"))) -> dict:
    """Page with `before`: pass the `next_before` of the previous page."""
    from .access import sql as cam_sql
    sql = ("SELECT id, camera_id, type, severity, zone, object_class, confidence, occurred_at, received_at, snapshot_ref IS NOT NULL "
           "FROM events WHERE NOT (type = ANY(%s))")
    args: list = [list(HIDDEN_TYPES)]
    for cond, val in (("occurred_at >= %s", since), ("occurred_at < %s", until), ("camera_id = %s", camera_id), ("type = %s", type)):
        if val is not None:
            sql += f" AND {cond}"
            args.append(val)
    if before:
        try:
            t, i = before.split("|")
            sql += " AND (occurred_at, id) < (%s, %s)"
            args += [datetime.fromisoformat(t), uuid.UUID(i)]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="before must be a next_before value") from exc
    w, a = cam_sql(key, "camera_id")
    sql += w + " ORDER BY occurred_at DESC, id DESC LIMIT %s"
    args += a + [_page(limit)]
    with connect() as conn:
        rows = conn.execute(sql, args).fetchall()
    out = [{"id": str(i), "camera_id": c, "type": t, "severity": s, "zone": z, "object": o, "confidence": cf, "occurred_at": at, "received_at": rc,
            "snapshot": f"/api/v1/events/{i}/snapshot" if snap else None} for i, c, t, s, z, o, cf, at, rc, snap in rows]
    return {"events": out, "next_before": f"{rows[-1][7].isoformat()}|{rows[-1][0]}" if len(rows) == _page(limit) else None}


@v1.get("/events/{event_id}/snapshot", summary="An event's picture (JPEG)")
def snapshot(event_id: uuid.UUID, key: dict = Depends(scope("events:read"))):
    from .access import allowed
    from .events import snapshot_dir
    with connect() as conn:
        r = conn.execute("SELECT snapshot_ref, camera_id, type FROM events WHERE id = %s", (event_id,)).fetchone()
    if not r or not r[0] or r[2] in HIDDEN_TYPES or not allowed(key, r[1]):
        raise HTTPException(status_code=404, detail="no picture")
    p = (snapshot_dir().parent / r[0]).resolve()
    if not p.is_relative_to(snapshot_dir().resolve()) or not p.exists():
        raise HTTPException(status_code=404, detail="no picture")
    return FileResponse(p, media_type="image/jpeg")


def _alert(alert_id) -> dict:
    from .alerts import get_alert
    from .webhooks import alert_payload
    a = get_alert(alert_id)
    if a["type"] in HIDDEN_TYPES:
        raise HTTPException(status_code=404, detail="no such alert")
    return alert_payload(a)


@v1.get("/alerts", summary="Alerts, newest first")
def alerts(status: str | None = None, severity: str | None = None, since: datetime | None = None, limit: int = 100,
           key: dict = Depends(scope("alerts:read"))) -> dict:
    from .access import sql as cam_sql
    sql = "SELECT a.id FROM alerts a JOIN events e ON e.id = a.event_id WHERE NOT (e.type = ANY(%s))"
    args: list = [list(HIDDEN_TYPES)]
    if status in ("open", "acknowledged", "closed"):
        sql += " AND a.status = %s"
        args.append(status)
    elif status == "active":
        sql += " AND a.status <> 'closed'"
    if severity in ("info", "warning", "critical"):
        sql += " AND a.severity = %s"
        args.append(severity)
    if since:
        sql += " AND a.created_at >= %s"
        args.append(since)
    w, a = cam_sql(key, "e.camera_id")
    sql += w + " ORDER BY a.created_at DESC LIMIT %s"
    with connect() as conn:
        ids = [r[0] for r in conn.execute(sql, args + a + [_page(limit)]).fetchall()]
    return {"alerts": [_alert(i) for i in ids]}


@v1.get("/alerts/{alert_id}")
def alert(alert_id: uuid.UUID, key: dict = Depends(scope("alerts:read"))) -> dict:
    from .access import check
    a = _alert(alert_id)
    check(key, a["camera_id"])
    return a


class ActIn(BaseModel):
    note: str = Field(default="", max_length=1000)
    reason: str | None = Field(default=None, pattern="^(real_incident|false_alarm|test|duplicate|other)$")


@v1.post("/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: uuid.UUID, body: ActIn, key: dict = Depends(scope("alerts:write"))) -> dict:
    return _act(alert_id, "acknowledge", body, key)


@v1.post("/alerts/{alert_id}/close")
def close(alert_id: uuid.UUID, body: ActIn, key: dict = Depends(scope("alerts:write"))) -> dict:
    if not body.reason:
        raise HTTPException(status_code=422, detail="give a reason: real_incident, false_alarm, test, duplicate or other")
    return _act(alert_id, "close", body, key)


def _act(alert_id, action: str, body: ActIn, key: dict) -> dict:
    from .access import check
    from .alerts import add_timeline, broker, get_alert
    a = get_alert(alert_id)
    if a["type"] in HIDDEN_TYPES:
        raise HTTPException(status_code=404, detail="no such alert")
    check(key, a["camera_id"])
    who = key["username"]
    with connect() as conn:
        if action == "acknowledge":
            if a["status"] != "open":
                raise HTTPException(status_code=409, detail=f"This alert is already {a['status']}.")
            conn.execute("UPDATE alerts SET status = 'acknowledged', acknowledged_by = %s, acknowledged_at = now() WHERE id = %s", (who, alert_id))
            add_timeline(conn, alert_id, "acknowledged", body.note, who)
        else:
            if a["status"] == "closed":
                raise HTTPException(status_code=409, detail="This alert is already closed.")
            conn.execute("UPDATE alerts SET status = 'closed', close_reason = %s, closed_by = %s, closed_at = now() WHERE id = %s",
                         (body.reason, who, alert_id))
            add_timeline(conn, alert_id, "closed", body.note or f"Closed through the API ({body.reason})", who)
    audit(f"api_alert_{action}", username=who, alert=str(alert_id), key=key["key_id"])
    broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
    return _alert(alert_id)


@v1.get("/cameras")
def cameras(key: dict = Depends(scope("cameras:read"))) -> dict:
    from .access import allowed
    from .console import load_devices
    out = []
    for n in load_devices()["nvrs"]:
        for c in n["channels"]:
            if c.get("camera_id") and allowed(key, c["camera_id"]):
                out.append({"camera_id": c["camera_id"], "name": c.get("name"), "nvr": n.get("name"), "online": c.get("online"),
                            "model": c.get("model"), "recorded_days": c.get("recorded_days")})
    return {"cameras": out}


# ------------------------------------------------------------------ managing keys (console, administrators)

router = APIRouter(prefix="/api-keys", tags=["api keys"])


class KeyIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    scopes: list[str] = Field(min_length=1)
    cameras: list[str] = Field(default_factory=list, max_length=200)
    expires_at: date | None = None


@router.get("")
def list_keys(_: dict = Depends(require("admin"))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT id, name, scopes, cameras, created_by, created_at, expires_at, last_used, last_ip, revoked_at FROM api_keys "
                            "ORDER BY revoked_at IS NOT NULL, created_at DESC").fetchall()
    keys = ["id", "name", "scopes", "cameras", "created_by", "created_at", "expires_at", "last_used", "last_ip", "revoked_at"]
    return [dict(zip(keys, r)) for r in rows]


@router.post("", status_code=201)
def make_key(body: KeyIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    from .access import clean_patterns
    bad = [s for s in body.scopes if s not in SCOPES]
    if bad:
        raise HTTPException(status_code=422, detail=f"unknown scope(s): {', '.join(bad)}")
    if body.expires_at and body.expires_at <= date.today():
        raise HTTPException(status_code=422, detail="the expiry date must be in the future")
    kid = secrets.token_hex(6)
    secret = secrets.token_urlsafe(32)
    with connect() as conn:
        conn.execute("INSERT INTO api_keys (id, name, secret_hash, scopes, cameras, created_by, expires_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                     (kid, body.name, hash_secret(secret), sorted(set(body.scopes)), Jsonb(clean_patterns(body.cameras)), user["username"], body.expires_at))
    audit("api_key_created", user_id=user["id"], username=user["username"], ip=client_ip(request), key=kid, name=body.name, scopes=body.scopes,
          cameras=body.cameras or "all")
    return {"id": kid, "key": f"hss_{kid}_{secret}", "name": body.name}


@router.delete("/{kid}")
def revoke(kid: str, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        r = conn.execute("UPDATE api_keys SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING name", (kid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such active key")
    audit("api_key_revoked", user_id=user["id"], username=user["username"], ip=client_ip(request), key=kid, name=r[0])
    return {"revoked": True}
