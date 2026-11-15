"""The plain-language summary at the top of a report. Rule-based: every sentence states a figure."""
from __future__ import annotations

from .data import ReportData

PERIOD_WORD = {"daily": "day", "weekly": "week", "monthly": "month", "custom": "period"}


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def summary(d: ReportData) -> list[str]:
    """A few short paragraphs, most important first."""
    p, c = d.period, d.counts
    unit = PERIOD_WORD[p.kind]
    paras = []
    if d.total == 0:
        paras.append(f"A quiet {unit}: no security events were recorded for {p.label()}.")
    else:
        parts = [f"{c.get('critical', 0)} critical", f"{plural(c.get('warning', 0), 'warning')}",
                 f"{c.get('info', 0)} for information"]
        s = f"The platform recorded {plural(d.total, 'event')} for {p.label()}: {', '.join(parts)}."
        pct = d.change_pct()
        if pct is None:
            s += f" There were no events in the previous {unit} to compare with."
        elif pct == 0:
            s += f" That is the same as the previous {unit}."
        else:
            s += f" That is {abs(pct)}% {'more' if pct > 0 else 'fewer'} than the previous {unit} ({d.prev_total})."
        paras.append(s)
        locs = d.locations()
        if locs:
            top, n, crit = locs[0]
            s = f"The busiest location was {top} with {plural(n, 'event')}"
            s += f", {crit} of them critical." if crit else "."
            hours = d.busiest_hours()
            if hours and hours[1] >= 2:
                s += f" Activity peaked between {hours[0]:02d}:00 and {(hours[0] + 2) % 24:02d}:00."
            paras.append(s)
        reps = d.repeats()
        if reps:
            paras.append(f"{plural(len(reps), 'location')} raised repeat alerts ({REPEAT_TEXT(reps)}); "
                         "repeats often point to a zone or schedule that needs adjusting.")
    dev = d.devices.get("nvrs", [])
    if dev:
        total = sum(len(n["channels"]) for n in dev)
        online = sum(1 for n in dev for ch in n["channels"] if ch["online"])
        faults = [n["name"] for n in dev for disk in n["disks"]
                  if (disk.get("status") or "ok").lower() not in ("ok", "normal", "notexist", "idle")]
        s = f"At the last device check, {online} of {total} cameras on {plural(len(dev), 'NVR')} were online"
        s += f"; {', '.join(sorted(set(faults)))} reported a drive fault." if faults else " and all NVR drives were healthy."
        paras.append(s)
    else:
        paras.append("Device health was not available for this report (no probe data on the server).")
    sent, failed = sum(v for k, v in d.deliveries.items() if k in ("sent", "delivered", "read")), d.deliveries.get("failed", 0)
    if sent or failed:
        paras.append(f"{plural(sent, 'message')} {'was' if sent == 1 else 'were'} delivered to recipients"
                     + (f" and {failed} failed." if failed else ", with no failures."))
    return paras


def REPEAT_TEXT(reps: list[tuple[str, int]]) -> str:  # noqa: N802 - reads like a sentence helper
    shown = [f"{loc.split(' · ')[0]} {n} times" for loc, n in reps[:3]]
    return "; ".join(shown) + ("; and others" if len(reps) > 3 else "")


def title(d: ReportData) -> str:
    return {"daily": "Daily security report", "weekly": "Weekly security summary",
            "monthly": "Monthly security report", "custom": "Security report"}[d.period.kind]
