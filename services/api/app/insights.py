"""False alarm tuning dashboard (release 2.0, first batch).

Built from how operators close alerts: "false alarm" against "real incident" (test and duplicate closes
are left out of the rates). For the chosen period it shows the headline figures, the noisiest rules and
cameras, false and real alarms by hour of day, and for each noisy camera or rule a suggested fix worked out
from the pattern of its false alarms. Device alerts (camera offline, drive faults) are left out: they are
not detection noise.
"""
from __future__ import annotations

import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends

from .auth import require
from .db import connect

router = APIRouter(prefix="/insights", tags=["insights"])
DEVICE = ("nvr_offline", "nvr_online", "camera_offline", "camera_online", "drive_fault", "drive_ok", "unit_offline",
          "unit_online", "low_battery", "missed_patrol", "checkpoint_visit")
MIN_ALERTS = 5            # a camera or rule needs this many reviewed alerts before it is judged
NOISY = 0.6               # false alarm share at or above this is "noisy"


def tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))


def rate(false: int, real: int) -> float | None:
    return round(false / (false + real), 3) if false + real else None


def suggest(alerts: list[dict], rule: dict | None) -> list[str]:
    """Fixes to try for one noisy camera or rule, from its false alarms (pure, tested).
    alerts: {reason, type, object_class, hour, created_at (datetime), zone}; rule: the rule's settings, if known."""
    false = [a for a in alerts if a["reason"] == "false_alarm"]
    if not false:
        return []
    tips = []
    n = len(false)
    no_object = sum(1 for a in false if not a["object_class"])
    if no_object / n >= 0.5:
        tips.append("Most false alarms carry no person or vehicle: turn on the human and vehicle filter on the camera (AcuSense), "
                    "or set the rule's Objects to human, vehicle.")
    motion = sum(1 for a in false if a["type"] in ("motion", "vmd"))
    if motion / n >= 0.5:
        tips.append("Plain motion causes most of them: use line crossing or intrusion with a target filter instead of motion.")
    dusk_dawn = sum(1 for a in false if a["hour"] in (5, 6, 7, 17, 18, 19))
    if dusk_dawn / n >= 0.5 and n >= 4:
        tips.append("They bunch at dusk and dawn, when the light changes and the camera switches to infrared: raise the "
                    "detection sensitivity threshold, check the IR switch-over time, or add white light.")
    day = sum(1 for a in false if 7 <= a["hour"] < 18)
    if rule is not None and not rule.get("armed") and day / n >= 0.6:
        tips.append("Most are in the daytime, when the area is busy: arm the rule at night only (for example 18:00 to 06:00).")
    times = sorted(a["created_at"] for a in false)
    quick = sum(1 for x, y in zip(times, times[1:]) if (y - x) <= timedelta(minutes=10))
    if len(times) >= 4 and quick / (len(times) - 1) >= 0.5:
        cd = rule.get("cooldown_s") if rule else None
        tips.append("They come in bursts minutes apart: raise the rule's cool-down" + (f" (now {cd} s)" if cd is not None else "")
                    + " so repeats fold into one alert, and look for something moving in view (a flag, branches, a light).")
    zones = Counter(a["zone"] for a in false if a["zone"])
    if zones:
        z, c = zones.most_common(1)[0]
        if c / n >= 0.7 and len(zones) >= 1 and n >= 4:
            tips.append(f"Nearly all are in '{z}': redraw that detection area to leave out trees, roads or reflections.")
    if not tips:
        tips.append("Watch a few of these alerts in Playback to see what triggers them, then adjust the camera's detection "
                    "area or sensitivity.")
    return tips


def breakdown(rows: list[dict], key: str, rules: dict[str, dict], label_of) -> list[dict]:
    """Per camera or per rule: counts, false alarm rate, and suggestions for the noisy ones (pure, tested)."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[r[key]].append(r)
    out = []
    for k, items in groups.items():
        c = Counter(a["reason"] or "open" for a in items)
        rt = rate(c["false_alarm"], c["real_incident"])
        noisy = rt is not None and rt >= NOISY and c["false_alarm"] + c["real_incident"] >= MIN_ALERTS
        rule = rules.get(k) if key == "rule" else None
        out.append({"key": k, "label": label_of(k), "alerts": len(items), "false": c["false_alarm"], "real": c["real_incident"],
                    "open": c["open"], "rate": rt, "noisy": noisy,
                    "tips": suggest(items, rule) if noisy else [],
                    "recent_false": [{"alert_id": a["id"], "at": a["created_at"].isoformat(), "camera_id": a["camera_id"]}
                                     for a in sorted(items, key=lambda a: a["created_at"], reverse=True) if a["reason"] == "false_alarm"][:3]})
    out.sort(key=lambda x: (x["false"], x["alerts"]), reverse=True)
    return out


@router.get("/false-alarms")
def false_alarms(days: int = 30, _: dict = Depends(require("admin", "cso", "management"))) -> dict:
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    zone = tz()
    with connect() as conn:
        raw = conn.execute(
            "SELECT a.id, a.rule, a.close_reason, a.created_at, a.acknowledged_at, a.status, e.camera_id, e.type, e.object_class, e.zone "
            "FROM alerts a JOIN events e ON e.id = a.event_id WHERE a.created_at >= %s AND NOT (e.type = ANY(%s))",
            (since, list(DEVICE))).fetchall()
        saved = conn.execute("SELECT value FROM settings WHERE key = 'alert_rules'").fetchone()
    rules = {r["name"]: r for r in (saved[0] if saved else [])}
    rows = [{"id": str(i), "rule": rl, "reason": reason, "created_at": at, "ack": ack, "status": st, "camera_id": cam, "type": t,
             "object_class": obj, "zone": z, "hour": at.astimezone(zone).hour} for i, rl, reason, at, ack, st, cam, t, obj, z in raw]
    from .alerts import camera_label
    c = Counter(r["reason"] or "open" for r in rows)
    acks = [(r["ack"] - r["created_at"]).total_seconds() for r in rows if r["ack"]]
    stale = sum(1 for r in rows if r["status"] != "closed" and datetime.now(timezone.utc) - r["created_at"] > timedelta(hours=24))
    hours = [{"hour": h, "false": 0, "real": 0, "other": 0} for h in range(24)]
    for r in rows:
        hours[r["hour"]]["false" if r["reason"] == "false_alarm" else "real" if r["reason"] == "real_incident" else "other"] += 1
    return {
        "days": days, "since": since,
        "kpis": {"alerts": len(rows), "false": c["false_alarm"], "real": c["real_incident"], "test_or_duplicate": c["test"] + c["duplicate"],
                 "other": c["other"], "open": c["open"], "rate": rate(c["false_alarm"], c["real_incident"]),
                 "ack_median_s": round(statistics.median(acks)) if acks else None, "open_over_24h": stale},
        "by_rule": breakdown(rows, "rule", rules, lambda k: k),
        "by_camera": breakdown(rows, "camera_id", rules, lambda k: camera_label(k) or k)[:30],
        "by_hour": hours,
    }


# ------------------------------------------------------------------ incident heat map (release 2.0, second batch)

def heat(rows: list[dict]) -> dict:
    """Counts by place and by weekday x hour (pure, tested). rows: {camera_id, zone, reason, severity, weekday 0=Mon, hour}."""
    grid = [[0] * 24 for _ in range(7)]
    cams: dict[str, Counter] = defaultdict(Counter)
    zones: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        grid[r["weekday"]][r["hour"]] += 1
        for table, key in ((cams, r["camera_id"]), (zones, r["zone"])):
            if not key:
                continue
            c = table[key]
            c["alerts"] += 1
            c["real"] += r["reason"] == "real_incident"
            c["false"] += r["reason"] == "false_alarm"
            c["critical"] += r["severity"] == "critical"
            c[f"h{r['hour']}"] += 1
    def pack(table):
        out = []
        for k, c in table.items():
            peak = max(range(24), key=lambda h: c[f"h{h}"])
            out.append({"key": k, "alerts": c["alerts"], "real": c["real"], "false": c["false"], "critical": c["critical"],
                        "peak_hour": peak if c[f"h{peak}"] else None})
        return sorted(out, key=lambda x: (-x["alerts"], x["key"]))
    return {"grid": grid, "cameras": pack(cams), "zones": pack(zones), "total": len(rows)}


@router.get("/heatmap")
def heatmap(days: int = 30, only: str = "all", severity: str = "", place: str = "", plan_id: int | None = None,
            _: dict = Depends(require("admin", "cso", "operator", "management", "viewer"))) -> dict:
    """Alerts by place on the site plan and by weekday and hour. only: all | real (closed as real incident) |
    not_false (everything except false alarms). place: 'camera:<id>' or 'zone:<name>' narrows the grid."""
    days = max(1, min(days, 365))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    zone_tz = tz()
    sql = ("SELECT e.camera_id, e.zone, a.close_reason, a.severity, a.created_at FROM alerts a JOIN events e ON e.id = a.event_id "
           "WHERE a.created_at >= %s AND NOT (e.type = ANY(%s))")
    args: list = [since, [t for t in DEVICE if t not in ("missed_patrol",)]]
    if only == "real":
        sql += " AND a.close_reason = 'real_incident'"
    elif only == "not_false":
        sql += " AND a.close_reason IS DISTINCT FROM 'false_alarm'"
    if severity in ("warning", "critical"):
        sql += " AND a.severity = %s"
        args.append(severity)
    from .access import allowed, sql as cam_sql
    w, a = cam_sql(_, "e.camera_id")
    sql += w
    args += a
    with connect() as conn:
        raw = conn.execute(sql, args).fetchall()
    rows = []
    for cam, z, reason, sev, at in raw:
        local = at.astimezone(zone_tz)
        rows.append({"camera_id": cam, "zone": z, "reason": reason, "severity": sev, "weekday": local.weekday(), "hour": local.hour})
    out = heat(rows)
    if place:
        kind, _, key = place.partition(":")
        sub = [r for r in rows if (kind == "camera" and r["camera_id"] == key) or (kind == "zone" and r["zone"] == key)]
        out["grid"] = heat(sub)["grid"]
        out["place_total"] = len(sub)
    from .alerts import camera_label
    for c in out["cameras"]:
        c["label"] = camera_label(c["key"]) or c["key"]
    plan = None
    if plan_id:
        from .geo import _plan, list_zones
        p = _plan(plan_id)
        with connect() as conn:
            cams = conn.execute("SELECT camera_id, x, y FROM camera_geo WHERE plan_id = %s", (plan_id,)).fetchall()
        plan = {"id": p["id"], "name": p["name"], "width": p["width"], "height": p["height"],
                "cameras": [{"camera_id": c, "x": x, "y": y} for c, x, y in cams if allowed(_, c)],
                "zones": [{"name": z["name"], "kind": z["kind"], "points": z["points"]} for z in list_zones(plan_id, _) if z["points"]]}
    return {"days": days, "since": since, "timezone": str(zone_tz), "only": only, "severity": severity, "place": place, **out, "plan": plan}
