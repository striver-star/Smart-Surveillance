"""Word (.docx) version of a report (python-docx, MIT licence). Same content as the PDF, editable."""
from __future__ import annotations

import io
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from . import charts, narrative
from .data import ReportData

INK, MUTED, SOFT = RGBColor(0x11, 0x18, 0x27), RGBColor(0x6B, 0x72, 0x80), "F6F8FB"


def _rgb(hexcol: str) -> RGBColor:
    h = hexcol.lstrip("#")
    return RGBColor(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _shade(cell, fill: str) -> None:
    tc = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    tc.append(shd)


def _page_field(paragraph, instr: str) -> None:
    run = paragraph.add_run()
    for kind, text in (("begin", None), (None, instr), ("end", None)):
        if kind:
            el = OxmlElement("w:fldChar")
            el.set(qn("w:fldCharType"), kind)
        else:
            el = OxmlElement("w:instrText")
            el.set(qn("xml:space"), "preserve")
            el.text = text
        run._r.append(el)


def _light_borders(table) -> None:
    """Thin horizontal lines only, like the PDF."""
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        if edge in ("left", "right", "insideV"):
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), "4")
            el.set(qn("w:color"), "E5E7EB")
        borders.append(el)
    tblPr.append(borders)


def _row_flag(row, tag: str) -> None:
    trPr = row._tr.get_or_add_trPr()
    el = OxmlElement(f"w:{tag}")
    el.set(qn("w:val"), "true")
    trPr.append(el)


def _table(doc, headers: list[str], rows: list[list], widths_cm: list[float]):
    t = doc.add_table(rows=1, cols=len(headers))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _light_borders(t)
    _row_flag(t.rows[0], "tblHeader")          # repeat on each page
    for c in t.rows[0].cells:                  # never leave the header alone at a page end
        for para in c.paragraphs:
            para.paragraph_format.keep_with_next = True
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        r = c.paragraphs[0].add_run(h)
        r.bold, r.font.size = True, Pt(8.5)
        _shade(c, SOFT)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            if callable(v):
                v(cells[i])
            else:
                cells[i].text = ""
                cells[i].paragraphs[0].add_run(str(v)).font.size = Pt(8.5)
    for row in t.rows:
        _row_flag(row, "cantSplit")
        for i, w in enumerate(widths_cm):
            row.cells[i].width = Cm(w)
    return t


def render(d: ReportData, branding: dict, logo_path: Path | None) -> bytes:
    accent = branding.get("accent") or "#2563eb"
    acc = _rgb(accent)
    title = narrative.title(d)
    doc = Document()
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.PORTRAIT
    sec.page_width, sec.page_height = Cm(21), Cm(29.7)
    for side in ("left_margin", "right_margin"):
        setattr(sec, side, Cm(1.8))
    sec.top_margin, sec.bottom_margin = Cm(1.6), Cm(1.6)
    base = doc.styles["Normal"]
    base.font.name, base.font.size, base.font.color.rgb = "Calibri", Pt(10), INK
    for name, size in (("Heading 1", 18), ("Heading 2", 13)):
        st = doc.styles[name]
        st.font.name, st.font.size, st.font.color.rgb, st.font.bold = "Calibri", Pt(size), acc, True

    # Header and footer on every page
    hp = sec.header.paragraphs[0]
    hp.text = ""
    r = hp.add_run(f"{title} · {d.period.label()}")
    r.font.size, r.font.color.rgb = Pt(8), MUTED
    hp.add_run("\t\t" + d.site_name).font.size = Pt(8)
    fp = sec.footer.paragraphs[0]
    fp.text = ""
    fr = fp.add_run("Confidential: security information. Do not forward outside the organisation.    Page ")
    fr.font.size, fr.font.color.rgb = Pt(7.5), MUTED
    _page_field(fp, "PAGE")
    fp.add_run(" of ").font.size = Pt(7.5)
    _page_field(fp, "NUMPAGES")

    # Title block
    if logo_path and logo_path.suffix.lower() in (".png", ".jpg", ".jpeg"):
        doc.add_picture(str(logo_path), height=Cm(1.4))
    doc.add_heading(title, level=1)
    p = doc.add_paragraph()
    r = p.add_run(f"{d.site_name}  ·  {d.period.label()}")
    r.font.size, r.font.color.rgb = Pt(11), MUTED
    p = doc.add_paragraph()
    r = p.add_run(f"Generated {d.generated_at:%d %b %Y %H:%M} ({d.period.tz.key})")
    r.font.size, r.font.color.rgb = Pt(8), MUTED

    # Headline figures
    c = d.counts
    pct = d.change_pct()
    dev = d.devices.get("nvrs", [])
    total = sum(len(n["channels"]) for n in dev)
    online = sum(1 for n in dev for ch in n["channels"] if ch["online"])
    tiles = [(str(d.total), "Events", "no earlier data" if pct is None else f"{'+' if pct > 0 else '−' if pct < 0 else '±'}{abs(pct)}% vs previous"),
             (str(c.get("critical", 0)), "Critical", f"{c.get('warning', 0)} warnings"),
             (f"{online}/{total}" if total else "–", "Cameras online", "at last check"),
             (str(len(d.locations())), "Locations with events", f"{len(d.repeats())} with repeat alerts")]
    t = doc.add_table(rows=1, cols=4)
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, (v, lab, sub) in enumerate(tiles):
        cell = t.rows[0].cells[i]
        _shade(cell, SOFT)
        cell.text = ""
        r = cell.paragraphs[0].add_run(v)
        r.bold, r.font.size = True, Pt(18)
        q = cell.add_paragraph()
        r = q.add_run(lab + "\n")
        r.bold, r.font.size = True, Pt(8)
        r = q.add_run(sub)
        r.font.size, r.font.color.rgb = Pt(8), MUTED

    doc.add_heading("Summary", level=2)
    for i, para in enumerate(narrative.summary(d)):
        doc.add_paragraph(para).runs[0].font.size = Pt(10.5 if i == 0 else 10)

    for caption, png in charts.for_report(d, accent):
        doc.add_picture(io.BytesIO(png), width=Cm(17.4 if caption != "Comparison" else 10.5))
        doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER

    crit = d.critical()
    doc.add_heading(f"Critical incidents ({len(crit)})", level=2)
    if not crit:
        doc.add_paragraph("No critical incidents in this period.")
    else:
        limit = {"daily": 12, "weekly": 10, "monthly": 8, "custom": 10}[d.period.kind]
        rows = []
        for e in crit[-limit:][::-1]:
            snap = d.snapshot(e)
            when = e["occurred_at"].astimezone(d.period.tz)

            def pic(cell, snap=snap):
                cell.text = ""
                if snap:
                    cell.paragraphs[0].add_run().add_picture(str(snap), width=Cm(4.4))
                else:
                    cell.paragraphs[0].add_run("no snapshot").font.size = Pt(8)
            rows.append([pic, f"{when:%a %d %b %H:%M:%S}\n{e['zone'] or 'No zone'}\n{d.cam(e['camera_id'])}",
                         f"{e['type'].replace('_', ' ').capitalize()}{(' · ' + e['object_class']) if e['object_class'] else ''}\n"
                         f"Confidence {round(100 * e['confidence']) if e['confidence'] else '–'}%\nTier {e['tier']} · {e['source_kind']}"])
        _table(doc, ["Snapshot", "When and where", "What"], rows, [4.8, 7.2, 5.4])
        if len(crit) > limit:
            doc.add_paragraph(f"The {limit} most recent are shown with snapshots; all {len(crit)} are in the register below.").runs[0].font.size = Pt(8)
            doc.add_heading("Incident register", level=2)
            reg = [[f"{e['occurred_at'].astimezone(d.period.tz):%d %b %H:%M}", e["type"].replace("_", " "),
                    f"{e['zone'] or ''} · {d.cam(e['camera_id'])}", f"{round(100 * e['confidence'])}%" if e["confidence"] else "–"]
                   for e in crit[::-1][:200]]
            _table(doc, ["Time", "Type", "Location", "Conf."], reg, [2.6, 3.0, 10.2, 1.6])

    locs = d.locations()[:10]
    if locs:
        doc.add_heading("Busiest locations", level=2)
        _table(doc, ["Location", "Events", "Critical"], [[l, n, k] for l, n, k in locs], [12.6, 2.4, 2.4])
        reps = d.repeats()
        if reps:
            doc.add_paragraph("Repeat alerts (3 or more at the same place): " + "; ".join(f"{l} ({n})" for l, n in reps[:6])).runs[0].font.size = Pt(8)

    doc.add_heading("Device health", level=2)
    if not dev:
        doc.add_paragraph("No device data on the server yet.")
    else:
        rows = []
        for n in dev:
            bad = [f"{x['name']} {x['status']}" for x in n["disks"] if (x.get("status") or "ok").lower() not in ("ok", "normal", "notexist", "idle")]
            rows.append([f"{n['name']}\n{n['address']}", f"{n['model']}\n{n['firmware']}", f"{n['online']} / {n['total']}",
                         ", ".join(bad) or "OK", n.get("time_mode") or "?"])
        _table(doc, ["NVR", "Model and firmware", "Cameras online", "Drives", "Clock"], rows, [3.4, 5.6, 2.6, 3.6, 2.2])
        off = [(n["name"], ch) for n in dev for ch in n["channels"] if ch["online"] is False]
        if off:
            doc.add_paragraph(f"Offline cameras ({len(off)}): " + "; ".join(f"{ch['name']} ({nv} ch {ch['channel']}, {ch['ip']})" for nv, ch in off)).runs[0].font.size = Pt(8)

    doc.add_heading("Open items and recommendations", level=2)
    items = d.open_items()
    for it in items or ["No open items."]:
        doc.add_paragraph(it, style="List Number" if items else None)

    probe = d.devices.get("probed_at")
    p = doc.add_paragraph()
    r = p.add_run("Sources: events from the platform's AI workers and cameras; device health from the probe of "
                  f"{probe[:16].replace('T', ' ') if probe else 'unknown date'}; messages from the delivery log. Times are local.")
    r.font.size, r.font.color.rgb = Pt(8), MUTED
    doc.core_properties.title = f"{title} – {d.period.label()}"
    doc.core_properties.author = d.site_name
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
