"""Turn NVR inventories into the compatibility matrix (CSV) and a readable summary (Markdown)."""
from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

GB_PER_MBPS_DAY = 10.8   # 1 Mbps for 24 h is about 10.8 GB (Section 18)
HEADROOM = 1.15

MATRIX_COLUMNS = [
    "nvr_address", "nvr_model", "nvr_firmware", "channel", "name", "camera_ip", "protocol",
    "online", "main_codec", "main_resolution", "main_fps", "main_kbps", "sub_codec",
    "sub_resolution", "sub_fps", "sub_kbps", "smart_events", "recognition_events",
    "provisional_tier", "tier_reason", "tier_override", "flags",
]


def _res(s: dict) -> str:
    return f"{s['width']}x{s['height']}" if s.get("width") and s.get("height") else ""


def matrix_rows(inventories: list[dict]):
    for inv in inventories:
        dev = inv["device"]
        for ch in inv["channels"]:
            main = ch.get("streams", {}).get("main", {})
            sub = ch.get("streams", {}).get("sub", {})
            yield {
                "nvr_address": inv["address"],
                "nvr_model": dev["model"],
                "nvr_firmware": f"{dev['firmware']} {dev['firmware_date']}".strip(),
                "channel": ch["id"],
                "name": ch.get("name", ""),
                "camera_ip": ch.get("camera_ip", ""),
                "protocol": ch.get("protocol", ""),
                "online": {True: "yes", False: "no"}.get(ch.get("online"), "?"),
                "main_codec": main.get("codec", ""),
                "main_resolution": _res(main),
                "main_fps": main.get("fps", ""),
                "main_kbps": main.get("bitrate_kbps", ""),
                "sub_codec": sub.get("codec", ""),
                "sub_resolution": _res(sub),
                "sub_fps": sub.get("fps", ""),
                "sub_kbps": sub.get("bitrate_kbps", ""),
                "smart_events": " ".join(e for e in ch.get("event_types", []) if e not in ("vmd", "videoloss")),
                "recognition_events": " ".join(ch.get("recognition_events", [])),
                "provisional_tier": ch.get("tier", ""),
                "tier_reason": ch.get("tier_reason", ""),
                "tier_override": "",
                "flags": "; ".join(ch.get("flags", [])),
            }


def write_matrix(inventories: list[dict], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=MATRIX_COLUMNS)
        w.writeheader()
        w.writerows(matrix_rows(inventories))


def nvr_numbers(inv: dict, target_days: int) -> dict:
    main_kbps = sum((ch.get("streams", {}).get("main", {}).get("bitrate_kbps") or 0)
                    for ch in inv["channels"])
    sub_kbps = sum((ch.get("streams", {}).get("sub", {}).get("bitrate_kbps") or 0)
                   for ch in inv["channels"])
    capacity_gb = sum(d["capacity_gb"] or 0 for d in inv["storage"])
    main_mbps = main_kbps / 1000
    daily_gb = main_mbps * GB_PER_MBPS_DAY
    return {
        "channels": len(inv["channels"]),
        "online": sum(1 for c in inv["channels"] if c.get("online")),
        "main_mbps": round(main_mbps, 1),
        "sub_mbps": round(sub_kbps / 1000, 1),
        "capacity_tb": round(capacity_gb / 1024, 1),
        "retention_days": round(capacity_gb / daily_gb, 1) if daily_gb else None,
        "needed_tb": round(daily_gb * target_days * HEADROOM / 1024, 1),
        "tiers": Counter(c.get("tier", "unknown") for c in inv["channels"]),
    }


def write_summary(inventories: list[dict], path: Path, *, target_days: int, bandwidth_limit_mbps: float) -> None:
    lines = ["# NVR probe summary", "",
             f"Targets: {target_days} days of recording; incoming bandwidth limit "
             f"{bandwidth_limit_mbps:g} Mbps per NVR (check the datasheet for each model).",
             "Tiers are provisional: confirm them in PoC step 13 and fill in `tier_override` in the matrix.",
             ""]
    totals: Counter[str] = Counter()
    for inv in inventories:
        dev, t = inv["device"], inv["time"]
        n = nvr_numbers(inv, target_days)
        totals.update(n["tiers"])
        lines += [f"## {dev['name'] or inv['address']} ({inv['address']})", "",
                  f"- Model: {dev['model'] or '?'}; firmware {dev['firmware'] or '?'} {dev['firmware_date']}",
                  f"- Serial: {dev['serial'] or '?'}; time mode {t['mode'] or '?'}, timezone {t['timezone'] or '?'}",
                  f"- Channels: {n['channels']} configured, {n['online']} online",
                  f"- Tiers: " + (", ".join(f"{k} {v}" for k, v in sorted(n['tiers'].items())) or "none"),
                  f"- Drives: " + (", ".join(f"{d['name'] or d['id']} {d['capacity_gb']} GB {d['status']}"
                                             for d in inv["storage"]) or "none reported"),
                  f"- Recording load (sum of main streams): {n['main_mbps']} Mbps"]
        if n["main_mbps"] > bandwidth_limit_mbps:
            lines.append(f"  - **Over the {bandwidth_limit_mbps:g} Mbps incoming limit.**")
        if n["retention_days"] is not None:
            verdict = "meets" if n["retention_days"] >= target_days else "**does not meet**"
            lines.append(f"- Estimated retention: {n['retention_days']} days with {n['capacity_tb']} TB, "
                         f"which {verdict} the {target_days} day target "
                         f"(needs about {n['needed_tb']} TB with 15% headroom)")
        lines.append(f"- Sub-stream load into the gateway: {n['sub_mbps']} Mbps")
        failed = [p for p, s in inv["endpoint_status"].items() if s != 200]
        if failed:
            lines.append(f"- Endpoints not available ({len(failed)}): " + ", ".join(failed))
        if "events_heard" in inv:
            ev = inv["events_heard"]
            lines.append(f"- Events heard in {ev['seconds']:g} s: " +
                         (", ".join(f"{k} x{v}" for k, v in sorted(ev['counts'].items())) or "none"))
        flagged = [c for c in inv["channels"] if c.get("flags")]
        if flagged:
            lines += ["", "| Ch | Name | Tier | Flags |", "|---|---|---|---|"]
            lines += [f"| {c['id']} | {c.get('name', '')} | {c.get('tier', '')} | {'; '.join(c['flags'])} |"
                      for c in flagged]
        lines.append("")
    lines += ["## All NVRs", "",
              "- Tier totals: " + (", ".join(f"{k} {v}" for k, v in sorted(totals.items())) or "none"),
              f"- Channels needing server AI (S): {totals.get('S', 0)}, about "
              f"{totals.get('S', 0) / 60:.1f} NVIDIA GPUs at 60 channels per GPU (benchmark in PoC step 16)",
              ""]
    path.write_text("\n".join(lines), encoding="utf-8")
