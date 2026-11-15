"""PDF version of a report (ReportLab, BSD licence; no system libraries needed)."""
from __future__ import annotations

import io
from pathlib import Path

import matplotlib
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate, PageTemplate, Paragraph,
                                Spacer, Table, TableStyle)
from xml.sax.saxutils import escape

from . import narrative
from .data import ReportData

FONT_DIR = Path(matplotlib.get_data_path()) / "fonts" / "ttf"      # DejaVu ships with Matplotlib
for name, file in (("DejaVu", "DejaVuSans.ttf"), ("DejaVu-Bold", "DejaVuSans-Bold.ttf")):
    if name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(name, str(FONT_DIR / file)))

INK, MUTED, LINE, SOFT = colors.HexColor("#111827"), colors.HexColor("#6b7280"), colors.HexColor("#e5e7eb"), colors.HexColor("#f6f8fb")
SEV_COL = {"critical": colors.HexColor("#dc2626"), "warning": colors.HexColor("#d97706"), "info": colors.HexColor("#0284c7")}
W, H = A4
MARGIN = 16 * mm
BODY_W = W - 2 * MARGIN


def styles(accent):
    base = dict(fontName="DejaVu", textColor=INK, fontSize=9.5, leading=13.5)
    return {
        "body": ParagraphStyle("body", **base, spaceAfter=5),
        "lead": ParagraphStyle("lead", **{**base, "fontSize": 10.5, "leading": 15}, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName="DejaVu-Bold", fontSize=12.5, leading=16, textColor=accent, spaceBefore=12, spaceAfter=6,
                             keepWithNext=1),
        "small": ParagraphStyle("small", **{**base, "fontSize": 8, "leading": 10.5, "textColor": MUTED}),
        "cell": ParagraphStyle("cell", **{**base, "fontSize": 8.5, "leading": 11}),
        "cellb": ParagraphStyle("cellb", **{**base, "fontName": "DejaVu-Bold", "fontSize": 8.5, "leading": 11}),
        "kpi": ParagraphStyle("kpi", fontName="DejaVu-Bold", fontSize=17, leading=20, textColor=INK),
        "kpil": ParagraphStyle("kpil", fontName="DejaVu", fontSize=7.5, leading=9.5, textColor=MUTED),
        "right": ParagraphStyle("right", **{**base, "fontSize": 8, "textColor": MUTED}, alignment=TA_RIGHT),
    }


class NumberedCanvas(rl_canvas.Canvas):
    """Adds 'Page X of Y' once the total is known."""
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._pages = []

    def showPage(self):  # noqa: N802 - ReportLab API
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        n = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont("DejaVu", 7.5)
            self.setFillColor(MUTED)
            self.drawRightString(W - MARGIN, 10 * mm, f"Page {self._pageNumber} of {n}")
            super().showPage()
        super().save()


def render(d: ReportData, branding: dict, logo_path: Path | None) -> bytes:
    accent = colors.HexColor(branding.get("accent") or "#2563eb")
    st = styles(accent)
    title = narrative.title(d)
    buf = io.BytesIO()
    logo = None
    if logo_path and logo_path.suffix.lower() in (".png", ".jpg", ".jpeg"):   # SVG logos appear as text in PDFs
        logo = ImageReader(str(logo_path))

    def first_page(c, doc):
        c.saveState()
        c.setFillColor(accent)
        c.rect(0, H - 34 * mm, W, 34 * mm, stroke=0, fill=1)
        x = MARGIN
        if logo:
            iw, ih = logo.getSize()
            h = 14 * mm
            w = min(40 * mm, iw * h / ih)
            c.setFillColor(colors.white)
            c.roundRect(x - 2 * mm, H - 27 * mm, w + 4 * mm, h + 4 * mm, 2 * mm, stroke=0, fill=1)
            c.drawImage(logo, x, H - 25 * mm, w, h, mask="auto", preserveAspectRatio=True)
            x += w + 7 * mm
        c.setFillColor(colors.white)
        c.setFont("DejaVu-Bold", 16)
        c.drawString(x, H - 16 * mm, title)
        c.setFont("DejaVu", 10)
        c.drawString(x, H - 22.5 * mm, f"{d.site_name}  ·  {d.period.label()}")
        c.setFont("DejaVu", 7.5)
        c.drawRightString(W - MARGIN, H - 29 * mm, f"Generated {d.generated_at:%d %b %Y %H:%M} ({d.period.tz.key})")
        footer(c)
        c.restoreState()

    def later_pages(c, doc):
        c.saveState()
        c.setStrokeColor(accent)
        c.setLineWidth(1.2)
        c.line(MARGIN, H - 12 * mm, W - MARGIN, H - 12 * mm)
        c.setFont("DejaVu-Bold", 8)
        c.setFillColor(INK)
        c.drawString(MARGIN, H - 10 * mm, f"{title} · {d.period.label()}")
        c.setFont("DejaVu", 8)
        c.setFillColor(MUTED)
        c.drawRightString(W - MARGIN, H - 10 * mm, d.site_name)
        footer(c)
        c.restoreState()

    def footer(c):
        c.setFont("DejaVu", 7.5)
        c.setFillColor(MUTED)
        c.drawString(MARGIN, 10 * mm, "Confidential: security information. Do not forward outside the organisation.")

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN, topMargin=18 * mm,
                          bottomMargin=18 * mm, title=f"{title} – {d.period.label()}", author=d.site_name)
    first = Frame(MARGIN, 16 * mm, BODY_W, H - 40 * mm - 16 * mm, id="first", leftPadding=0, rightPadding=0)
    rest = Frame(MARGIN, 16 * mm, BODY_W, H - 18 * mm - 16 * mm, id="rest", leftPadding=0, rightPadding=0)
    doc.addPageTemplates([PageTemplate("first", [first], onPage=first_page), PageTemplate("later", [rest], onPage=later_pages)])
    story = [NextPageTemplate("later")]
    story += kpi_row(d, st, accent)
    story.append(Paragraph("Summary", st["h2"]))
    paras = narrative.summary(d)
    story += [Paragraph(escape(p), st["lead"] if i == 0 else st["body"]) for i, p in enumerate(paras)]

    from . import charts
    for caption, png in charts.for_report(d, branding.get("accent") or "#2563eb"):
        img = ImageReader(io.BytesIO(png))
        iw, ih = img.getSize()
        w = BODY_W if caption != "Comparison" else BODY_W * 0.6
        story.append(Spacer(1, 6))
        story.append(Image(io.BytesIO(png), width=w, height=w * ih / iw))

    crit = d.critical()
    story.append(Paragraph(f"Critical incidents ({len(crit)})", st["h2"]))
    if not crit:
        story.append(Paragraph("No critical incidents in this period.", st["body"]))
    else:
        limit = {"daily": 12, "weekly": 10, "monthly": 8, "custom": 10}[d.period.kind]
        story.append(incident_table(d, crit[-limit:][::-1], st))
        if len(crit) > limit:
            story.append(Paragraph(f"The {limit} most recent are shown with snapshots; all {len(crit)} are in the register below.", st["small"]))
            story.append(Paragraph("Incident register", st["h2"]))
            story.append(register_table(d, crit[::-1][:200], st))

    locs = d.locations()[:10]
    if locs:
        story.append(Paragraph("Busiest locations", st["h2"]))
        rows = [[Paragraph("<b>Location</b>", st["cell"]), Paragraph("<b>Events</b>", st["cell"]), Paragraph("<b>Critical</b>", st["cell"])]]
        rows += [[Paragraph(escape(loc), st["cell"]), str(n), str(c)] for loc, n, c in locs]
        story.append(table(rows, [BODY_W * 0.72, BODY_W * 0.14, BODY_W * 0.14]))
        reps = d.repeats()
        if reps:
            story.append(Spacer(1, 4))
            story.append(Paragraph("Repeat alerts (3 or more at the same place): " + escape("; ".join(f"{l} ({n})" for l, n in reps[:6])), st["small"]))

    story.append(Paragraph("Device health", st["h2"]))
    story += device_section(d, st)

    items = d.open_items()
    story.append(Paragraph("Open items and recommendations", st["h2"]))
    if items:
        story += [Paragraph(f"{i}. {escape(t)}", st["body"]) for i, t in enumerate(items, 1)]
    else:
        story.append(Paragraph("No open items.", st["body"]))

    story.append(Spacer(1, 10))
    probe = d.devices.get("probed_at")
    story.append(Paragraph(
        "Sources: events from the platform's AI workers and cameras; device health from the probe of "
        f"{probe[:16].replace('T', ' ') if probe else 'unknown date'} (live device monitoring arrives in Phase 3); "
        "messages from the delivery log. Times are local.", st["small"]))

    doc.build(story, canvasmaker=NumberedCanvas)
    return buf.getvalue()


def table(rows, widths, header=True) -> Table:
    t = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [("FONT", (0, 0), (-1, -1), "DejaVu", 8.5), ("TEXTCOLOR", (0, 0), (-1, -1), INK),
             ("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LINEBELOW", (0, 0), (-1, -1), 0.4, LINE),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), SOFT), ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE)]
    t.setStyle(TableStyle(style))
    return t


def kpi_row(d: ReportData, st, accent) -> list:
    c = d.counts
    pct = d.change_pct()
    trend = "no earlier data" if pct is None else ("same as before" if pct == 0 else f"{'+' if pct > 0 else '−'}{abs(pct)}% vs previous")
    dev = d.devices.get("nvrs", [])
    total = sum(len(n["channels"]) for n in dev)
    online = sum(1 for n in dev for ch in n["channels"] if ch["online"])
    tiles = [
        (str(d.total), "Events", trend),
        (str(c.get("critical", 0)), "Critical", f"{c.get('warning', 0)} warnings"),
        (f"{online}/{total}" if total else "–", "Cameras online", "at last check"),
        (str(len(d.locations())), "Locations with events", f"{len(d.repeats())} with repeat alerts"),
    ]
    cells = [[Paragraph(v, st["kpi"]), Paragraph(f"<b>{escape(l)}</b><br/>{escape(s)}", st["kpil"])] for v, l, s in tiles]
    t = Table([[Table([[a], [b]], colWidths=[BODY_W / 4 - 6]) for a, b in cells]], colWidths=[BODY_W / 4] * 4)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), SOFT), ("BOX", (0, 0), (-1, -1), 0.6, LINE),
                           ("LINEAFTER", (0, 0), (-2, -1), 0.6, LINE), ("LEFTPADDING", (0, 0), (-1, -1), 8),
                           ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                           ("LINEABOVE", (0, 0), (-1, 0), 2.2, accent)]))
    return [t]


def incident_table(d: ReportData, events: list[dict], st) -> Table:
    rows = [[Paragraph("<b>Snapshot</b>", st["cell"]), Paragraph("<b>When and where</b>", st["cell"]), Paragraph("<b>What</b>", st["cell"])]]
    for e in events:
        snap = d.snapshot(e)
        img = Image(str(snap), width=44 * mm, height=26 * mm, kind="proportional") if snap else Paragraph("no snapshot", st["small"])
        when = e["occurred_at"].astimezone(d.period.tz)
        where = Paragraph(f"<b>{when:%a %d %b %H:%M:%S}</b><br/>{escape(e['zone'] or 'No zone')}<br/>"
                          f"<font color='#6b7280'>{escape(d.cam(e['camera_id']))}</font>", st["cell"])
        what = Paragraph(f"<b>{escape(e['type'].replace('_', ' ').capitalize())}</b>"
                         f"{(' · ' + escape(e['object_class'])) if e['object_class'] else ''}<br/>"
                         f"Confidence {round(100 * e['confidence']) if e['confidence'] else '–'}%<br/>"
                         f"<font color='#6b7280'>Tier {e['tier']} · {escape(e['source_kind'])}</font>", st["cell"])
        rows.append([img, where, what])
    t = table(rows, [48 * mm, BODY_W - 48 * mm - 52 * mm, 52 * mm])
    t.setStyle(TableStyle([("LINEBEFORE", (0, 1), (0, -1), 2.5, SEV_COL["critical"])]))
    return t


def register_table(d: ReportData, events: list[dict], st) -> Table:
    rows = [[Paragraph(f"<b>{h}</b>", st["cell"]) for h in ("Time", "Type", "Location", "Conf.")]]
    for e in events:
        when = e["occurred_at"].astimezone(d.period.tz)
        rows.append([f"{when:%d %b %H:%M}", e["type"].replace("_", " "), Paragraph(escape(f"{e['zone'] or ''} · {d.cam(e['camera_id'])}"), st["cell"]),
                     f"{round(100 * e['confidence'])}%" if e["confidence"] else "–"])
    return table(rows, [26 * mm, 30 * mm, BODY_W - 26 * mm - 30 * mm - 16 * mm, 16 * mm])


def device_section(d: ReportData, st) -> list:
    nvrs = d.devices.get("nvrs", [])
    if not nvrs:
        return [Paragraph("No device data on the server yet.", st["body"])]
    rows = [[Paragraph(f"<b>{h}</b>", st["cell"]) for h in ("NVR", "Model and firmware", "Cameras online", "Drives", "Clock")]]
    for n in nvrs:
        bad = [f"{x['name']} {x['status']}" for x in n["disks"] if (x.get("status") or "ok").lower() not in ("ok", "normal", "notexist", "idle")]
        rows.append([Paragraph(f"<b>{escape(n['name'])}</b><br/><font color='#6b7280'>{escape(n['address'])}</font>", st["cell"]),
                     Paragraph(f"{escape(n['model'])}<br/><font color='#6b7280'>{escape(n['firmware'])}</font>", st["cell"]),
                     f"{n['online']} / {n['total']}",
                     Paragraph(f"<font color='#dc2626'><b>{escape(', '.join(bad))}</b></font>" if bad else "OK", st["cell"]),
                     (n.get("time_mode") or "?").upper() if (n.get("time_mode") or "").lower() == "ntp" else (n.get("time_mode") or "?")])
    out = [table(rows, [34 * mm, 54 * mm, 26 * mm, BODY_W - 34 * mm - 54 * mm - 26 * mm - 22 * mm, 22 * mm])]
    off = [(n["name"], c) for n in nvrs for c in n["channels"] if c["online"] is False]
    if off:
        out.append(Spacer(1, 4))
        out.append(Paragraph(f"Offline cameras ({len(off)}): " + escape("; ".join(f"{c['name']} ({nv} ch {c['channel']}, {c['ip']})" for nv, c in off)), st["small"]))
    return [KeepTogether(out)]
