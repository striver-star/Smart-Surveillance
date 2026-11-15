"""Data for the web console: branding, live camera list, devices and the overview.

Devices come from the latest probe files on the server (HSS_PROBE_DIR, read-only): hss-probe's
inventory.json and hss-cameras' cameras/cameras.json. They are real site data but a snapshot,
so every answer says when it was taken. A device health service replaces this in Phase 3.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

router = APIRouter(tags=["console"])
ANY_ROLE = ("admin", "cso", "operator", "management")
LOGO_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/svg+xml": "svg", "image/webp": "webp"}
MAX_LOGO = 512 * 1024


def _data_dir() -> Path:
    d = Path(os.environ.get("HSS_DATA_DIR", "/data")) / "branding"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_branding() -> dict:
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'branding'").fetchone()
    b = {"site_name": "HSS Security Platform", "accent": "#2563eb", "logo": None}
    if row:
        b.update(row[0])
    return b


@router.get("/branding")
def branding() -> dict:
    """Public: the login page shows the site name and logo."""
    b = get_branding()
    return {"site_name": b["site_name"], "accent": b["accent"], "has_logo": bool(b.get("logo"))}


@router.get("/branding/logo")
def branding_logo() -> Response:
    b = get_branding()
    if not b.get("logo"):
        raise HTTPException(status_code=404, detail="no logo")
    path = _data_dir() / b["logo"]["file"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="no logo")
    # An SVG is served as an inert image: no scripts, nothing loaded from elsewhere.
    return Response(path.read_bytes(), media_type=b["logo"]["type"],
                    headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox",
                             "X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"})


class BrandingIn(BaseModel):
    site_name: str = Field(min_length=1, max_length=60)
    accent: str = Field(pattern=r"^#[0-9a-fA-F]{6}$")
    logo_data_url: str | None = Field(default=None, max_length=800_000)   # data:image/png;base64,...
    remove_logo: bool = False


@router.put("/branding")
def set_branding(body: BrandingIn, request: Request, admin: dict = Depends(require("admin"))) -> dict:
    b = get_branding()
    b.update(site_name=body.site_name.strip(), accent=body.accent)
    if body.remove_logo:
        b["logo"] = None
    elif body.logo_data_url:
        m = re.match(r"^data:([\w/+.-]+);base64,(.+)$", body.logo_data_url, re.S)
        if not m or m.group(1) not in LOGO_TYPES:
            raise HTTPException(status_code=422, detail="Logo must be PNG, JPEG, WebP or SVG.")
        try:
            data = base64.b64decode(m.group(2), validate=True)
        except binascii.Error as exc:
            raise HTTPException(status_code=422, detail="Logo is not valid base64.") from exc
        if len(data) > MAX_LOGO:
            raise HTTPException(status_code=422, detail="Logo must be 512 KB or smaller.")
        name = f"logo.{LOGO_TYPES[m.group(1)]}"
        (_data_dir() / name).write_bytes(data)
        b["logo"] = {"file": name, "type": m.group(1)}
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('branding', %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(b),))
    audit("branding_changed", user_id=admin["id"], username=admin["username"], ip=client_ip(request),
          site_name=b["site_name"], logo=bool(b.get("logo")))
    return branding()


# ------------------------------------------------------------------ live view

@router.get("/live/paths")
def live_paths(_: dict = Depends(require("admin", "cso", "operator"))) -> list[dict]:
    """Camera paths configured in the gateway (names only; source URLs hold passwords and stay hidden)."""
    url = os.environ.get("HSS_GATEWAY_API", "http://gateway:9997")
    names: set[str] = set()
    try:
        for endpoint in ("/v3/config/paths/list", "/v3/paths/list"):   # configured cameras + streams being published
            r = httpx.get(f"{url}{endpoint}", params={"itemsPerPage": 1000}, timeout=5)
            r.raise_for_status()
            names |= {i["name"] for i in r.json().get("items", []) if i.get("name")}
    except httpx.HTTPStatusError as exc:
        hint = (" (the gateway refused the request: recreate it with 'docker compose up -d --force-recreate gateway' so it loads "
                "gateway/mediamtx.yml)" if exc.response.status_code in (401, 403) else "")
        raise HTTPException(status_code=502, detail=f"gateway answered {exc.response.status_code}{hint}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=f"gateway not reachable: {exc.__class__.__name__}") from exc
    # Skip catch-all and regular-expression path entries (all, all_others, ~...).
    names = sorted(n for n in names if n not in ("all", "all_others") and not n.startswith("~"))
    return [{"path": n, "nvr": n.split("-")[0], "label": n} for n in names]


# ------------------------------------------------------------------ devices (from the probe files)

def _probe_dir() -> Path:
    return Path(os.environ.get("HSS_PROBE_DIR", "/probe"))


def _mtime(p: Path) -> str | None:
    return datetime.fromtimestamp(p.stat().st_mtime, timezone.utc).isoformat() if p.exists() else None


def load_devices() -> dict:
    inv_path, cam_path = _probe_dir() / "inventory.json", _probe_dir() / "cameras" / "cameras.json"
    nvrs, cameras = [], {}
    if cam_path.exists():
        for s in json.loads(cam_path.read_text(encoding="utf-8")):
            for c in s.get("cameras", []):
                cameras[(c["nvr"], int(c["channel"]))] = c
    if inv_path.exists():
        for inv in json.loads(inv_path.read_text(encoding="utf-8")):
            disks = inv.get("storage", [])
            chans = []
            for ch in inv.get("channels", []):
                cam = cameras.get((inv["address"], int(ch["id"])), {})
                main = (ch.get("streams") or {}).get("main") or {}
                chans.append({
                    "channel": ch["id"], "name": ch.get("name") or f"Channel {ch['id']}", "ip": ch.get("camera_ip", ""),
                    "online": ch.get("online"), "tier": cam.get("tier") or ch.get("tier", "?"),
                    "model": cam.get("model", ""), "firmware": cam.get("firmware", ""), "class": cam.get("class", ""),
                    "clock_drift_s": cam.get("clock_drift_s"),
                    "stream": " ".join(x for x in (main.get("codec") or "",
                                                   f"{main['width']}x{main['height']}" if main.get("width") else "",
                                                   f"{round(main['bitrate_kbps'] / 1024, 1):g} Mbps" if main.get("bitrate_kbps") else "") if x),
                    "flags": ch.get("flags", []),
                })
            nvrs.append({
                "address": inv["address"], "name": inv["device"].get("name") or inv["address"],
                "model": inv["device"].get("model", ""), "firmware": inv["device"].get("firmware", ""),
                "time_mode": (inv.get("time") or {}).get("mode", ""),
                "channels": chans, "online": sum(1 for c in chans if c["online"]), "total": len(chans),
                "disks": [{"name": d.get("name") or d.get("id"), "capacity_gb": d.get("capacity_gb"),
                           "status": d.get("status")} for d in disks],
                "disk_problem": any((d.get("status") or "ok").lower() not in ("ok", "normal", "notexist", "idle") for d in disks),
            })
    live_at = merge_live(nvrs)
    return {"source": "live" if live_at else "probe files", "live_checked_at": live_at,
            "probed_at": _mtime(inv_path), "cameras_surveyed_at": _mtime(cam_path),
            "nvrs": nvrs}


def merge_live(nvrs: list[dict]) -> str | None:
    """Overlay the edge service's live health (checked every minute) on the probe data.
    NVRs the probe never saw are added from the live data. Returns the latest check time, if any."""
    try:
        from .devices import live_health
        live = live_health()
    except Exception:          # the table may not exist yet on a fresh database
        return None
    if not live:
        return None
    known = {n["address"]: n for n in nvrs}
    for addr, h in live.items():
        n = known.get(addr)
        if n is None:
            n = {"address": addr, "name": h.get("name") or addr, "model": h.get("model", ""), "firmware": h.get("firmware", ""),
                 "time_mode": h.get("time_mode", ""), "channels": [], "disks": []}
            nvrs.append(n)
            known[addr] = n
        n["reachable"] = h["reachable"]
        n["live_checked_at"] = h["checked_at"].isoformat()
        if h.get("name"):
            n["name"] = h["name"]
        for k in ("model", "firmware", "time_mode"):
            if h.get(k):
                n[k] = h[k]
        by_id = {c["channel"]: c for c in n["channels"]}
        for c in h.get("channels", []):
            ch = by_id.get(c["id"])
            if ch is None:
                ch = {"channel": c["id"], "name": c.get("name") or f"Channel {c['id']}", "ip": c.get("ip", ""), "tier": "?",
                      "model": "", "firmware": "", "class": "", "clock_drift_s": None, "stream": "", "flags": []}
                n["channels"].append(ch)
            ch["online"] = None if not h["reachable"] else c.get("online")
            if c.get("name"):
                ch["name"] = c["name"]
        n["channels"].sort(key=lambda c: c["channel"])
        if h.get("disks"):
            n["disks"] = [{"name": d.get("name"), "capacity_gb": d.get("capacity_gb"), "status": d.get("status")} for d in h["disks"]]
        n["online"] = sum(1 for c in n["channels"] if c["online"])
        n["total"] = len(n["channels"])
        n["disk_problem"] = any((d.get("status") or "ok").lower() not in ("ok", "normal", "notexist", "idle") for d in n["disks"])
    return max(h["checked_at"] for h in live.values()).isoformat()


@router.get("/devices")
def devices(_: dict = Depends(require(*ANY_ROLE))) -> dict:
    return load_devices()


# ------------------------------------------------------------------ overview

@router.get("/overview")
def overview(user: dict = Depends(require(*ANY_ROLE))) -> dict:
    dev = load_devices()
    with connect() as conn:
        sev = dict(conn.execute("SELECT severity, count(*) FROM events WHERE occurred_at > now() - interval '24 hours' "
                                "GROUP BY severity").fetchall())
        walls = conn.execute("SELECT count(*), count(*) FILTER (WHERE last_seen > now() - interval '60 seconds') "
                             "FROM wall_nodes").fetchone()
        gw = conn.execute("SELECT status, at FROM gateway_events ORDER BY at DESC LIMIT 1").fetchone()
        sent = conn.execute("SELECT count(*), count(*) FILTER (WHERE status IN ('sent', 'delivered', 'read')) "
                            "FROM deliveries WHERE created_at > now() - interval '7 days' AND status <> 'skipped'").fetchone()
    return {
        "user": user["username"],
        "events_24h": {"critical": sev.get("critical", 0), "warning": sev.get("warning", 0), "info": sev.get("info", 0)},
        "walls": {"total": walls[0], "online": walls[1]},
        "whatsapp": {"status": gw[0] if gw else "unknown", "since": gw[1] if gw else None,
                     "sent_7d": sent[1], "attempts_7d": sent[0]},
        "devices": {"nvrs": len(dev["nvrs"]), "cameras": sum(n["total"] for n in dev["nvrs"]),
                    "online": sum(n["online"] for n in dev["nvrs"]),
                    "nvr_disk_problems": [n["name"] for n in dev["nvrs"] if n["disk_problem"]],
                    "probed_at": dev["probed_at"], "live_checked_at": dev.get("live_checked_at"),
                    "unreachable": [n["name"] for n in dev["nvrs"] if n.get("reachable") is False]},
    }
