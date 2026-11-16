import io
import zipfile
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.reports import docx_render, narrative, pdf
from app.reports.data import ReportData, camera_names, period_for
from app.reports.service import due_today

TZ = ZoneInfo("Africa/Lagos")
NOW = datetime(2026, 11, 16, 7, 0, tzinfo=TZ)          # a Monday


def test_periods():
    d = period_for("daily", TZ, now=NOW)
    assert (d.start.date(), d.end.date(), d.label()) == (date(2026, 11, 15), date(2026, 11, 16), "Sunday 15 November 2026")
    w = period_for("weekly", TZ, now=NOW)
    assert (w.start.date(), w.end.date(), w.label()) == (date(2026, 11, 9), date(2026, 11, 16), "9 to 15 November 2026")
    m = period_for("monthly", TZ, now=NOW)
    assert (m.start.date(), m.end.date(), m.label()) == (date(2026, 10, 1), date(2026, 11, 1), "October 2026")
    assert m.previous.start.date() == date(2026, 9, 1) and m.previous.end.date() == date(2026, 10, 1)
    jan = period_for("monthly", TZ, now=datetime(2027, 1, 3, tzinfo=TZ))
    assert (jan.start.date(), jan.end.date()) == (date(2026, 12, 1), date(2027, 1, 1))     # across the year end
    c = period_for("custom", TZ, start=date(2026, 10, 30), end=date(2026, 11, 2))
    assert c.label() == "30 October to 2 November 2026" and len(c.days) == 4
    with pytest.raises(ValueError):
        period_for("custom", TZ, start=date(2026, 11, 2), end=date(2026, 10, 1))


def test_schedule_days(monkeypatch):
    monkeypatch.delenv("HSS_REPORT_KINDS", raising=False)
    assert due_today(date(2026, 11, 16)) == ["daily", "weekly"]              # Monday
    assert due_today(date(2026, 12, 1)) == ["daily", "monthly", "compliance"]  # 1st, a Tuesday
    assert due_today(date(2027, 2, 1)) == ["daily", "weekly", "monthly", "compliance"]  # Monday the 1st
    monkeypatch.setenv("HSS_REPORT_KINDS", "weekly")
    assert due_today(date(2026, 11, 17)) == []


DEVICES = {"probed_at": "2026-11-15T05:00:00+00:00", "nvrs": [{
    "address": "10.1.3.4", "name": "NVR4", "model": "DS-7632NXI-K2/16P", "firmware": "V4.83.005", "time_mode": "manual",
    "online": 2, "total": 3, "disk_problem": True,
    "disks": [{"name": "hdd1", "capacity_gb": None, "status": "notexist"}, {"name": "hdd2", "capacity_gb": 3726, "status": "error"}],
    "channels": [{"channel": 23, "name": "SECURITY CHECK 1", "ip": "10.1.3.9", "online": True, "clock_drift_s": -3},
                 {"channel": 22, "name": "MAIN GATE ENTERANCE", "ip": "10.1.3.112", "online": True, "clock_drift_s": -25200},
                 {"channel": 2, "name": "GATE LEFT WING", "ip": "10.1.3.166", "online": False, "clock_drift_s": None}]}]}


def report_data(kind="weekly", n=12, prev=Counter({"critical": 2, "warning": 2})):
    p = period_for(kind, TZ, now=NOW)
    events = []
    for i in range(n):
        events.append({"id": i, "camera_id": "nvr4-ch23" if i % 3 else "nvr4-ch22", "type": "intrusion", "object_class": "human",
                       "zone": "Perimeter fence" if i % 3 else "Main gate", "severity": ["critical", "warning", "info"][i % 3],
                       "confidence": 0.8, "occurred_at": p.start + timedelta(hours=20 + i), "snapshot_ref": None, "tier": "S",
                       "source_kind": "server_ai"})
    return ReportData(period=p, site_name="Test site", events=events, prev_counts=prev, devices=DEVICES,
                      camera_names=camera_names(DEVICES), walls={"total": 1, "online": 1}, deliveries=Counter({"read": 3}),
                      snapshot_root=Path("/nonexistent"), generated_at=NOW)


def test_camera_names_and_narrative():
    d = report_data()
    assert d.cam("nvr4-ch23") == "SECURITY CHECK 1 (nvr4-ch23)" and d.cam("nvr9-ch01") == "nvr9-ch01"
    text = " ".join(narrative.summary(d))
    assert "12 events for 9 to 15 November 2026: 4 critical, 4 warnings, 4 for information" in text
    assert "200% more than the previous week (4)" in text
    assert "Perimeter fence · SECURITY CHECK 1 (nvr4-ch23) with 8 events" in text
    assert "2 of 3 cameras on 1 NVR were online; NVR4 reported a drive fault" in text
    items = " ".join(d.open_items())
    assert "drive hdd2 reports 'error'" in items and "1 camera offline (GATE LEFT WING)" in items and "clock is wrong" in items
    quiet = " ".join(narrative.summary(report_data("daily", n=0, prev=Counter())))
    assert quiet.startswith("A quiet day: no security events")


def test_pdf_and_docx_render():
    d = report_data("monthly", n=30)
    pdf_bytes = pdf.render(d, {"accent": "#2563eb"}, None)
    assert pdf_bytes.startswith(b"%PDF") and len(pdf_bytes) > 20_000
    docx_bytes = docx_render.render(d, {"accent": "#0f766e"}, None)
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        xml = z.read("word/document.xml").decode()
        assert "Monthly security report" in xml and "Critical incidents (10)" in xml and "Incident register" in xml
        assert sum(n.startswith("word/media/") for n in z.namelist()) >= 3          # charts embedded
