"""Collects everything a report needs for one period, plus the previous period for comparison."""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..db import connect

KINDS = ("daily", "weekly", "monthly", "custom")
REPEAT_MIN = 3          # same camera and zone this many times in a period = repeat alert


@dataclass
class Period:
    kind: str
    start: datetime      # local, inclusive
    end: datetime        # local, exclusive
    tz: ZoneInfo

    @property
    def previous(self) -> "Period":
        if self.kind == "monthly":
            prev_end = self.start
            prev_start = (self.start - timedelta(days=1)).replace(day=1)
            return Period(self.kind, prev_start, prev_end, self.tz)
        length = self.end - self.start
        return Period(self.kind, self.start - length, self.start, self.tz)

    @property
    def days(self) -> list[date]:
        d, out = self.start.date(), []
        while d < self.end.date():
            out.append(d)
            d += timedelta(days=1)
        return out

    def label(self) -> str:
        s, e = self.start, self.end - timedelta(seconds=1)
        if self.kind == "daily":
            return f"{s:%A} {s.day} {s:%B %Y}"
        if self.kind == "monthly":
            return s.strftime("%B %Y")
        if s.year == e.year and s.month == e.month:
            return f"{s.day} to {e.day} {e:%B %Y}"
        if s.year == e.year:
            return f"{s.day} {s:%B} to {e.day} {e:%B %Y}"
        return f"{s.day} {s:%B %Y} to {e.day} {e:%B %Y}"


def period_for(kind: str, tz: ZoneInfo, *, on: date | None = None, start: date | None = None,
               end: date | None = None, now: datetime | None = None) -> Period:
    """The period a report covers. Defaults: daily = yesterday, weekly = last Monday to Sunday,
    monthly = last calendar month. `on` picks the day (daily), the week containing it (weekly)
    or the month containing it (monthly). Custom needs start and end dates (end inclusive)."""
    today = (now or datetime.now(tz)).astimezone(tz).date()
    mid = lambda d: datetime.combine(d, time.min, tz)  # noqa: E731
    if kind == "daily":
        d = on or today - timedelta(days=1)
        return Period(kind, mid(d), mid(d + timedelta(days=1)), tz)
    if kind == "weekly":
        d = on or today - timedelta(days=7)
        monday = d - timedelta(days=d.weekday())
        return Period(kind, mid(monday), mid(monday + timedelta(days=7)), tz)
    if kind == "monthly":
        d = on or (today.replace(day=1) - timedelta(days=1))
        first = d.replace(day=1)
        nxt = (first + timedelta(days=32)).replace(day=1)
        return Period(kind, mid(first), mid(nxt), tz)
    if kind == "custom":
        if not start or not end or end < start:
            raise ValueError("custom reports need a start and an end date (end on or after start)")
        if (end - start).days > 92:
            raise ValueError("custom reports cover at most 93 days")
        return Period(kind, mid(start), mid(end + timedelta(days=1)), tz)
    raise ValueError(f"kind must be one of {', '.join(KINDS)}")


@dataclass
class ReportData:
    period: Period
    site_name: str
    events: list[dict]
    prev_counts: Counter
    devices: dict
    camera_names: dict[str, str]
    walls: dict
    deliveries: Counter
    snapshot_root: Path
    generated_at: datetime
    notes: list[str] = field(default_factory=list)

    # ---- derived figures
    @property
    def counts(self) -> Counter:
        return Counter(e["severity"] for e in self.events)

    @property
    def total(self) -> int:
        return len(self.events)

    @property
    def prev_total(self) -> int:
        return sum(self.prev_counts.values())

    def change_pct(self) -> int | None:
        return None if not self.prev_total else round(100 * (self.total - self.prev_total) / self.prev_total)

    def cam(self, camera_id: str) -> str:
        name = self.camera_names.get(camera_id)
        return f"{name} ({camera_id})" if name else camera_id

    def by(self, key) -> list[tuple[str, int]]:
        return Counter(key(e) for e in self.events).most_common()

    def by_hour(self) -> dict[int, Counter]:
        out: dict[int, Counter] = defaultdict(Counter)
        for e in self.events:
            out[e["occurred_at"].astimezone(self.period.tz).hour][e["severity"]] += 1
        return out

    def by_day(self) -> dict[date, Counter]:
        out: dict[date, Counter] = {d: Counter() for d in self.period.days}
        for e in self.events:
            d = e["occurred_at"].astimezone(self.period.tz).date()
            out.setdefault(d, Counter())[e["severity"]] += 1
        return out

    def locations(self) -> list[tuple[str, int, int]]:
        """(location, events, critical) by zone and camera, busiest first."""
        c, crit = Counter(), Counter()
        for e in self.events:
            k = f"{e['zone'] or 'No zone'} · {self.cam(e['camera_id'])}"
            c[k] += 1
            crit[k] += e["severity"] == "critical"
        return [(k, n, crit[k]) for k, n in c.most_common()]

    def repeats(self) -> list[tuple[str, int]]:
        return [(k, n) for k, n, _ in self.locations() if n >= REPEAT_MIN]

    def critical(self) -> list[dict]:
        return [e for e in self.events if e["severity"] == "critical"]

    def busiest_hours(self) -> tuple[int, int] | None:
        """Start hour of the busiest two-hour window, and its count."""
        h = self.by_hour()
        if not h:
            return None
        best = max(range(24), key=lambda x: sum(h.get(x, {}).values()) + sum(h.get((x + 1) % 24, {}).values()))
        return best, sum(h.get(best, {}).values()) + sum(h.get((best + 1) % 24, {}).values())

    def snapshot(self, e: dict) -> Path | None:
        ref = e.get("snapshot_ref")
        if not ref:
            return None
        p = (self.snapshot_root / ref).resolve()
        return p if p.is_relative_to(self.snapshot_root.resolve()) and p.exists() else None

    def open_items(self) -> list[str]:
        """Plain-language action items from the device state and the events."""
        items = []
        for n in self.devices.get("nvrs", []):
            for d in n["disks"]:
                if (d.get("status") or "ok").lower() not in ("ok", "normal", "notexist", "idle"):
                    items.append(f"{n['name']} ({n['address']}): drive {d['name']} reports '{d['status']}'. Replace it; "
                                 "recordings on that drive are at risk.")
            off = [c["name"] for c in n["channels"] if c["online"] is False]
            if off:
                items.append(f"{n['name']}: {len(off)} camera{'s' if len(off) > 1 else ''} offline "
                             f"({', '.join(off[:5])}{'…' if len(off) > 5 else ''}). Check power and network.")
            drift = [c for c in n["channels"] if c.get("clock_drift_s") is not None and abs(c["clock_drift_s"]) > 30]
            if drift:
                items.append(f"{n['name']}: {len(drift)} camera clock{'s are' if len(drift) > 1 else ' is'} wrong, so "
                             "event times from them are off. Set cameras and NVRs to NTP.")
        for loc, n in self.repeats()[:3]:
            items.append(f"Repeat alerts at {loc} ({n} times): check whether the zone, schedule or camera view needs adjusting.")
        if self.walls.get("total") and self.walls.get("online", 0) < self.walls["total"]:
            items.append(f"{self.walls['total'] - self.walls['online']} video wall PC(s) not reporting.")
        failed = self.deliveries.get("failed", 0)
        if failed:
            items.append(f"{failed} message(s) failed to deliver during the period; check the WhatsApp gateway.")
        return items


def camera_names(devices: dict) -> dict[str, str]:
    """Gateway path names (nvr<last IP octet>-ch<NN>) to camera names from the probe."""
    out = {}
    for n in devices.get("nvrs", []):
        m = re.search(r"\.(\d+)$", n.get("address", "").split(":")[0])
        prefix = n.get("alias") or (f"nvr{m.group(1)}" if m else None)
        if not prefix:
            continue
        for c in n["channels"]:
            out[f"{prefix}-ch{int(c['channel']):02d}"] = c["name"]
    return out


def collect(period: Period, *, site_name: str, devices: dict, snapshot_root: Path, camera: str | None = None) -> ReportData:
    cols = "id, camera_id, type, object_class, zone, severity, confidence, occurred_at, snapshot_ref, tier, source_kind"
    where = "occurred_at >= %s AND occurred_at < %s" + (" AND camera_id = %s" if camera else "")
    with connect() as conn:
        cur = conn.execute(f"SELECT {cols} FROM events WHERE {where} ORDER BY occurred_at",
                           (period.start, period.end, *([camera] if camera else [])))
        names = [c.name for c in cur.description]
        events = [dict(zip(names, r)) for r in cur.fetchall()]
        prev = period.previous
        prev_counts = Counter(dict(conn.execute(
            f"SELECT severity, count(*) FROM events WHERE {where} GROUP BY 1",
            (prev.start, prev.end, *([camera] if camera else []))).fetchall()))
        walls = conn.execute("SELECT count(*), count(*) FILTER (WHERE last_seen > now() - interval '60 seconds') "
                             "FROM wall_nodes").fetchone()
        deliveries = Counter(dict(conn.execute(
            "SELECT status, count(*) FROM deliveries WHERE created_at >= %s AND created_at < %s AND status <> 'skipped' "
            "GROUP BY 1", (period.start, period.end)).fetchall()))
    return ReportData(period=period, site_name=site_name, events=events, prev_counts=prev_counts, devices=devices,
                      camera_names=camera_names(devices), walls={"total": walls[0], "online": walls[1]},
                      deliveries=deliveries, snapshot_root=snapshot_root, generated_at=datetime.now(period.tz))
