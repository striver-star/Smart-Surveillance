"""Notifications: WhatsApp (provider A gateway) first, e-mail fallback, push (ntfy) for alerts.

Recipients and what they receive are kept in /config/recipients.json (see config/recipients.example.json).
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
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import connect
from .wall import admin_token

log = logging.getLogger("notify")
router = APIRouter(prefix="/notify")

TOPICS = {"daily", "weekly", "monthly", "critical", "device", "system", "test"}
PUSH_TOPICS = {"critical", "device", "system"}


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
    status: str                 # sent | failed
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


def load_recipients(path: Path | None = None) -> list[Recipient]:
    path = path or Path(os.environ.get("HSS_RECIPIENTS", "/config/recipients.json"))
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    return [Recipient(**{k: v for k, v in r.items() if k in Recipient.__dataclass_fields__}) for r in raw]


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
    for r in recipients:
        if topic not in r.subscriptions:
            continue
        delivered = False
        if r.whatsapp and wa.configured:
            a = wa.send(r, f"*{title}*\n{text}", attachment)
            attempts.append(a)
            delivered = a.status == "sent"
        if not delivered and r.email and email.configured:
            a = email.send(r, title, text, attachment, is_fallback=bool(r.whatsapp and wa.configured))
            attempts.append(a)
            delivered = a.status == "sent"
        if not delivered and not (r.whatsapp and wa.configured) and not (r.email and email.configured):
            attempts.append(Attempt("none", "failed", r.name, "", "no WhatsApp number or e-mail configured"))
    if topic in PUSH_TOPICS and push.configured:
        attempts.append(push.publish(title, text, "high" if topic == "critical" else "default"))
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
                                f"The WhatsApp gateway is now '{status}'. Messages fall back to e-mail until it is "
                                "linked again (docker compose logs -f whatsapp).", None, load_recipients(),
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


@router.post("", dependencies=[Depends(admin_token)])
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


@router.post("/test", dependencies=[Depends(admin_token)])
def notify_test() -> dict:
    return {"attempts": _out(send_test("Sent on request."))}


@router.get("/status", dependencies=[Depends(admin_token)])
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
        "recipients": [{"name": r.name, "role": r.role, "whatsapp": mask(r.whatsapp), "email": mask(r.email),
                        "subscriptions": r.subscriptions} for r in load_recipients()],
        "since": since.isoformat(),
        "deliveries": [{"channel": c, "status": s, "fallback": f, "count": n} for c, s, f, n in counts],
        "gateway_events": [{"at": a.isoformat(), "status": s} for a, s in events],
    }


@router.get("/deliveries", dependencies=[Depends(admin_token)])
def deliveries(limit: int = 50) -> list[dict]:
    with connect() as conn:
        cur = conn.execute("SELECT created_at, topic, recipient, channel, address, status, detail, is_fallback "
                           "FROM deliveries ORDER BY created_at DESC LIMIT %s", (max(1, min(limit, 500)),))
        cols = [c.name for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]
