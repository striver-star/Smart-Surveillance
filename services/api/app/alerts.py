"""Alerts and incident workflow (Section 5.5, Phase 3 part A).

An event becomes an alert when it matches an alert rule. Rules are checked in order; the first
match decides the severity, the channels (screen, sound, push, whatsapp) and the escalation time.
A cooldown folds repeat events at the same camera and zone into the open alert, so one person
walking along a fence doesn't raise ten alerts.

Workflow: open -> acknowledged -> closed (with a reason), reopen possible; assign and comment at
any time. Every step goes on the alert's timeline and in the audit log. Unacknowledged alerts whose
rule sets an escalation time are escalated to the recipients subscribed to "escalation" (WhatsApp,
e-mail fallback, push), up to three times.

The console gets new alerts and changes live over Server-Sent Events (GET /alerts/stream).
"""
from __future__ import annotations

import asyncio
import fnmatch
import hashlib
import io
import json
import logging
import os
import threading
import uuid
import zipfile
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response, StreamingResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("alerts")
router = APIRouter(prefix="/alerts", tags=["alerts"])
WATCHERS = ("admin", "cso", "operator")
SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}
CHANNELS = ("screen", "sound", "push", "whatsapp")
MAX_ESCALATIONS = 3
CLOSE_REASONS = ("real_incident", "false_alarm", "test", "duplicate", "other")

DEVICE_TYPES = ["nvr_offline", "camera_offline", "drive_fault"]
DEFAULT_RULES = [
    {"name": "Device faults", "enabled": True, "min_severity": "warning", "cameras": [], "zones": [], "types": DEVICE_TYPES,
     "objects": [], "armed": [], "raise_to": None, "channels": ["screen", "push", "whatsapp"], "escalate_after_min": None,
     "cooldown_s": 0, "notify_topic": "device"},
    {"name": "Critical events", "enabled": True, "min_severity": "critical", "cameras": [], "zones": [], "types": [],
     "objects": [], "armed": [], "raise_to": None, "channels": ["screen", "sound", "push", "whatsapp"],
     "escalate_after_min": 10, "cooldown_s": 120, "notify_topic": "critical"},
    {"name": "Warnings", "enabled": True, "min_severity": "warning", "cameras": [], "zones": [], "types": [],
     "objects": [], "armed": [], "raise_to": None, "channels": ["screen", "sound"], "escalate_after_min": None,
     "cooldown_s": 120, "notify_topic": "critical"},
]


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))


# ------------------------------------------------------------------ live updates (Server-Sent Events)

class Broker:
    """In-process fan-out to connected consoles. The API runs one worker process, so this is enough;
    a second process would switch to PostgreSQL LISTEN/NOTIFY."""
    def __init__(self):
        self.queues: set[asyncio.Queue] = set()
        self.loop: asyncio.AbstractEventLoop | None = None

    def publish(self, message: dict) -> None:
        if not self.loop:
            return
        data = json.dumps(message, default=str)
        for q in list(self.queues):
            self.loop.call_soon_threadsafe(q.put_nowait, data)


broker = Broker()


# ------------------------------------------------------------------ rules

class Rule(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    enabled: bool = True
    min_severity: str = Field(default="warning", pattern="^(info|warning|critical)$")
    cameras: list[str] = Field(default_factory=list)        # patterns, e.g. "nvr4-*"
    zones: list[str] = Field(default_factory=list)          # patterns, e.g. "*fence*"
    types: list[str] = Field(default_factory=list)
    objects: list[str] = Field(default_factory=list)
    armed: list[tuple[str, str]] = Field(default_factory=list)   # [["18:00", "06:00"]]; empty = always
    raise_to: str | None = Field(default=None, pattern="^(warning|critical)$")
    channels: list[str] = Field(default_factory=lambda: ["screen", "sound"])
    escalate_after_min: int | None = Field(default=None, ge=1, le=1440)
    cooldown_s: int = Field(default=120, ge=0, le=86400)
    notify_topic: str = Field(default="critical", pattern="^(critical|device|system)$")   # who gets WhatsApp and push
    ptz_presets: list[str] = Field(default_factory=list, max_length=8)   # PTZ cameras to turn: ["nvr4-ch05:3"]
    outputs: list[str] = Field(default_factory=list, max_length=8)       # sirens, lights, relays to switch on (by name)


def load_rules() -> list[dict]:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'alert_rules'").fetchone()
        if not row:
            return DEFAULT_RULES
        rules = row[0]
        # Rules saved before device health existed: add the "Device faults" rule once, at the top,
        # so device problems reach the IT Manager rather than the security alerts. Never re-added
        # if someone removes it later.
        if not conn.execute("SELECT 1 FROM settings WHERE key = 'alert_rules_device_added'").fetchone():
            if not any(set(r.get("types", [])) & set(DEVICE_TYPES) for r in rules):
                rules = [DEFAULT_RULES[0]] + rules
                conn.execute("UPDATE settings SET value = %s WHERE key = 'alert_rules'", (Jsonb(rules),))
            conn.execute("INSERT INTO settings (key, value) VALUES ('alert_rules_device_added', 'true') ON CONFLICT DO NOTHING")
        return rules


def _any(patterns: list[str], value: str | None) -> bool:
    return not patterns or any(fnmatch.fnmatch((value or "").lower(), p.lower()) for p in patterns)


def armed_now(windows: list, at: datetime) -> bool:
    if not windows:
        return True
    t = at.time()
    for start, end in windows:
        s, e = time.fromisoformat(start), time.fromisoformat(end)
        if (s <= t < e) if s <= e else (t >= s or t < e):      # e.g. 18:00 to 06:00 crosses midnight
            return True
    return False


def match_rule(rules: list[dict], event: dict, at_local: datetime) -> dict | None:
    for r in rules:
        if not r.get("enabled", True):
            continue
        if SEVERITY_RANK[event["severity"]] < SEVERITY_RANK[r.get("min_severity", "warning")]:
            continue
        if not (_any(r.get("cameras", []), event["camera_id"]) and _any(r.get("zones", []), event.get("zone"))
                and _any(r.get("types", []), event["type"]) and _any(r.get("objects", []), event.get("object_class"))):
            continue
        if not armed_now(r.get("armed", []), at_local):
            continue
        return r
    return None


# ------------------------------------------------------------------ raising alerts

ALERT_COLS = ("a.id, a.event_id, a.rule, a.severity, a.status, a.assigned_to, a.acknowledged_by, a.acknowledged_at, "
              "a.closed_by, a.closed_at, a.close_reason, a.escalation_level, a.channels, a.created_at, "
              "e.camera_id, e.zone, e.type, e.object_class, e.confidence, e.occurred_at, e.snapshot_ref, e.tier, e.source_kind")


_names_cache: dict = {"at": 0.0, "names": {}}


def camera_label(camera_id: str) -> str | None:
    """Camera name from the probe and live device data (cached for a minute)."""
    import time as _t
    if _t.monotonic() - _names_cache["at"] > 60:
        try:
            from .console import load_devices
            from .reports.data import camera_names
            names = camera_names(load_devices())
            with connect() as conn:          # guards and vehicles (Phase 5) and patrol checkpoints
                names |= {f"unit-{i}": n for i, n in conn.execute("SELECT id, name FROM tracked_units").fetchall()}
                names |= {f"checkpoint-{i}": n for i, n in conn.execute("SELECT id, name FROM zones").fetchall()}
            _names_cache["names"] = names
        except Exception:
            _names_cache["names"] = {}
        _names_cache["at"] = _t.monotonic()
    return _names_cache["names"].get(camera_id)


def _alert_row(r) -> dict:
    keys = [c.split(".")[1] for c in ALERT_COLS.replace(" ", "").split(",")]
    a = dict(zip(keys, r))
    a["camera_name"] = camera_label(a["camera_id"])
    a["id"], a["event_id"] = str(a["id"]), str(a["event_id"])
    a["snapshot_url"] = f"/api/events/{a['event_id']}/snapshot" if a.pop("snapshot_ref") else None
    return a


def get_alert(alert_id) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {ALERT_COLS} FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.id = %s",
                         (alert_id,)).fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="no such alert")
        a = _alert_row(r)
        a["repeats"] = conn.execute("SELECT count(*) FROM alert_timeline WHERE alert_id = %s AND kind = 'repeat'",
                                    (alert_id,)).fetchone()[0]
    return a


def add_timeline(conn, alert_id, kind: str, text: str = "", username: str | None = None) -> None:
    conn.execute("INSERT INTO alert_timeline (alert_id, username, kind, text) VALUES (%s, %s, %s, %s)",
                 (alert_id, username, kind, text))


def on_event(event: dict) -> str | None:
    """Called after an event is stored. Returns the new alert id, or None."""
    at_local = event["occurred_at"].astimezone(tz())
    rule = match_rule(load_rules(), event, at_local)
    if rule is None:
        return None
    severity = rule.get("raise_to") or event["severity"]
    if SEVERITY_RANK[severity] < SEVERITY_RANK[event["severity"]]:
        severity = event["severity"]
    with connect() as conn:
        if rule.get("cooldown_s"):
            existing = conn.execute(
                "SELECT a.id FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.status <> 'closed' AND a.rule = %s "
                "AND e.camera_id = %s AND coalesce(e.zone, '') = coalesce(%s, '') AND a.created_at > now() - %s * interval '1 second' "
                "ORDER BY a.created_at DESC LIMIT 1",
                (rule["name"], event["camera_id"], event.get("zone"), rule["cooldown_s"])).fetchone()
            if existing:
                add_timeline(conn, existing[0], "repeat",
                             f"Repeat {event['type'].replace('_', ' ')} at {at_local:%H:%M:%S}"
                             + (f" ({event['object_class']}, {round(100 * event['confidence'])}%)" if event.get("confidence") else ""))
                conn.commit()
                broker.publish({"kind": "updated", "alert": get_alert(existing[0])})
                return None
        alert_id = conn.execute(
            "INSERT INTO alerts (event_id, rule, severity, escalate_after_s, channels) VALUES (%s, %s, %s, %s, %s) "
            "ON CONFLICT (event_id) DO NOTHING RETURNING id",
            (event["id"], rule["name"], severity,
             rule["escalate_after_min"] * 60 if rule.get("escalate_after_min") else None,
             Jsonb(rule.get("channels", ["screen"])))).fetchone()
        if not alert_id:
            return None
        alert_id = alert_id[0]
        add_timeline(conn, alert_id, "raised", f"Raised by rule '{rule['name']}'")
    alert = get_alert(alert_id)
    broker.publish({"kind": "new", "alert": alert})
    if rule.get("ptz_presets"):
        threading.Thread(target=_ptz_for_alert, args=(rule["ptz_presets"], alert_id), daemon=True).start()
    if rule.get("outputs"):
        threading.Thread(target=_outputs_for_alert, args=(rule["outputs"], alert_id), daemon=True).start()
    channels = set(rule.get("channels", []))
    if channels & {"push", "whatsapp"}:
        threading.Thread(target=_notify, args=(alert, channels, rule.get("notify_topic") or "critical"), daemon=True).start()
    if severity == "critical" and event["type"] not in DEVICE_TYPES:
        from .clips import request_clip
        try:
            if request_clip(alert_id, event["id"], event["camera_id"], event["occurred_at"], "rule"):
                broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
        except Exception:
            log.exception("requesting a clip for alert %s failed", alert_id)
    return str(alert_id)


def _outputs_for_alert(names: list[str], alert_id) -> None:
    try:
        from .outputs import run_rule_outputs
        done = run_rule_outputs(names, str(alert_id))
        if done:
            with connect() as conn:
                add_timeline(conn, alert_id, "outputs", "Switched on: " + "; ".join(done))
            broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
    except Exception:
        log.exception("outputs for alert %s failed", alert_id)


def _ptz_for_alert(targets: list[str], alert_id) -> None:
    try:
        from .ptz import run_rule_presets
        done = run_rule_presets(targets, str(alert_id))
        if done:
            with connect() as conn:
                add_timeline(conn, alert_id, "ptz", "PTZ: " + "; ".join(done))
            broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
    except Exception:
        log.exception("PTZ presets for alert %s failed", alert_id)


def _alert_text(a: dict, prefix: str = "") -> tuple[str, str]:
    when = a["occurred_at"].astimezone(tz())
    title = f"{prefix}{a['severity'].upper()}: {a['type'].replace('_', ' ')} at {a['zone'] or a.get('camera_name') or a['camera_id']}"
    body = (f"{when:%a %d %b %H:%M:%S} · camera {a['camera_id']}"
            + (f" · {a['object_class']}" if a.get("object_class") else "")
            + (f" · {round(100 * a['confidence'])}%" if a.get("confidence") else "")
            + "\nOpen the console to acknowledge.")
    return title, body


def _snapshot_attachment(a: dict):
    from .notify import Attachment
    with connect() as conn:
        ref = conn.execute("SELECT snapshot_ref FROM events WHERE id = %s", (a["event_id"],)).fetchone()
    if not ref or not ref[0]:
        return None
    path = Path(os.environ.get("HSS_DATA_DIR", "/data")) / ref[0]
    return Attachment(f"alert-{a['id'][:8]}.jpg", "image/jpeg", path.read_bytes()) if path.exists() else None


def _notify(alert: dict, channels: set[str], topic: str, prefix: str = "", kind: str = "notified") -> None:
    """WhatsApp (with e-mail fallback) to the topic's subscribers, and push. Runs in a thread."""
    try:
        from .notify import PushSender, dispatch, load_recipients, record, senders
        wa, email, push = senders()
        title, body = _alert_text(alert, prefix)
        attempts = []
        if "whatsapp" in channels:
            attempts += dispatch(topic, title, body, _snapshot_attachment(alert), load_recipients(), wa, email,
                                 push if "push" in channels else PushSender("", ""))
        elif "push" in channels and push.configured:
            attempts.append(push.publish(title, body, "high" if alert["severity"] == "critical" else "default"))
        record(topic, attempts)
        ok = sum(a.status == "sent" for a in attempts)
        with connect() as conn:
            add_timeline(conn, alert["id"], kind, f"{ok} of {len(attempts)} messages delivered ({topic})"
                         if attempts else f"No recipients or channels configured for '{topic}'")
        broker.publish({"kind": "updated", "alert": get_alert(alert["id"])})
    except Exception:  # notification problems must never break alerting
        log.exception("notifying alert %s failed", alert.get("id"))


# ------------------------------------------------------------------ escalation

def escalate_once(now: datetime | None = None) -> list[str]:
    with connect() as conn:
        due = conn.execute(
            "SELECT id FROM alerts WHERE status = 'open' AND escalate_after_s IS NOT NULL AND escalation_level < %s "
            "AND coalesce(last_escalated_at, created_at) + escalate_after_s * interval '1 second' <= coalesce(%s, now())",
            (MAX_ESCALATIONS, now)).fetchall()
        for (alert_id,) in due:
            conn.execute("UPDATE alerts SET escalation_level = escalation_level + 1, last_escalated_at = now() WHERE id = %s",
                         (alert_id,))
    out = []
    for (alert_id,) in due:
        a = get_alert(alert_id)
        with connect() as conn:
            add_timeline(conn, alert_id, "escalated", f"Not acknowledged in time: escalation {a['escalation_level']} of {MAX_ESCALATIONS}")
        broker.publish({"kind": "updated", "alert": get_alert(alert_id)})
        threading.Thread(target=_notify, args=(a, {"whatsapp", "push"}, "escalation", f"ESCALATED (level {a['escalation_level']}) ", "escalation_sent"),
                         daemon=True).start()
        out.append(str(alert_id))
    return out


async def background_loop() -> None:
    broker.loop = asyncio.get_running_loop()
    while True:
        try:
            await asyncio.to_thread(escalate_once)
        except Exception:
            log.exception("escalation check failed")
        await asyncio.sleep(30)


# ------------------------------------------------------------------ endpoints

@router.get("/stream")
async def stream(request: Request, _: dict = Depends(require(*WATCHERS))):
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    broker.loop = asyncio.get_running_loop()
    broker.queues.add(q)

    async def gen():
        try:
            yield "retry: 5000\n\n"
            while not await request.is_disconnected():
                try:
                    data = await asyncio.wait_for(q.get(), timeout=20)
                    yield f"event: alert\ndata: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            broker.queues.discard(q)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("")
def list_alerts(status: str | None = None, severity: str | None = None, limit: int = 100,
                _: dict = Depends(require(*WATCHERS, allow_admin_token=True))) -> dict:
    sql, params = f"SELECT {ALERT_COLS} FROM alerts a JOIN events e ON e.id = a.event_id WHERE true", []
    if status == "active":
        sql += " AND a.status <> 'closed'"
    elif status in ("open", "acknowledged", "closed"):
        sql += " AND a.status = %s"
        params.append(status)
    if severity in SEVERITY_RANK:
        sql += " AND a.severity = %s"
        params.append(severity)
    sql += " ORDER BY a.created_at DESC LIMIT %s"
    params.append(max(1, min(limit, 500)))
    with connect() as conn:
        rows = [_alert_row(r) for r in conn.execute(sql, params).fetchall()]
        counts = dict(conn.execute("SELECT status, count(*) FROM alerts GROUP BY status").fetchall())
    return {"alerts": rows, "counts": {"open": counts.get("open", 0), "acknowledged": counts.get("acknowledged", 0),
                                       "closed": counts.get("closed", 0)}}


@router.get("/assignees")
def assignees(_: dict = Depends(require(*WATCHERS))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT username, display_name, role FROM users WHERE NOT disabled AND role IN "
                            "('admin', 'cso', 'operator') ORDER BY lower(username)").fetchall()
    return [{"username": u, "display_name": d or u, "role": r} for u, d, r in rows]


@router.get("/rules")
def get_rules(_: dict = Depends(require(*WATCHERS, allow_admin_token=True))) -> list[dict]:
    return load_rules()


@router.put("/rules")
def put_rules(rules: list[Rule], request: Request, user: dict = Depends(require("admin", "cso", allow_admin_token=True))) -> list[dict]:
    data = [r.model_dump() for r in rules]
    for r in data:
        bad = set(r["channels"]) - set(CHANNELS)
        if bad:
            raise HTTPException(status_code=422, detail=f"unknown channel(s): {', '.join(sorted(bad))}")
        for w in r["armed"]:
            for t in w:
                try:
                    time.fromisoformat(t)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=f"armed time '{t}' must be HH:MM") from exc
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('alert_rules', %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(data),))
    audit("alert_rules_changed", user_id=user["id"], username=user["username"], ip=client_ip(request),
          rules=[r["name"] for r in data])
    return data


@router.get("/{alert_id}")
def alert_detail(alert_id: uuid.UUID, _: dict = Depends(require(*WATCHERS, allow_admin_token=True))) -> dict:
    a = get_alert(alert_id)
    with connect() as conn:
        a["timeline"] = [{"at": t, "username": u, "kind": k, "text": x} for t, u, k, x in conn.execute(
            "SELECT at, username, kind, text FROM alert_timeline WHERE alert_id = %s ORDER BY at, id", (alert_id,)).fetchall()]
    from .clips import clips_for
    a["clips"] = clips_for(alert_id)
    return a


class ActionIn(BaseModel):
    action: str = Field(pattern="^(acknowledge|assign|comment|close|reopen)$")
    text: str = Field(default="", max_length=2000)
    assignee: str | None = Field(default=None, max_length=80)
    reason: str | None = None


@router.post("/{alert_id}/action")
def alert_action(alert_id: uuid.UUID, body: ActionIn, request: Request, user: dict = Depends(require(*WATCHERS))) -> dict:
    a = get_alert(alert_id)
    who = user["username"]
    with connect() as conn:
        if body.action == "acknowledge":
            if a["status"] != "open":
                raise HTTPException(status_code=409, detail=f"This alert is already {a['status']}.")
            conn.execute("UPDATE alerts SET status = 'acknowledged', acknowledged_by = %s, acknowledged_at = now(), "
                         "assigned_to = coalesce(assigned_to, %s) WHERE id = %s", (who, who, alert_id))
            add_timeline(conn, alert_id, "acknowledged", body.text, who)
        elif body.action == "assign":
            if user["role"] == "operator" and body.assignee not in (None, who):
                raise HTTPException(status_code=403, detail="Operators can only take an alert themselves.")
            target = body.assignee or who
            if not conn.execute("SELECT 1 FROM users WHERE username = %s AND NOT disabled", (target,)).fetchone():
                raise HTTPException(status_code=422, detail="No such active user.")
            conn.execute("UPDATE alerts SET assigned_to = %s WHERE id = %s", (target, alert_id))
            add_timeline(conn, alert_id, "assigned", f"Assigned to {target}" + (f": {body.text}" if body.text else ""), who)
        elif body.action == "comment":
            if not body.text.strip():
                raise HTTPException(status_code=422, detail="Write a comment first.")
            add_timeline(conn, alert_id, "comment", body.text.strip(), who)
        elif body.action == "close":
            if body.reason not in CLOSE_REASONS:
                raise HTTPException(status_code=422, detail=f"Choose a reason: {', '.join(CLOSE_REASONS)}")
            if a["status"] == "closed":
                raise HTTPException(status_code=409, detail="This alert is already closed.")
            conn.execute("UPDATE alerts SET status = 'closed', closed_by = %s, closed_at = now(), close_reason = %s, "
                         "acknowledged_by = coalesce(acknowledged_by, %s), acknowledged_at = coalesce(acknowledged_at, now()) "
                         "WHERE id = %s", (who, body.reason, who, alert_id))
            add_timeline(conn, alert_id, "closed", body.reason.replace("_", " ") + (f": {body.text}" if body.text else ""), who)
        elif body.action == "reopen":
            if a["status"] != "closed":
                raise HTTPException(status_code=409, detail="Only closed alerts can be reopened.")
            conn.execute("UPDATE alerts SET status = 'acknowledged', closed_by = NULL, closed_at = NULL, close_reason = NULL "
                         "WHERE id = %s", (alert_id,))
            add_timeline(conn, alert_id, "reopened", body.text, who)
    if body.action == "close" and body.reason == "real_incident":
        try:                       # a real incident's evidence goes into the vault at once
            from .evidence import seal
            seal(alert_id, who, reason="Closed as a real incident" + (f": {body.text}" if body.text else ""), ip=client_ip(request))
        except Exception:
            logging.getLogger("alerts").exception("sealing evidence for alert %s failed", alert_id)
    if body.action in ("acknowledge", "close"):
        try:                       # acknowledging (or closing) silences the sirens and lights this alert started
            from .outputs import silence_alert
            silenced = silence_alert(str(alert_id))
            if silenced:
                with connect() as conn:
                    add_timeline(conn, alert_id, "outputs", "Silenced: " + ", ".join(silenced), who)
        except Exception:
            logging.getLogger("alerts").exception("silencing outputs for alert %s failed", alert_id)
    audit(f"alert_{body.action}", user_id=user["id"], username=who, ip=client_ip(request), alert=str(alert_id),
          **({"reason": body.reason} if body.reason else {}), **({"assignee": body.assignee} if body.assignee else {}))
    updated = get_alert(alert_id)
    broker.publish({"kind": "updated", "alert": updated})
    return alert_detail(alert_id)


@router.get("/{alert_id}/evidence")
def evidence(alert_id: uuid.UUID, request: Request, user: dict = Depends(require("admin", "cso"))) -> Response:
    """A one-off copy of the evidence zip (not kept). For evidence that must be kept and accounted for,
    seal it into the vault instead (POST /alerts/{id}/seal)."""
    from .evidence import build_package
    data, manifest, _ = build_package(alert_id, user["username"])
    digest = hashlib.sha256(data).hexdigest()
    with connect() as conn:
        add_timeline(conn, alert_id, "exported", f"Evidence copy exported, SHA-256 {digest}", user["username"])
    audit("evidence_exported", user_id=user["id"], username=user["username"], ip=client_ip(request),
          alert=str(alert_id), sha256=digest)
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="evidence-{str(alert_id)[:8]}-{manifest["packaged_at"][:10]}.zip"',
        "X-Evidence-SHA256": digest})
