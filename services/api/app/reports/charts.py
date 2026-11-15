"""Report charts as PNG bytes (Matplotlib, headless). Shared by the PDF and Word versions."""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from .data import ReportData  # noqa: E402

SEV = [("critical", "#dc2626"), ("warning", "#f59e0b"), ("info", "#38bdf8")]
INK, GRID, MUTED = "#1f2937", "#e5e7eb", "#6b7280"


def _style(ax, title: str) -> None:
    ax.set_title(title, loc="left", fontsize=10.5, color=INK, fontweight="bold", pad=10)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=MUTED, labelsize=8, length=0)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def _stacked(ax, labels: list[str], series: list[dict]) -> None:
    bottom = [0] * len(labels)
    for sev, color in SEV:
        vals = [s.get(sev, 0) for s in series]
        ax.bar(range(len(labels)), vals, bottom=bottom, color=color, width=0.72, label=sev.capitalize(), linewidth=0)
        bottom = [b + v for b, v in zip(bottom, vals)]
    ax.set_xticks(range(len(labels)), labels)
    ax.yaxis.get_major_locator().set_params(integer=True)


def by_hour(d: ReportData, accent: str) -> bytes:
    h = d.by_hour()
    fig, ax = plt.subplots(figsize=(7.2, 2.4))
    _stacked(ax, [f"{x:02d}" for x in range(24)], [h.get(x, {}) for x in range(24)])
    _style(ax, "Events by hour of day")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper right", bbox_to_anchor=(1, 1.22))
    return _png(fig)


def by_day(d: ReportData, accent: str) -> bytes:
    days = d.by_day()
    keys = sorted(days)
    fmt = "%a %d" if len(keys) <= 8 else "%d"
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    _stacked(ax, [k.strftime(fmt) for k in keys], [days[k] for k in keys])
    _style(ax, "Events per day")
    ax.legend(frameon=False, fontsize=8, ncol=3, loc="upper right", bbox_to_anchor=(1, 1.22))
    if len(keys) > 16:
        for i, lab in enumerate(ax.get_xticklabels()):
            lab.set_visible(i % 2 == 0)
    return _png(fig)


def top_locations(d: ReportData, accent: str, n: int = 8) -> bytes | None:
    locs = d.locations()[:n]
    if not locs:
        return None
    labels = [(loc if len(loc) <= 48 else loc[:46] + "…") for loc, _, _ in locs][::-1]
    fig, ax = plt.subplots(figsize=(7.2, 0.42 * len(locs) + 0.7))
    ax.barh(labels, [c for _, c, _ in locs][::-1], color=accent, height=0.6)
    ax.barh(labels, [k for _, _, k in locs][::-1], color="#dc2626", height=0.6, label="of which critical")
    _style(ax, "Busiest locations")
    ax.yaxis.grid(False)
    ax.xaxis.grid(True, color=GRID, linewidth=0.8)
    ax.xaxis.get_major_locator().set_params(integer=True)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    return _png(fig)


def comparison(d: ReportData, accent: str) -> bytes:
    labels = ["Critical", "Warning", "Info"]
    now = [d.counts.get(k.lower(), 0) for k in labels]
    prev = [d.prev_counts.get(k.lower(), 0) for k in labels]
    fig, ax = plt.subplots(figsize=(4.2, 2.4))
    x = range(len(labels))
    ax.bar([i - 0.19 for i in x], prev, width=0.36, color="#cbd5e1", label="Previous")
    ax.bar([i + 0.19 for i in x], now, width=0.36, color=accent, label="This period")
    ax.set_xticks(list(x), labels)
    ax.yaxis.get_major_locator().set_params(integer=True)
    _style(ax, "Compared with the previous period")
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    return _png(fig)


def for_report(d: ReportData, accent: str) -> list[tuple[str, bytes]]:
    """(caption, png) in report order; empty periods get no charts."""
    if not d.total and not d.prev_total:
        return []
    out = []
    if d.period.kind == "daily":
        out.append(("Events by hour", by_hour(d, accent)))
    else:
        out.append(("Events per day", by_day(d, accent)))
        out.append(("Events by hour", by_hour(d, accent)))
    loc = top_locations(d, accent)
    if loc:
        out.append(("Busiest locations", loc))
    if d.period.kind in ("weekly", "monthly"):
        out.append(("Comparison", comparison(d, accent)))
    return out
