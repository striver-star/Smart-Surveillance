"""Compliance and privacy report (release 2.0, second batch): one monthly report for the CSO, the DPO
and management that shows whether the system is run as the DPIA and the legal review say.

It opens with a checklist (OK / Attention / Action) and then gives the figures behind it:
- face and plate: the legal review in force, its expiry, the DPIA review date, the recognition signs,
  and how much recognition was used;
- retention: the configured limits, the clean-up runs, the oldest data still held, NVR recording days,
  and evidence past its keep-until date;
- access to video: the viewing log (live and recordings), by person, out-of-hours viewing;
- evidence: sealed, downloaded, exported, legal holds, failed checks;
- accounts: roles, two-factor, failed sign-ins, accounts unused for 90 days, changes to users;
- data that left the system: evidence exports and downloads, viewing log exports, reports downloaded.

The dates the system can't know (DPIA review due, signs last checked, DPO) are kept in the settings key
'compliance' and set in the console (Settings, Compliance).
"""
from __future__ import annotations

import io
import logging
import os
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median
from xml.sax.saxutils import escape

from ..db import connect

log = logging.getLogger("reports.compliance")
OK, ATTENTION, ACTION = "OK", "Attention", "Action"
NIGHT = (22, 6)                     # out-of-hours viewing: 22:00 to 06:00 local


def _days(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


def settings() -> dict:
    with connect() as conn:
        r = conn.execute("SELECT value FROM settings WHERE key = 'compliance'").fetchone()
    v = (r[0] if r else None) or {}
    return {"dpia_review_due": v.get("dpia_review_due"), "signs_checked_on": v.get("signs_checked_on"),
            "dpo_name": v.get("dpo_name", ""), "notes": v.get("notes", "")}


@dataclass
class Check:
    status: str
    area: str
    text: str
    fix: str = ""


@dataclass
class Section:
    title: str
    lead: str = ""
    headers: list[str] = field(default_factory=list)
    rows: list[list] = field(default_factory=list)
    widths: list[float] = field(default_factory=list)       # fractions of the page width
    notes: list[str] = field(default_factory=list)


@dataclass
class Compliance:
    site_name: str
    label: str
    tz: str
    generated_at: datetime
    checks: list[Check]
    sections: list[Section]

    def counts(self) -> Counter:
        return Counter(c.status for c in self.checks)


# ------------------------------------------------------------------ pure checks (tested)

def date_check(area: str, due: date | None, today: date, *, missing: str, soon_days: int, what: str, fix: str) -> Check:
    """A review date: OK if more than soon_days away, Attention if close or not set, Action if past."""
    if not due:
        return Check(ATTENTION, area, missing, fix)
    left = (due - today).days
    if left < 0:
        return Check(ACTION, area, f"{what} was due on {due:%d %B %Y}, {-left} days ago.", fix)
    if left <= soon_days:
        return Check(ATTENTION, area, f"{what} is due on {due:%d %B %Y}, in {left} days.", fix)
    return Check(OK, area, f"{what} is due on {due:%d %B %Y}.")


def recording_check(days_by_camera: dict[str, int], target: int) -> Check:
    if not days_by_camera:
        return Check(ATTENTION, "Recording", "No NVR recording check yet (Devices: NVRs are checked daily).",
                     "Check that the NVRs are added in Devices and reachable.")
    short = sorted(c for c, d in days_by_camera.items() if d < target)
    long = sorted(c for c, d in days_by_camera.items() if d > target * 2)
    if short:
        return Check(ATTENTION, "Recording", f"{len(short)} of {len(days_by_camera)} cameras keep less than {target} days "
                     f"({', '.join(short[:5])}{'…' if len(short) > 5 else ''}).", "Fit larger drives or lower bitrates (see the drive plan).")
    if long:
        return Check(ATTENTION, "Recording", f"{len(long)} cameras keep more than {2 * target} days; the DPIA sets {target}.",
                     "Set a maximum recording age on the NVR for those channels.")
    return Check(OK, "Recording", f"All {len(days_by_camera)} cameras keep about {target} days or more, within the DPIA.")


def n_of(n: int, word: str, plural: str | None = None) -> str:
    return f"{n} {word if n == 1 else (plural or word + 's')}"


def out_of_hours(hour: int) -> bool:
    a, b = NIGHT
    return hour >= a or hour < b


# ------------------------------------------------------------------ collection

def collect(start: datetime, end: datetime, tzinfo, site_name: str, label: str, now: datetime | None = None) -> Compliance:
    now = now or datetime.now(timezone.utc)
    today = now.astimezone(tzinfo).date()
    cfg = settings()
    checks: list[Check] = []
    sections: list[Section] = []

    # --- face and plate
    from ..legal import current_acceptance, recognition_scope, status as legal_status
    acc, st = current_acceptance(now), legal_status()
    with connect() as conn:
        types = conn.execute("SELECT type, camera_id, count(*) FROM events WHERE occurred_at >= %s AND occurred_at < %s GROUP BY 1, 2",
                             (start, end)).fetchall()
    rec = [(t, c, n) for t, c, n in types if recognition_scope(t)]
    used = sum(n for _, _, n in rec)
    if acc and not acc["expired"] and acc["current_version"]:
        exp = acc["expires_at"].astimezone(tzinfo).date()
        checks.append(date_check("Face and plate", exp, today, missing="", soon_days=60, what="Renewal of the legal review",
                                 fix="Renew the legal opinion and accept the review again (Face & plate)."))
    elif used:
        checks.append(Check(ACTION, "Face and plate", f"{n_of(used, 'recognition event')} this period without a legal review in force.",
                            "Stop recognition, or renew and accept the legal review (Face & plate)."))
    else:
        checks.append(Check(OK, "Face and plate", "Face and plate recognition are locked and were not used."))
    due = date.fromisoformat(cfg["dpia_review_due"]) if cfg["dpia_review_due"] else None
    checks.append(date_check("DPIA", due, today, missing="The DPIA review date isn't recorded.", soon_days=60, what="The DPIA review",
                             fix="Record the DPIA review date in Settings › Compliance; review the DPIA with the DPO."))
    if st.get("face") or st.get("plate") or used:
        signs = date.fromisoformat(cfg["signs_checked_on"]) if cfg["signs_checked_on"] else None
        if not signs:
            checks.append(Check(ATTENTION, "Signs", "No record of the recognition signs being checked.",
                                "Walk the site, check every recognition sign, and record the date in Settings › Compliance."))
        elif (today - signs).days > 90:
            checks.append(Check(ATTENTION, "Signs", f"Recognition signs were last checked {signs:%d %B %Y}, over 90 days ago.",
                                "Walk the site and check the signs; record the date."))
        else:
            checks.append(Check(OK, "Signs", f"Recognition signs checked on {signs:%d %B %Y}."))
    rows = [["Legal review", "in force" if acc and not acc["expired"] and acc["current_version"] else "not in force"],
            ["Features unlocked", ", ".join(k for k in ("face", "plate") if st.get(k)) or "none"]]
    if acc:
        rows += [["Accepted by", f"{acc['full_name']} ({acc['position']}) on {acc['accepted_at'].astimezone(tzinfo):%d %B %Y}"],
                 ["Legal opinion", f"{acc['reviewer_name']}, {acc['reviewer_firm']}, ref {acc['opinion_ref']}"],
                 ["DPIA reference", acc["dpia_ref"] or "—"], ["Expires", f"{acc['expires_at'].astimezone(tzinfo):%d %B %Y}"]]
    with connect() as conn:
        wl = conn.execute("SELECT count(*) FILTER (WHERE active AND expires_at >= current_date), "
                          "count(*) FILTER (WHERE active AND expires_at >= current_date AND expires_at < current_date + 14) FROM watch_people").fetchone()
        wp = conn.execute("SELECT count(*) FILTER (WHERE active AND expires_at >= current_date) FROM watch_plates").fetchone()
        vd = conn.execute("SELECT verdict, count(*) FROM recognition_verdicts WHERE at >= %s AND at < %s GROUP BY 1", (start, end)).fetchall()
    verdicts = dict(vd)
    rows += [["Watchlists", f"{wl[0]} people, {wp[0]} plates in force"],
             ["Operator verdicts", f"{verdicts.get('confirmed', 0)} confirmed, {verdicts.get('rejected', 0)} not a match" if vd else "none this period"]]
    if wl[1]:
        checks.append(Check(ATTENTION, "Watchlists", f"{n_of(wl[1], 'watchlist entry', 'watchlist entries')} expire within 14 days.",
                            "Renew them with a current reason and authority, or let them lapse (Face & plate › Face watchlist)."))
    if verdicts.get("rejected", 0) > verdicts.get("confirmed", 0) and sum(verdicts.values()) >= 10:
        checks.append(Check(ATTENTION, "Recognition accuracy", "Operators marked more matches 'not a match' than confirmed this period.",
                            "Raise the face threshold (Face & plate › Accuracy shows a suggestion) or review camera placement."))
    rows += [["DPIA review due", f"{due:%d %B %Y}" if due else "not recorded"],
             ["Signs last checked", cfg["signs_checked_on"] or "not recorded"], ["Data Protection Officer", cfg["dpo_name"] or "not recorded"]]
    by_scope = Counter()
    for t, _c, n in rec:
        by_scope[recognition_scope(t)] += n
    s = Section("Face and plate recognition", f"{n_of(used, 'recognition event')} this period "
                f"({by_scope['face']} face, {by_scope['plate']} plate)." if used else "No recognition events this period.",
                ["Item", "Status"], rows, [0.3, 0.7])
    if rec:
        top = Counter()
        for t, c, n in rec:
            top[(c, t)] += n
        s.notes.append("Most recognition events: " + "; ".join(f"{c} {t.replace('_', ' ')} ({n})" for (c, t), n in top.most_common(6)) + ".")
    sections.append(s)

    # --- retention
    ev_days, pos_days, view_days, evd_days, rec_target = (_days("HSS_EVENT_DAYS", 365), _days("HSS_POSITION_DAYS", 30),
                                                          _days("HSS_VIEW_LOG_DAYS", 365), _days("HSS_EVIDENCE_DAYS", 365),
                                                          _days("HSS_RECORDING_DAYS", 30))
    with connect() as conn:
        runs = conn.execute("SELECT at, status, data FROM system_reports WHERE kind = 'retention' AND at >= %s ORDER BY at DESC",
                            (start - timedelta(days=2),)).fetchall()
        oldest = conn.execute("SELECT min(e.occurred_at) FROM events e WHERE NOT EXISTS (SELECT 1 FROM alerts a WHERE a.event_id = e.id "
                              "AND a.status <> 'closed')").fetchone()[0]
        oldest_pos = conn.execute("SELECT min(at) FROM unit_positions").fetchone()[0]
        overdue = conn.execute("SELECT count(*) FROM evidence WHERE deleted_at IS NULL AND NOT legal_hold AND retain_until < %s",
                               (today,)).fetchone()[0]
        holds = conn.execute("SELECT count(*) FROM evidence WHERE deleted_at IS NULL AND legal_hold").fetchone()[0]
        nvr_rec = conn.execute("SELECT alias, info->'recording'->'channels' FROM nvrs WHERE enabled").fetchall()
    last = runs[0][0] if runs else None
    if not last or now - last > timedelta(days=2):
        checks.append(Check(ACTION, "Retention", "The nightly retention clean-up hasn't run in the last 2 days.",
                            "Check the API service is running; run it from System › Retention."))
    else:
        too_old = []
        if oldest and now - oldest > timedelta(days=ev_days + 2):
            too_old.append(f"events from {oldest.astimezone(tzinfo):%d %B %Y}")
        if oldest_pos and now - oldest_pos > timedelta(days=pos_days + 2):
            too_old.append(f"guard positions from {oldest_pos.astimezone(tzinfo):%d %B %Y}")
        checks.append(Check(ACTION, "Retention", "Data older than its limit is still held: " + ", ".join(too_old) + ".",
                            "Run the retention clean-up and check its result.") if too_old else
                      Check(OK, "Retention", f"The clean-up ran {len(runs)} times; nothing is held beyond its limit."))
    if overdue:
        checks.append(Check(ACTION, "Evidence", f"{n_of(overdue, 'evidence item')} past the keep-until date and not on legal hold.",
                            "Review them in the Evidence vault: delete, or set a legal hold with a reason."))
    days_by_cam = {}
    for alias, chans in nvr_rec:
        for ch, v in (chans or {}).items():
            if isinstance(v, dict) and v.get("days") is not None:
                days_by_cam[f"{alias}-ch{int(ch):02d}"] = int(v["days"])
    checks.append(recording_check(days_by_cam, rec_target))
    d = sorted(days_by_cam.values())
    sections.append(Section("Retention", "How long each kind of data is kept, and whether the limits are kept.",
                            ["Data", "Limit", "Held now"],
                            [["Events, snapshots and clips", f"{ev_days} days (open alerts kept)", f"oldest {oldest.astimezone(tzinfo):%d %b %Y}" if oldest else "none"],
                             ["Guard positions", f"{pos_days} days", f"oldest {oldest_pos.astimezone(tzinfo):%d %b %Y}" if oldest_pos else "none"],
                             ["Viewing log", f"{view_days} days", "—"],
                             ["Evidence vault", f"{evd_days} days unless on legal hold", f"{holds} on legal hold, {overdue} overdue"],
                             ["NVR recordings", f"{rec_target} days (overwritten by the NVR)",
                              f"{d[0]} to {d[-1]} days, median {median(d):.0f}" if d else "not checked"]],
                            [0.34, 0.33, 0.33],
                            [f"Retention clean-up last ran {last.astimezone(tzinfo):%d %B %Y %H:%M}." if last else "No retention run found."]))

    # --- viewing
    with connect() as conn:
        views = conn.execute("SELECT username, role, kind, camera_id, started_at FROM view_log WHERE started_at >= %s AND started_at < %s",
                             (start, end)).fetchall()
    per: dict[str, Counter] = {}
    distinct: dict[str, set] = {}
    night = 0
    for u, _role, k, cam, at in views:
        c = per.setdefault(u, Counter())
        c[k] += 1
        distinct.setdefault(u, set()).add(cam)
        if out_of_hours(at.astimezone(tzinfo).hour):
            c["night"] += 1
            night += 1
    roles = {u: r for u, r, *_ in views}
    vrows = sorted(([u, roles.get(u) or "", c["live"], c["playback"], len(distinct.get(u, ())), c["night"]] for u, c in per.items()),
                   key=lambda r: -(r[2] + r[3]))
    sections.append(Section("Who watched video", f"{n_of(len(views), 'viewing')} by {n_of(len(per), 'person', 'people')} this period; {night} between "
                            f"{NIGHT[0]:02d}:00 and {NIGHT[1]:02d}:00. Wall screens are shared displays and aren't counted.",
                            ["Person", "Role", "Live", "Recordings", "Cameras", "22:00–06:00"], vrows[:25],
                            [0.24, 0.16, 0.12, 0.16, 0.14, 0.18],
                            ["Out-of-hours viewing is normal for night operators; check it for anyone who doesn't work nights."]))

    # --- audit: evidence, exports, accounts
    with connect() as conn:
        acts = conn.execute("SELECT action, username, count(*) FROM audit_log WHERE at >= %s AND at < %s GROUP BY 1, 2",
                            (start, end)).fetchall()
        users = conn.execute("SELECT username, role, totp_enabled, disabled, last_login_at, created_at FROM users").fetchall()
        user_changes = conn.execute("SELECT at, username, action, detail FROM audit_log WHERE at >= %s AND at < %s AND action IN "
                                    "('user_created', 'user_changed') ORDER BY at", (start, end)).fetchall()
    act = Counter()
    by_person: dict[str, Counter] = {}
    for a, u, n in acts:
        act[a] += n
        by_person.setdefault(a, Counter())[u or "?"] += n
    if act["evidence_verify_failed"]:
        checks.append(Check(ACTION, "Evidence", f"{n_of(act['evidence_verify_failed'], 'evidence integrity check')} failed.",
                            "Open the Evidence vault, find the failed item and report it to the CSO; the file may have been changed."))
    who = lambda a: ", ".join(f"{u} ({n})" for u, n in by_person.get(a, Counter()).most_common(4)) or "—"  # noqa: E731
    sections.append(Section("Evidence vault", "Sealed evidence and every time it was opened or changed.", ["Activity", "Count", "By"],
                            [["Sealed", act["evidence_sealed"], who("evidence_sealed")], ["Downloaded", act["evidence_downloaded"], who("evidence_downloaded")],
                             ["Exported copies (not kept)", act["evidence_exported"], who("evidence_exported")],
                             ["Legal hold changed", act["evidence_hold"], who("evidence_hold")],
                             ["Integrity check failed", act["evidence_verify_failed"], who("evidence_verify_failed")]],
                            [0.34, 0.12, 0.54]))
    sections.append(Section("Data that left the system", "Downloads and exports of footage and logs this period.", ["What", "Count", "By"],
                            [["Evidence downloads and exports", act["evidence_downloaded"] + act["evidence_exported"],
                              ", ".join(f"{u} ({n})" for u, n in (by_person.get("evidence_downloaded", Counter())
                                                                  + by_person.get("evidence_exported", Counter())).most_common(4)) or "—"],
                             ["Viewing log exports (CSV)", act["viewing_log_exported"], who("viewing_log_exported")],
                             ["Reports downloaded", act["report_downloaded"], who("report_downloaded")],
                             ["Reports sent", act["report_sent"], who("report_sent")]], [0.34, 0.12, 0.54]))

    no2fa = sorted(u for u, r, totp, dis, *_ in users if r in ("admin", "cso") and not totp and not dis)
    if no2fa:
        checks.append(Check(ACTION, "Accounts", f"Administrator or CSO accounts without two-factor: {', '.join(no2fa)}.",
                            "Turn on two-factor for these accounts (Settings › Two-factor sign-in)."))
    stale = sorted(u for u, r, totp, dis, last_login, created in users
                   if not dis and r != "guard" and now - (last_login or created) > timedelta(days=90))
    if stale:
        checks.append(Check(ATTENTION, "Accounts", f"Accounts not used for 90 days: {', '.join(stale[:6])}{'…' if len(stale) > 6 else ''}.",
                            "Disable accounts of people who left or no longer need access (Users)."))
    if act["login_failed"] >= 20:
        checks.append(Check(ATTENTION, "Accounts", f"{act['login_failed']} failed sign-ins this period.",
                            "Check the Audit log for guessing from one address; locked accounts unlock after 15 minutes."))
    if not no2fa and not stale:
        checks.append(Check(OK, "Accounts", "Administrators and the CSO use two-factor; no unused accounts."))
    roles_count = Counter(r for u, r, t, dis, *_ in users if not dis)
    arows = [[r, n] for r, n in sorted(roles_count.items())]
    notes = [f"{n_of(act['login'], 'sign-in')}, {act['login_failed']} failed. {n_of(act['lockdown_started'], 'lockdown')} started."]
    if user_changes:
        notes.append("Changes to users: " + "; ".join(f"{at.astimezone(tzinfo):%d %b} {u} {'added' if a == 'user_created' else 'changed'} "
                                                      f"{(det or {}).get('target') or (det or {}).get('username') or 'a user'}"
                                                      for at, u, a, det in user_changes[:12]) + (f"; and {len(user_changes) - 12} more" if len(user_changes) > 12 else "") + ".")
    sections.append(Section("Accounts and access", "Active accounts by role.", ["Role", "Accounts"], arows, [0.5, 0.5], notes))

    order = {ACTION: 0, ATTENTION: 1, OK: 2}
    checks.sort(key=lambda c: order[c.status])
    return Compliance(site_name, label, str(tzinfo), now.astimezone(tzinfo), checks, sections)


# ------------------------------------------------------------------ rendering

def summary(c: Compliance) -> str:
    n = c.counts()
    if n[ACTION]:
        head = f"{n_of(n[ACTION], 'item')} {'needs' if n[ACTION] == 1 else 'need'} action"
    elif n[ATTENTION]:
        head = f"No actions; {n_of(n[ATTENTION], 'item')} {'needs' if n[ATTENTION] == 1 else 'need'} attention"
    else:
        head = "Everything checked is in order"
    first = next((x for x in c.checks if x.status != OK), None)
    return head + (f". First: {first.text}" if first else ".")


def render_pdf(c: Compliance, branding: dict, logo_path: Path | None) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import BaseDocTemplate, Frame, NextPageTemplate, PageTemplate, Paragraph, Spacer
    from .pdf import BODY_W, H, INK, MARGIN, MUTED, W, NumberedCanvas, styles, table
    accent = colors.HexColor(branding.get("accent") or "#2563eb")
    st = styles(accent)
    tone = {OK: colors.HexColor("#15803d"), ATTENTION: colors.HexColor("#b45309"), ACTION: colors.HexColor("#b91c1c")}
    buf = io.BytesIO()
    logo = ImageReader(str(logo_path)) if logo_path and logo_path.suffix.lower() in (".png", ".jpg", ".jpeg") else None
    title = "Compliance and privacy report"

    def first_page(cv, doc):
        from reportlab.lib.units import mm
        cv.saveState()
        cv.setFillColor(accent)
        cv.rect(0, H - 34 * mm, W, 34 * mm, stroke=0, fill=1)
        x = MARGIN
        if logo:
            iw, ih = logo.getSize()
            h = 14 * mm
            w = min(40 * mm, iw * h / ih)
            cv.setFillColor(colors.white)
            cv.roundRect(x - 2 * mm, H - 27 * mm, w + 4 * mm, h + 4 * mm, 2 * mm, stroke=0, fill=1)
            cv.drawImage(logo, x, H - 25 * mm, w, h, mask="auto", preserveAspectRatio=True)
            x += w + 7 * mm
        cv.setFillColor(colors.white)
        cv.setFont("DejaVu-Bold", 16)
        cv.drawString(x, H - 16 * mm, title)
        cv.setFont("DejaVu", 10)
        cv.drawString(x, H - 22.5 * mm, f"{c.site_name}  ·  {c.label}")
        cv.setFont("DejaVu", 7.5)
        cv.drawRightString(W - MARGIN, H - 29 * mm, f"Generated {c.generated_at:%d %b %Y %H:%M} ({c.tz})")
        footer(cv)
        cv.restoreState()

    def later(cv, doc):
        from reportlab.lib.units import mm
        cv.saveState()
        cv.setStrokeColor(accent)
        cv.line(MARGIN, H - 12 * mm, W - MARGIN, H - 12 * mm)
        cv.setFont("DejaVu-Bold", 8)
        cv.setFillColor(INK)
        cv.drawString(MARGIN, H - 10 * mm, f"{title} · {c.label}")
        footer(cv)
        cv.restoreState()

    def footer(cv):
        from reportlab.lib.units import mm
        cv.setFont("DejaVu", 7.5)
        cv.setFillColor(MUTED)
        cv.drawString(MARGIN, 10 * mm, "Confidential: contains personal data. For the CSO, the DPO and management only.")

    from reportlab.lib.units import mm
    doc = BaseDocTemplate(buf, pagesize=(W, H), leftMargin=MARGIN, rightMargin=MARGIN, topMargin=18 * mm, bottomMargin=18 * mm,
                          title=f"{title} – {c.label}", author=c.site_name)
    doc.addPageTemplates([PageTemplate("first", [Frame(MARGIN, 16 * mm, BODY_W, H - 56 * mm, leftPadding=0, rightPadding=0)], onPage=first_page),
                          PageTemplate("later", [Frame(MARGIN, 16 * mm, BODY_W, H - 34 * mm, leftPadding=0, rightPadding=0)], onPage=later)])
    story = [NextPageTemplate("later"), Paragraph(escape(summary(c)), st["lead"]), Paragraph("Checklist", st["h2"])]
    rows = [[Paragraph("<b>Status</b>", st["cell"]), Paragraph("<b>Area</b>", st["cell"]), Paragraph("<b>Finding and what to do</b>", st["cell"])]]
    for x in c.checks:
        rows.append([Paragraph(f'<font color="{tone[x.status].hexval().replace("0x", "#")}"><b>{x.status}</b></font>', st["cell"]),
                     Paragraph(escape(x.area), st["cellb"]),
                     Paragraph(escape(x.text) + (f'<br/><font color="#6b7280">{escape(x.fix)}</font>' if x.fix else ""), st["cell"])])
    story.append(table(rows, [BODY_W * 0.13, BODY_W * 0.17, BODY_W * 0.70]))
    for s in c.sections:
        story.append(Paragraph(escape(s.title), st["h2"]))
        if s.lead:
            story.append(Paragraph(escape(s.lead), st["body"]))
        if s.headers:
            body = [[Paragraph(f"<b>{escape(h)}</b>", st["cell"]) for h in s.headers]]
            body += [[Paragraph(escape(str(v)), st["cell"]) for v in r] for r in s.rows] or [[Paragraph("None this period.", st["cell"])] + [""] * (len(s.headers) - 1)]
            story.append(table(body, [BODY_W * w for w in s.widths]))
        for n in s.notes:
            story.append(Spacer(1, 3))
            story.append(Paragraph(escape(n), st["small"]))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Sources: the platform's audit log, viewing log, evidence vault, legal review record, retention runs and the "
                           "NVRs' daily recording check. Dates in Settings › Compliance are entered by the CSO.", st["small"]))
    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def render_docx(c: Compliance, branding: dict, logo_path: Path | None) -> bytes:
    from docx import Document
    from docx.shared import Cm, Pt, RGBColor
    from .docx_render import _table
    doc = Document()
    for s in doc.sections:
        s.left_margin = s.right_margin = Cm(1.8)
    if logo_path and logo_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        doc.add_picture(str(logo_path), height=Cm(1.4))
    doc.add_heading("Compliance and privacy report", level=1)
    doc.add_paragraph(f"{c.site_name} · {c.label} · generated {c.generated_at:%d %b %Y %H:%M} ({c.tz})")
    doc.add_paragraph(summary(c))
    doc.add_heading("Checklist", level=2)
    colour = {OK: RGBColor(0x15, 0x80, 0x3D), ATTENTION: RGBColor(0xB4, 0x53, 0x09), ACTION: RGBColor(0xB9, 0x1C, 0x1C)}

    def status_cell(x):
        def fill(cell):
            cell.text = ""
            r = cell.paragraphs[0].add_run(x.status)
            r.bold, r.font.size, r.font.color.rgb = True, Pt(8.5), colour[x.status]
        return fill
    _table(doc, ["Status", "Area", "Finding and what to do"],
           [[status_cell(x), x.area, x.text + (f" {x.fix}" if x.fix else "")] for x in c.checks], [2.2, 3.0, 12.2])
    for s in c.sections:
        doc.add_heading(s.title, level=2)
        if s.lead:
            doc.add_paragraph(s.lead)
        if s.headers:
            _table(doc, s.headers, s.rows or [["None this period."] + [""] * (len(s.headers) - 1)], [17.4 * w for w in s.widths])
        for n in s.notes:
            p = doc.add_paragraph(n)
            for r in p.runs:
                r.font.size = Pt(8.5)
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue()
