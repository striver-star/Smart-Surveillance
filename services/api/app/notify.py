"""Notifications: WhatsApp (provider A gateway) first, e-mail fallback, push (ntfy) for alerts.

Recipients and what they receive are managed in the console (WhatsApp & alerts › Recipients) and kept in the
database. An existing /config/recipients.json is imported once, the first time the list is read; after that the
file is no longer used. The dedicated WhatsApp number is linked from the same page (QR code from the gateway).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import smtplib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .db import connect
from .auth import audit, client_ip, require

log = logging.getLogger("notify")
router = APIRouter(prefix="/notify")

PUSH_TOPICS = {"critical", "device", "system", "lockdown"}


@dataclass
class Recipient:
    name: str
    role: str = ""
    whatsapp: str = ""
    email: str = ""
    subscriptions: list[str] = field(default_factory=list)


@dataclass
class Attempt:
    channel: str
    status: str                 # sent | failed | skipped (duplicate number)
    recipient: str = ""
    address: str = ""
    detail: str = ""
    message_id: str = ""
    is_fallback: bool = False


@dataclass
class Attachment:
    filename: str
    mimetype: str
    data: bytes


def mask(address: str) -> str:
    if "@" in address:
        return "…@" + address.split("@", 1)[1]
    digits = "".join(c for c in address if c.isdigit())
    return "…" + digits[-4:] if digits else ""


TOPICS = {"daily", "weekly", "monthly", "test", "critical", "device", "system", "escalation", "lockdown", "compliance"}
_recipients_state: dict = {"good": None, "problem": "", "warnings": []}


def check_recipients(text: str) -> tuple[list[Recipient], list[str]]:
    """Parse and check recipients.json. Raises ValueError with a plain message (line and column)."""
    if not text.strip():
        raise ValueError("recipients.json is empty")
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        hint = " (often a missing comma between two items, or a comma after the last one)" if "delimiter" in exc.msg or "Expecting" in exc.msg else ""
        raise ValueError(f"recipients.json line {exc.lineno}, column {exc.colno}: {exc.msg}{hint}") from exc
    if not isinstance(raw, list):
        raise ValueError("recipients.json must be a list [ ... ] of recipients")
    out, warnings = [], []
    for i, r in enumerate(raw, 1):
        if not isinstance(r, dict) or not r.get("name"):
            raise ValueError(f"recipients.json entry {i}: each recipient needs at least a name")
        subs = r.get("subscriptions", [])
        if not isinstance(subs, list) or not all(isinstance(x, str) for x in subs):
            raise ValueError(f"recipients.json, {r['name']}: subscriptions must be a list of words in quotes")
        unknown = [x for x in subs if x not in TOPICS]
        if unknown:
            warnings.append(f"{r['name']}: unknown subscription(s) {', '.join(unknown)} (known: {', '.join(sorted(TOPICS))})")
        if r.get("whatsapp") and not str(r["whatsapp"]).startswith("+"):
            warnings.append(f"{r['name']}: WhatsApp number should start with + and the country code")
        out.append(Recipient(**{k: v for k, v in r.items() if k in Recipient.__dataclass_fields__}))
    return out, warnings


TOPIC_TEXT = {
    "critical": "Critical alerts (forced doors, SOS, duress, intrusion at night...)",
    "escalation": "Alerts nobody acknowledged in time",
    "lockdown": "Lockdown started and ended",
    "device": "NVR, camera, drive and access device faults",
    "system": "Server problems: backups, disk space, the WhatsApp link",
    "daily": "Daily report",
    "weekly": "Weekly report",
    "monthly": "Monthly report",
    "compliance": "Monthly compliance and privacy report",
    "test": "Delivery tests",
}
REC_COLS = "id, name, role, whatsapp, email, subscriptions, enabled, updated_by, updated_at"


def _rec_row(r) -> dict:
    return dict(zip([c.strip() for c in REC_COLS.split(",")], r))


def _import_file_once(conn) -> None:
    """The first time: copy config/recipients.json (if any) into the database, then never read it again."""
    if conn.execute("SELECT 1 FROM settings WHERE key = 'recipients_imported'").fetchone():
        return
    path = Path(os.environ.get("HSS_RECIPIENTS", "/config/recipients.json"))
    n = 0
    if not conn.execute("SELECT 1 FROM notify_recipients LIMIT 1").fetchone():
        try:
            recs, _ = check_recipients(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            try:
                recs, _ = check_recipients(_last_good_file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                recs = []
        for r in recs:
            conn.execute("INSERT INTO notify_recipients (name, role, whatsapp, email, subscriptions, updated_by) VALUES (%s, %s, %s, %s, %s, 'imported')",
                         (r.name, r.role, r.whatsapp, r.email, [t for t in r.subscriptions if t in TOPICS]))
            n += 1
    conn.execute("INSERT INTO settings (key, value) VALUES ('recipients_imported', %s) ON CONFLICT (key) DO NOTHING",
                 (Jsonb({"from": str(path), "count": n, "at": datetime.now(ZoneInfo("UTC")).isoformat()}),))
    if n:
        log.info("imported %d recipients from %s; manage them in the console from now on", n, path)


def recipient_rows() -> list[dict]:
    with connect() as conn:
        _import_file_once(conn)
        return [_rec_row(r) for r in conn.execute(f"SELECT {REC_COLS} FROM notify_recipients ORDER BY name").fetchall()]


def load_recipients(path: Path | None = None) -> list[Recipient]:
    """The recipients who receive messages: from the database (managed in the console), or from a file when a
    path is given (older set-ups and tests)."""
    if path is None:
        try:
            return [Recipient(r["name"], r["role"], r["whatsapp"], r["email"], list(r["subscriptions"]))
                    for r in recipient_rows() if r["enabled"]]
        except Exception as exc:                       # never let a database hiccup stop an alert silently
            log.error("recipients unavailable: %s", exc)
            return _recipients_state["good"] or []
    return _load_file(path)


def _load_file(path: Path) -> list[Recipient]:
    """The recipients from a file. If the file has a mistake, keep using the last good list (so a typo can't
    silently stop alerts) and remember the problem for the console's WhatsApp page."""
    try:
        recipients, warnings = check_recipients(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _recipients_state.update(problem="", warnings=[])
        return []
    except (ValueError, OSError) as exc:
        if _recipients_state["problem"] != str(exc):
            logging.getLogger("notify").error("%s; using the last good recipient list", exc)
        _recipients_state["problem"] = str(exc)
        if _recipients_state["good"] is None:          # after a restart: the copy saved on disk
            try:
                _recipients_state["good"], _ = check_recipients(_last_good_file().read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _recipients_state["good"] = []
        return _recipients_state["good"]
    if _recipients_state["good"] != recipients:
        try:
            _last_good_file().write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            pass
    _recipients_state.update(good=recipients, problem="", warnings=warnings)
    return recipients


def _last_good_file() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data")) / "recipients.last-good.json"


def recipients_problem() -> dict:
    return {"error": _recipients_state["problem"], "warnings": _recipients_state["warnings"],
            "using_last_good": bool(_recipients_state["problem"] and _recipients_state["good"])}


class WhatsAppSender:
    def __init__(self, url: str | None = None, token: str | None = None, transport=None):
        self.url = url if url is not None else os.environ.get("HSS_WA_URL", "")
        self.token = token if token is not None else os.environ.get("HSS_WA_TOKEN", "")
        self._http = httpx.Client(timeout=60, transport=transport,
                                  headers={"Authorization": f"Bearer {self.token}"})

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def status(self) -> dict:
        try:
            return self._http.get(f"{self.url}/status").json()
        except (httpx.HTTPError, ValueError) as exc:
            return {"status": "unreachable", "last_error": exc.__class__.__name__}

    def send(self, r: Recipient, text: str, attachment: Attachment | None) -> Attempt:
        body = {"to": r.whatsapp, "text": text}
        if attachment:
            body["document"] = {"filename": attachment.filename, "mimetype": attachment.mimetype,
                                "base64": base64.b64encode(attachment.data).decode()}
        try:
            resp = self._http.post(f"{self.url}/send", json=body)
            data = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            return Attempt("whatsapp", "failed", r.name, mask(r.whatsapp), f"gateway unreachable: {exc.__class__.__name__}")
        if resp.status_code == 200:
            return Attempt("whatsapp", "sent", r.name, mask(r.whatsapp), message_id=data.get("id", ""))
        return Attempt("whatsapp", "failed", r.name, mask(r.whatsapp), data.get("error", f"HTTP {resp.status_code}"))

    def call(self, method: str, path: str) -> dict:
        try:
            r = self._http.request(method, f"{self.url}{path}")
            return r.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise HTTPException(status_code=502, detail=f"The WhatsApp gateway didn't answer ({exc.__class__.__name__}). "
                                                        "Is it running? docker compose --profile notify up -d") from exc

    def ack(self, message_id: str) -> str | None:
        try:
            resp = self._http.get(f"{self.url}/messages/{message_id}")
            return resp.json().get("ack") if resp.status_code == 200 else None
        except (httpx.HTTPError, ValueError):
            return None


class EmailSender:
    def __init__(self, env: dict | None = None):
        e = env if env is not None else os.environ
        self.host = e.get("HSS_SMTP_HOST", "")
        self.port = int(e.get("HSS_SMTP_PORT", "587") or 587)
        self.user = e.get("HSS_SMTP_USER", "")
        self.password = e.get("HSS_SMTP_PASSWORD", "")
        self.sender = e.get("HSS_SMTP_FROM", "")
        self.starttls = e.get("HSS_SMTP_STARTTLS", "true").lower() != "false"

    @property
    def configured(self) -> bool:
        return bool(self.host and self.sender)

    def send(self, r: Recipient, subject: str, text: str, attachment: Attachment | None,
             is_fallback: bool) -> Attempt:
        msg = EmailMessage()
        msg["From"], msg["To"], msg["Subject"] = self.sender, r.email, subject
        msg.set_content(text)
        if attachment:
            maintype, _, subtype = attachment.mimetype.partition("/")
            msg.add_attachment(attachment.data, maintype=maintype, subtype=subtype or "octet-stream",
                               filename=attachment.filename)
        try:
            with smtplib.SMTP(self.host, self.port, timeout=30) as s:
                if self.starttls:
                    s.starttls()
                if self.user:
                    s.login(self.user, self.password)
                s.send_message(msg)
        except (OSError, smtplib.SMTPException) as exc:
            return Attempt("email", "failed", r.name, mask(r.email), f"{exc.__class__.__name__}: {exc}"[:300],
                           is_fallback=is_fallback)
        return Attempt("email", "sent", r.name, mask(r.email), is_fallback=is_fallback)


class PushSender:
    def __init__(self, url: str | None = None, topic: str | None = None, transport=None):
        self.url = url if url is not None else os.environ.get("HSS_NTFY_URL", "")
        self.topic = topic if topic is not None else os.environ.get("HSS_NTFY_TOPIC", "")
        self._http = httpx.Client(timeout=15, transport=transport)

    @property
    def configured(self) -> bool:
        return bool(self.url and self.topic)

    def publish(self, title: str, text: str, priority: str = "default") -> Attempt:
        try:
            resp = self._http.post(f"{self.url}/{self.topic}", content=text.encode(),
                                   headers={"Title": title, "Priority": priority})
        except httpx.HTTPError as exc:
            return Attempt("ntfy", "failed", "push subscribers", self.topic, exc.__class__.__name__)
        ok = resp.status_code == 200
        return Attempt("ntfy", "sent" if ok else "failed", "push subscribers", self.topic,
                       "" if ok else f"HTTP {resp.status_code}")


def dispatch(topic: str, title: str, text: str, attachment: Attachment | None, recipients: list[Recipient],
             wa: WhatsAppSender, email: EmailSender, push: PushSender) -> list[Attempt]:
    """Send to every recipient subscribed to `topic`: WhatsApp first, e-mail if that fails."""
    attempts: list[Attempt] = []
    sent_to: dict[str, str] = {}               # number -> recipient, so a shared phone gets one copy
    for r in recipients:
        if topic not in r.subscriptions:
            continue
        number = "".join(ch for ch in r.whatsapp if ch.isdigit())
        if number and number in sent_to:
            attempts.append(Attempt("whatsapp", "skipped", r.name, mask(r.whatsapp),
                                    f"same number as {sent_to[number]}, already sent"))
            continue
        delivered = False
        if r.whatsapp and wa.configured:
            a = wa.send(r, f"*{title}*\n{text}", attachment)
            attempts.append(a)
            delivered = a.status == "sent"
            if delivered:
                sent_to[number] = r.name
        if not delivered and r.email and email.configured:
            a = email.send(r, title, text, attachment, is_fallback=bool(r.whatsapp and wa.configured))
            attempts.append(a)
            delivered = a.status == "sent"
        if not delivered and not (r.whatsapp and wa.configured) and not (r.email and email.configured):
            why = ("the WhatsApp gateway isn't set up, and no e-mail fallback" if r.whatsapp
                   else "no WhatsApp number, and e-mail isn't set up" if r.email else "no WhatsApp number or e-mail address")
            attempts.append(Attempt("none", "failed", r.name, "", why))
    if topic in PUSH_TOPICS and push.configured:
        attempts.append(push.publish(title, text, "high" if topic in ("critical", "lockdown") else "default"))
    return attempts


def record(topic: str, attempts: list[Attempt]) -> None:
    with connect() as conn:
        for a in attempts:
            conn.execute(
                "INSERT INTO deliveries (topic, recipient, channel, address, status, detail, message_id, is_fallback) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (topic, a.recipient, a.channel, a.address, a.status, a.detail, a.message_id or None, a.is_fallback))


def test_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a few lines of text, for delivery tests (no PDF library needed)."""
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    content = "BT /F1 16 Tf 72 760 Td " + " ".join(
        f"({esc(t)}) Tj 0 -24 Td" for t in lines) + " ET"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
            "/Resources << /Font << /F1 5 0 R >> >> >>",
            f"<< /Length {len(content)} >>\nstream\n{content}\nendstream",
            "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out, offsets = b"%PDF-1.4\n", []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{o}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def senders() -> tuple[WhatsAppSender, EmailSender, PushSender]:
    return WhatsAppSender(), EmailSender(), PushSender()


def send_test(note: str = "") -> list[Attempt]:
    now = datetime.now(ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos")))
    stamp = now.strftime("%A %d %B %Y, %H:%M")
    pdf = test_pdf(["HSS delivery test", stamp, "If you can read this, report delivery works.", note])
    wa, email, push = senders()
    attempts = dispatch("test", "HSS delivery test", f"Test message sent {stamp}. {note}".strip(),
                        Attachment(f"hss-test-{now:%Y%m%d-%H%M}.pdf", "application/pdf", pdf),
                        load_recipients(), wa, email, push)
    record("test", attempts)
    return attempts


# ---------- background: gateway watch, delivery receipts, daily test ----------

def _watch_once(last_status: str | None) -> str:
    wa, email, push = senders()
    if not wa.configured:
        return last_status or "not configured"
    status = wa.status().get("status", "unknown")
    if status != last_status:
        with connect() as conn:
            conn.execute("INSERT INTO gateway_events (status, detail) VALUES (%s, %s)", (status, ""))
        if last_status == "ready" and status != "ready":
            attempts = dispatch("system", "WhatsApp gateway disconnected",
                                f"The WhatsApp gateway is now '{status}'. "
                                + ("Messages fall back to e-mail" if email.configured else "WhatsApp messages are not delivered")
                                + " until it is linked again (docker compose logs -f whatsapp).", None, load_recipients(),
                                wa, email, push)
            record("system", attempts)
    with connect() as conn:  # refresh receipts for WhatsApp messages from the last 48 hours
        rows = conn.execute("SELECT id, message_id FROM deliveries WHERE channel = 'whatsapp' AND status IN "
                            "('sent', 'delivered') AND message_id IS NOT NULL AND created_at > now() - interval '48 hours'"
                            ).fetchall()
        for row_id, mid in rows:
            ack = wa.ack(mid)
            if ack in ("delivered", "read", "played"):
                conn.execute("UPDATE deliveries SET status = %s WHERE id = %s", ("read" if ack != "delivered" else ack, row_id))
    return status


async def background_loop() -> None:
    tz = ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))
    daily = os.environ.get("HSS_NOTIFY_DAILY_TEST", "")       # "HH:MM", empty = off
    last_status, last_test_day = None, None
    while True:
        try:
            last_status = await asyncio.to_thread(_watch_once, last_status)
            now = datetime.now(tz)
            if daily and now.strftime("%H:%M") >= daily and last_test_day != now.date():
                last_test_day = now.date()
                await asyncio.to_thread(send_test, "Daily delivery test for the one-week trial.")
        except Exception:  # keep watching whatever happens
            log.exception("notification background loop")
        await asyncio.sleep(60)


# ---------- API ----------

class AttachmentIn(BaseModel):
    filename: str = Field(max_length=200)
    mimetype: str = Field(max_length=100)
    base64: str = Field(max_length=20_000_000)


class NotifyIn(BaseModel):
    topic: str
    title: str = Field(max_length=200)
    text: str = Field(max_length=4000)
    attachment: AttachmentIn | None = None


def _out(attempts: list[Attempt]) -> list[dict]:
    return [a.__dict__ for a in attempts]


@router.post("", dependencies=[Depends(require("admin", allow_admin_token=True))])
def notify(n: NotifyIn) -> dict:
    if n.topic not in TOPICS:
        raise HTTPException(status_code=422, detail=f"topic must be one of {sorted(TOPICS)}")
    att = None
    if n.attachment:
        try:
            att = Attachment(n.attachment.filename, n.attachment.mimetype, base64.b64decode(n.attachment.base64, validate=True))
        except ValueError:
            raise HTTPException(status_code=422, detail="attachment is not valid base64")
    wa, email, push = senders()
    attempts = dispatch(n.topic, n.title, n.text, att, load_recipients(), wa, email, push)
    record(n.topic, attempts)
    return {"attempts": _out(attempts)}


@router.post("/test", dependencies=[Depends(require("admin", allow_admin_token=True))])
def notify_test() -> dict:
    return {"attempts": _out(send_test("Sent on request."))}


@router.get("/status", dependencies=[Depends(require("admin", "cso", allow_admin_token=True))])
def notify_status(days: int = 7) -> dict:
    wa, email, push = senders()
    since = datetime.now(ZoneInfo("UTC")) - timedelta(days=max(1, min(days, 90)))
    with connect() as conn:
        counts = conn.execute("SELECT channel, status, is_fallback, count(*) FROM deliveries WHERE created_at > %s "
                              "GROUP BY 1, 2, 3 ORDER BY 1, 2", (since,)).fetchall()
        events = conn.execute("SELECT at, status FROM gateway_events WHERE at > %s ORDER BY at", (since,)).fetchall()
    return {
        "whatsapp": wa.status() if wa.configured else {"status": "not configured"},
        "email_configured": email.configured,
        "push_configured": push.configured,
        "recipients": [{"name": r["name"], "role": r["role"], "whatsapp": mask(r["whatsapp"]), "email": mask(r["email"]),
                        "subscriptions": list(r["subscriptions"]), "enabled": r["enabled"]} for r in recipient_rows()],
        "topics": TOPIC_TEXT,
        "since": since.isoformat(),
        "deliveries": [{"channel": c, "status": s, "fallback": f, "count": n} for c, s, f, n in counts],
        "gateway_events": [{"at": a.isoformat(), "status": s} for a, s in events],
    }


@router.get("/deliveries", dependencies=[Depends(require("admin", allow_admin_token=True))])
def deliveries(limit: int = 50) -> list[dict]:
    with connect() as conn:
        cur = conn.execute("SELECT created_at, topic, recipient, channel, address, status, detail, is_fallback "
                           "FROM deliveries ORDER BY created_at DESC LIMIT %s", (max(1, min(limit, 500)),))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def send_text_to_topic(topic: str, text: str, title: str = "HSS system") -> list[Attempt]:
    """A plain message to everyone subscribed to `topic` (e.g. backup failures to 'system')."""
    wa, email, push = senders()
    attempts = dispatch(topic, title, text, None, load_recipients(), wa, email, push)
    record(topic, attempts)
    return attempts


# ---------- recipients and the WhatsApp link, managed in the console (administrators) ----------

PHONE = re.compile(r"^\+[1-9]\d{7,14}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RecipientIn(BaseModel):
    name: str = Field(min_length=2, max_length=60)
    role: str = Field(default="", max_length=40)
    whatsapp: str = Field(default="", max_length=20)
    email: str = Field(default="", max_length=120)
    subscriptions: list[str] = Field(default_factory=list, max_length=len(TOPICS))
    enabled: bool = True


def _clean(body: RecipientIn) -> RecipientIn:
    number = re.sub(r"[\s\-()]", "", body.whatsapp)
    if number.startswith("00"):
        number = "+" + number[2:]
    if number and not PHONE.match(number):
        raise HTTPException(status_code=422, detail="WhatsApp number: the full international number, e.g. +2348012345678 (not 0801...).")
    email = body.email.strip()
    if email and not EMAIL.match(email):
        raise HTTPException(status_code=422, detail="That e-mail address doesn't look right.")
    if not number and not email:
        raise HTTPException(status_code=422, detail="Give a WhatsApp number, an e-mail address, or both.")
    unknown = [t for t in body.subscriptions if t not in TOPICS]
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown message type: {', '.join(unknown)}")
    return body.model_copy(update={"whatsapp": number, "email": email, "name": body.name.strip(), "subscriptions": sorted(set(body.subscriptions))})


@router.get("/recipients", dependencies=[Depends(require("admin"))])
def list_recipients() -> dict:
    return {"recipients": recipient_rows(), "topics": TOPIC_TEXT}


@router.post("/recipients", status_code=201)
def add_recipient(body: RecipientIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    b = _clean(body)
    with connect() as conn:
        _import_file_once(conn)
        r = conn.execute(f"INSERT INTO notify_recipients (name, role, whatsapp, email, subscriptions, enabled, updated_by) "
                         f"VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING {REC_COLS}",
                         (b.name, b.role, b.whatsapp, b.email, b.subscriptions, b.enabled, user["username"])).fetchone()
    audit("recipient_added", user_id=user["id"], username=user["username"], ip=client_ip(request), recipient=b.name,
          whatsapp=mask(b.whatsapp), email=mask(b.email), receives=b.subscriptions)
    return _rec_row(r)


@router.put("/recipients/{rid}")
def change_recipient(rid: int, body: RecipientIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    b = _clean(body)
    with connect() as conn:
        r = conn.execute(f"UPDATE notify_recipients SET name = %s, role = %s, whatsapp = %s, email = %s, subscriptions = %s, enabled = %s, "
                         f"updated_by = %s, updated_at = now() WHERE id = %s RETURNING {REC_COLS}",
                         (b.name, b.role, b.whatsapp, b.email, b.subscriptions, b.enabled, user["username"], rid)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such recipient")
    audit("recipient_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), recipient=b.name,
          whatsapp=mask(b.whatsapp), email=mask(b.email), receives=b.subscriptions, enabled=b.enabled)
    return _rec_row(r)


@router.delete("/recipients/{rid}")
def delete_recipient(rid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        r = conn.execute("DELETE FROM notify_recipients WHERE id = %s RETURNING name", (rid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such recipient")
    audit("recipient_deleted", user_id=user["id"], username=user["username"], ip=client_ip(request), recipient=r[0])
    return {"deleted": True}


@router.post("/recipients/{rid}/test")
def test_recipient(rid: int, request: Request, user: dict = Depends(require("admin"))) -> dict:
    """A short test message to one person (WhatsApp, else e-mail), to check their number."""
    with connect() as conn:
        r = conn.execute(f"SELECT {REC_COLS} FROM notify_recipients WHERE id = %s", (rid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such recipient")
    row = _rec_row(r)
    rec = Recipient(row["name"], row["role"], row["whatsapp"], row["email"], ["test"])
    wa, email, push = senders()
    stamp = datetime.now(ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))).strftime("%d %B %Y, %H:%M")
    attempts = dispatch("test", "HSS test message", f"Hello {row['name']}, this is a test from the security platform ({stamp}). "
                        "You'll receive: " + (", ".join(row["subscriptions"]) or "nothing yet") + ".",
                        None, [rec], wa, email, PushSender(url="", topic=""))
    record("test", attempts)
    audit("recipient_tested", user_id=user["id"], username=user["username"], ip=client_ip(request), recipient=row["name"])
    return {"attempts": _out(attempts)}


@router.get("/whatsapp/qr", dependencies=[Depends(require("admin"))])
def whatsapp_qr() -> dict:
    """The gateway's link QR code (SVG) while it waits to be linked."""
    wa = WhatsAppSender()
    if not wa.configured:
        raise HTTPException(status_code=409, detail="The WhatsApp gateway isn't set up (HSS_WA_TOKEN, profile notify).")
    return wa.call("GET", "/qr")


@router.post("/whatsapp/unlink")
def whatsapp_unlink(request: Request, user: dict = Depends(require("admin"))) -> dict:
    wa = WhatsAppSender()
    before = wa.status().get("me")
    res = wa.call("POST", "/logout")
    audit("whatsapp_unlinked", user_id=user["id"], username=user["username"], ip=client_ip(request), number=mask(str(before or "")))
    return res


@router.post("/whatsapp/restart")
def whatsapp_restart(request: Request, user: dict = Depends(require("admin"))) -> dict:
    res = WhatsAppSender().call("POST", "/restart")
    audit("whatsapp_restarted", user_id=user["id"], username=user["username"], ip=client_ip(request))
    return res
