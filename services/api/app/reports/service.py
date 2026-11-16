"""Reports: generate (on demand or on a schedule), archive, download and send (Section 5.6).

Schedule (off unless HSS_REPORT_TIME is set, for example "07:00", local time HSS_TZ):
daily report every day for yesterday, weekly on Mondays for last week, monthly on the 1st for
last month. Each is sent to the recipients subscribed to "daily", "weekly" or "monthly".
The compliance and privacy report runs on the 1st for last month and goes to "compliance" subscribers.
HSS_REPORT_KINDS limits which run (default "daily,weekly,monthly,compliance"); HSS_REPORT_FORMATS picks what
is attached (default "pdf"; "pdf,docx" sends both).
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from ..auth import audit, client_ip, require
from ..db import connect
from . import narrative
from .data import KINDS, collect, period_for

log = logging.getLogger("reports")
router = APIRouter(prefix="/reports", tags=["reports"])
READERS = ("admin", "cso", "management")
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))


def data_dir() -> Path:
    return Path(os.environ.get("HSS_DATA_DIR", "/data"))


def generate(kind: str, *, created_by: str, on: date | None = None, start: date | None = None,
             end: date | None = None, camera: str | None = None) -> dict:
    from ..console import get_branding, load_devices
    from . import docx_render, pdf
    if kind == "compliance":
        return generate_compliance(created_by=created_by, on=on)
    period = period_for(kind, tz(), on=on, start=start, end=end)
    branding = get_branding()
    logo = data_dir() / "branding" / branding["logo"]["file"] if branding.get("logo") else None
    d = collect(period, site_name=branding["site_name"], devices=load_devices(), snapshot_root=data_dir(), camera=camera)
    report_id = uuid.uuid4()
    folder = data_dir() / "reports" / f"{period.start:%Y}" / f"{period.start:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{kind}-{period.start:%Y-%m-%d}-{str(report_id)[:8]}"
    pdf_path, docx_path = folder / f"{stem}.pdf", folder / f"{stem}.docx"
    pdf_path.write_bytes(pdf.render(d, branding, logo))
    docx_path.write_bytes(docx_render.render(d, branding, logo))
    title = narrative.title(d) + (f" ({camera})" if camera else "")
    figures = {"events": d.total, "critical": d.counts.get("critical", 0), "warning": d.counts.get("warning", 0),
               "info": d.counts.get("info", 0), "previous": d.prev_total, "change_pct": d.change_pct(),
               "locations": len(d.locations()), "repeats": len(d.repeats()), "open_items": len(d.open_items()),
               "label": period.label()}
    with connect() as conn:
        conn.execute("INSERT INTO reports (id, kind, title, period_start, period_end, timezone, created_by, summary, figures, "
                     "pdf_path, docx_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (report_id, kind, title, period.start, period.end, period.tz.key, created_by,
                      "\n\n".join(narrative.summary(d)), Jsonb(figures),
                      str(pdf_path.relative_to(data_dir())), str(docx_path.relative_to(data_dir()))))
    return get_report(report_id)


def generate_compliance(*, created_by: str, on: date | None = None) -> dict:
    """The monthly compliance and privacy report (reports/compliance.py), for the month containing `on`
    (default: last month)."""
    from ..console import get_branding
    from . import compliance
    period = period_for("monthly", tz(), on=on)
    branding = get_branding()
    logo = data_dir() / "branding" / branding["logo"]["file"] if branding.get("logo") else None
    c = compliance.collect(period.start, period.end, tz(), branding["site_name"], period.label())
    report_id = uuid.uuid4()
    folder = data_dir() / "reports" / f"{period.start:%Y}" / f"{period.start:%m}"
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"compliance-{period.start:%Y-%m}-{str(report_id)[:8]}"
    pdf_path, docx_path = folder / f"{stem}.pdf", folder / f"{stem}.docx"
    pdf_path.write_bytes(compliance.render_pdf(c, branding, logo))
    docx_path.write_bytes(compliance.render_docx(c, branding, logo))
    n = c.counts()
    figures = {"label": period.label(), "actions": n[compliance.ACTION], "attention": n[compliance.ATTENTION], "ok": n[compliance.OK],
               "checks": [{"status": x.status, "area": x.area, "text": x.text} for x in c.checks]}
    with connect() as conn:
        conn.execute("INSERT INTO reports (id, kind, title, period_start, period_end, timezone, created_by, summary, figures, "
                     "pdf_path, docx_path) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (report_id, "compliance", "Compliance and privacy report", period.start, period.end, period.tz.key, created_by,
                      compliance.summary(c), Jsonb(figures), str(pdf_path.relative_to(data_dir())), str(docx_path.relative_to(data_dir()))))
    return get_report(report_id)


COLS = "id, kind, title, period_start, period_end, timezone, created_at, created_by, summary, figures, sent"


def _row(r) -> dict:
    out = dict(zip([c.strip() for c in COLS.split(",")], r))
    out["id"] = str(out["id"])
    out["files"] = {"pdf": f"/api/reports/{out['id']}/pdf", "docx": f"/api/reports/{out['id']}/docx"}
    return out


def get_report(report_id) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS} FROM reports WHERE id = %s", (report_id,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such report")
    return _row(r)


def send(report_id, *, formats=("pdf",), topic: str | None = None) -> list[dict]:
    from ..notify import Attachment, dispatch, load_recipients, record, senders
    rep = get_report(report_id)
    topic = topic or (rep["kind"] if rep["kind"] != "custom" else None)
    if topic not in ("daily", "weekly", "monthly", "compliance"):
        raise HTTPException(status_code=422, detail="choose who receives it: daily, weekly, monthly or compliance subscribers")
    with connect() as conn:
        paths = conn.execute("SELECT pdf_path, docx_path FROM reports WHERE id = %s", (report_id,)).fetchone()
    recipients = load_recipients()
    if not any(topic in r.subscriptions for r in recipients):
        raise HTTPException(status_code=422, detail=f"Nobody is subscribed to {topic} reports. Add them in config/recipients.json.")
    wa, email, push = senders()
    first_para = (rep["summary"].split("\n\n") or [""])[0]
    attempts_all = []
    for i, fmt in enumerate(f for f in ("pdf", "docx") if f in formats):
        path = data_dir() / paths[0 if fmt == "pdf" else 1]
        name = f"{rep['title']} {rep['figures'].get('label', '')}".strip().replace(" ", "_").replace("/", "-")
        att = Attachment(f"{re.sub(r'[^A-Za-z0-9_.-]', '', name)}.{fmt}", MIME[fmt], path.read_bytes())
        text = first_para if i == 0 else "Word version, for editing."
        attempts = dispatch(topic, f"{rep['title']} · {rep['figures'].get('label', '')}", text, att,
                            recipients, wa, email, push if i == 0 else type(push)("", ""))
        record(topic, attempts)
        attempts_all += [{"format": fmt, "channel": a.channel, "status": a.status, "recipient": a.recipient,
                          "detail": a.detail, "at": datetime.now(tz()).isoformat(timespec="seconds")} for a in attempts]
    with connect() as conn:
        conn.execute("UPDATE reports SET sent = sent || %s WHERE id = %s", (Jsonb(attempts_all), report_id))
    return attempts_all


# ------------------------------------------------------------------ endpoints

class ComplianceIn(BaseModel):
    dpia_review_due: date | None = None
    signs_checked_on: date | None = None
    dpo_name: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=1000)


@router.get("/compliance/settings")
def compliance_settings(_: dict = Depends(require("admin", "cso"))) -> dict:
    from .compliance import settings
    return settings()


@router.put("/compliance/settings")
def put_compliance_settings(body: ComplianceIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    from .compliance import settings
    value = {"dpia_review_due": body.dpia_review_due.isoformat() if body.dpia_review_due else None,
             "signs_checked_on": body.signs_checked_on.isoformat() if body.signs_checked_on else None,
             "dpo_name": body.dpo_name.strip(), "notes": body.notes.strip()}
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('compliance', %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
                      (Jsonb(value),))
    audit("compliance_settings_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), **value)
    return settings()


class GenerateIn(BaseModel):
    kind: str = Field(pattern="^(daily|weekly|monthly|custom|compliance)$")
    on: date | None = None
    start: date | None = None
    end: date | None = None
    camera: str | None = Field(default=None, pattern=r"^[A-Za-z0-9._-]{1,100}$")


@router.post("", status_code=201)
def generate_endpoint(body: GenerateIn, request: Request, user: dict = Depends(require(*READERS, allow_admin_token=True))) -> dict:
    try:
        rep = generate(body.kind, created_by=user["username"], on=body.on, start=body.start, end=body.end, camera=body.camera)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit("report_generated", user_id=user["id"], username=user["username"], ip=client_ip(request),
          report=rep["id"], kind=body.kind, period=rep["figures"]["label"])
    return rep


@router.get("")
def list_reports(kind: str | None = None, q: str | None = None, limit: int = 50,
                 _: dict = Depends(require(*READERS, allow_admin_token=True))) -> list[dict]:
    sql, params = f"SELECT {COLS} FROM reports WHERE true", []
    if kind in KINDS or kind == "compliance":
        sql += " AND kind = %s"
        params.append(kind)
    if q:
        sql += " AND (title ILIKE %s OR summary ILIKE %s OR figures->>'label' ILIKE %s)"
        params += [f"%{q}%"] * 3
    sql += " ORDER BY period_start DESC, created_at DESC LIMIT %s"
    params.append(max(1, min(limit, 200)))
    with connect() as conn:
        return [_row(r) for r in conn.execute(sql, params).fetchall()]


@router.get("/{report_id}")
def report_detail(report_id: uuid.UUID, _: dict = Depends(require(*READERS, allow_admin_token=True))) -> dict:
    return get_report(report_id)


@router.get("/{report_id}/{fmt}")
def report_file(report_id: uuid.UUID, fmt: str, request: Request, user: dict = Depends(require(*READERS, allow_admin_token=True))):
    if fmt not in MIME:
        raise HTTPException(status_code=404, detail="pdf or docx")
    rep = get_report(report_id)
    with connect() as conn:
        paths = conn.execute("SELECT pdf_path, docx_path FROM reports WHERE id = %s", (report_id,)).fetchone()
    path = (data_dir() / paths[0 if fmt == "pdf" else 1]).resolve()
    if not path.is_relative_to(data_dir().resolve()) or not path.exists():
        raise HTTPException(status_code=404, detail="file missing")
    name = re.sub(r"[^A-Za-z0-9_.-]", "", f"{rep['title']}_{rep['figures'].get('label', '')}".replace(" ", "_"))
    audit("report_downloaded", user_id=user["id"], username=user["username"], ip=client_ip(request), report=str(report_id), format=fmt)
    return FileResponse(path, media_type=MIME[fmt], filename=f"{name}.{fmt}")


class SendIn(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["pdf"])
    topic: str | None = Field(default=None, pattern="^(daily|weekly|monthly|compliance)$")


@router.post("/{report_id}/send")
def send_endpoint(report_id: uuid.UUID, body: SendIn, request: Request,
                  user: dict = Depends(require("admin", "cso", allow_admin_token=True))) -> dict:
    attempts = send(report_id, formats=tuple(f for f in body.formats if f in MIME) or ("pdf",), topic=body.topic)
    audit("report_sent", user_id=user["id"], username=user["username"], ip=client_ip(request), report=str(report_id),
          delivered=sum(a["status"] == "sent" for a in attempts), attempts=len(attempts))
    return {"attempts": attempts}


# ------------------------------------------------------------------ schedule

def due_today(today: date) -> list[str]:
    kinds = [k.strip() for k in os.environ.get("HSS_REPORT_KINDS", "daily,weekly,monthly,compliance").split(",") if k.strip()]
    due = []
    if "daily" in kinds:
        due.append("daily")
    if "weekly" in kinds and today.weekday() == 0:
        due.append("weekly")
    if "monthly" in kinds and today.day == 1:
        due.append("monthly")
    if "compliance" in kinds and today.day == 1:
        due.append("compliance")
    return due


def run_schedule_once(now: datetime) -> list[str]:
    """Generate and send whatever is due and not yet done today. Returns the kinds it ran."""
    at = os.environ.get("HSS_REPORT_TIME", "")
    if not re.fullmatch(r"\d{2}:\d{2}", at) or now.strftime("%H:%M") < at:
        return []
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'report_schedule'").fetchone()
    done = row[0] if row else {}
    ran = []
    formats = tuple(f.strip() for f in os.environ.get("HSS_REPORT_FORMATS", "pdf").split(",") if f.strip() in MIME) or ("pdf",)
    for kind in due_today(now.date()):
        if done.get(kind) == now.date().isoformat():
            continue
        done[kind] = now.date().isoformat()          # mark first: a failing report must not retry every minute
        with connect() as conn:
            conn.execute("INSERT INTO settings (key, value) VALUES ('report_schedule', %s) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(done),))
        try:
            rep = generate(kind, created_by="schedule")
            send(rep["id"], formats=formats)
            ran.append(kind)
            log.info("scheduled %s report %s sent", kind, rep["id"])
        except Exception:  # keep the loop alive; the failure is logged and visible as a missing report
            log.exception("scheduled %s report failed", kind)
    return ran


async def background_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(run_schedule_once, datetime.now(tz()))
        except Exception:  # never let the scheduler die
            log.exception("report schedule check failed")
        await asyncio.sleep(60)
