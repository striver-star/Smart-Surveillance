"""System health for Phase 8: backup reports, the security self-check, the licence, retention.

Retention (daily):
- events older than HSS_EVENT_DAYS (default 365) are deleted with their snapshots and clips, unless
  their alert is still open; sealed evidence is separate and follows its own retention;
- guard and vehicle positions older than HSS_POSITION_DAYS (default 30);
- NVR recordings: the oldest recording on each camera is read from the NVRs (ISAPI search) and compared
  with HSS_RECORDING_DAYS (default 30), the days of video the site must keep.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import licence
from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token

log = logging.getLogger("hss.system")
router = APIRouter(prefix="/system", tags=["system"])
WEAK = ("change-me", "changeme", "password", "admin", "12345", "secret", "test")


def days(name: str, default: int) -> int:
    return int(os.environ.get(name, str(default)))


# ------------------------------------------------------------------ backup reports

class ReportIn(BaseModel):
    kind: str = Field(pattern=r"^(backup|restore_test)$")
    status: str = Field(pattern=r"^(ok|failed)$")
    detail: str = Field(default="", max_length=1000)
    name: str = Field(default="", max_length=100)
    size_bytes: int = 0
    sha256: str = Field(default="", max_length=64)


@router.post("/backup-status", dependencies=[Depends(check_worker_token)])
def backup_status(r: ReportIn) -> dict:
    with connect() as conn:
        conn.execute("INSERT INTO system_reports (kind, status, detail, data) VALUES (%s, %s, %s, %s)",
                     (r.kind, r.status, r.detail, Jsonb({"name": r.name, "size_bytes": r.size_bytes, "sha256": r.sha256})))
    if r.status == "failed":
        try:
            from .notify import send_text_to_topic
            send_text_to_topic("system", f"HSS {r.kind.replace('_', ' ')} FAILED: {r.detail}")
        except Exception:
            log.warning("could not send the %s failure notice", r.kind)
    return {"recorded": True}


def last_report(kind: str, status: str | None = None) -> dict | None:
    with connect() as conn:
        row = conn.execute("SELECT status, detail, data, at FROM system_reports WHERE kind = %s"
                           + (" AND status = %s" if status else "") + " ORDER BY at DESC LIMIT 1",
                           (kind, status) if status else (kind,)).fetchone()
    return dict(zip(["status", "detail", "data", "at"], row)) if row else None


# ------------------------------------------------------------------ security self-check

def check(cid: str, title: str, status: str, detail: str, fix: str = "") -> dict:
    return {"id": cid, "title": title, "status": status, "detail": detail, "fix": fix}


def token_checks(env: dict) -> list[dict]:
    """Shared secrets in .env (pure, tested). Values are never shown, only judged."""
    out = []
    for name, what in (("HSS_WORKER_TOKEN", "Worker and edge token"), ("HSS_WALL_TOKEN", "Wall PC token"),
                       ("HSS_WA_TOKEN", "WhatsApp gateway token")):
        v = env.get(name, "")
        if not v:
            out.append(check(f"token-{name}", f"{what} set", "fail" if name != "HSS_WA_TOKEN" else "warn",
                             f"{name} is empty.", f"Set {name} in .env: openssl rand -hex 32"))
        elif len(v) < 24 or any(w in v.lower() for w in WEAK):
            out.append(check(f"token-{name}", f"{what} strength", "fail", f"{name} is short or a well-known value.",
                             f"Replace it in .env with: openssl rand -hex 32 (and update the wall PCs or gateway that use it)."))
        else:
            out.append(check(f"token-{name}", f"{what} strength", "ok", "Long and random-looking."))
    db = env.get("HSS_DATABASE_URL", "")
    pw = db.split("://", 1)[-1].split("@", 1)[0].split(":", 1)[-1] if "@" in db else ""
    out.append(check("db-password", "Database password", "fail" if len(pw) < 16 or any(w in pw.lower() for w in WEAK) else "ok",
                     "Short or well-known." if len(pw) < 16 or any(w in pw.lower() for w in WEAK) else "Long and not a default.",
                     "Change POSTGRES_PASSWORD (docs/hardening.md explains how to change it on a running database)."))
    if env.get("HSS_ADMIN_TOKEN"):
        out.append(check("admin-token", "Temporary admin token removed", "warn", "HSS_ADMIN_TOKEN is still set; it bypasses sign-in for scripts.",
                         "Remove HSS_ADMIN_TOKEN from .env and recreate the API, unless a script still needs it."))
    else:
        out.append(check("admin-token", "Temporary admin token removed", "ok", "Not set."))
    return out


def age_check(cid: str, title: str, rep: dict | None, max_age: timedelta, now: datetime, fix: str, missing_status: str = "fail") -> dict:
    if not rep:
        return check(cid, title, missing_status, "Never reported.", fix)
    age = now - rep["at"]
    if rep["status"] != "ok":
        return check(cid, title, "fail", f"Last run failed {age.days} day(s) ago: {rep['detail']}", fix)
    if age > max_age:
        return check(cid, title, "fail" if missing_status == "fail" else "warn", f"Last success {age.days} days ago.", fix)
    return check(cid, title, "ok", f"{rep['at']:%d %b %Y %H:%M} UTC: {rep['detail']}")


def run_checks() -> list[dict]:
    now = datetime.now(timezone.utc)
    out = token_checks(dict(os.environ))
    with connect() as conn:
        no2fa = [u for (u,) in conn.execute("SELECT username FROM users WHERE role IN ('admin', 'cso') AND NOT disabled AND NOT totp_enabled").fetchall()]
        stale = [u for (u,) in conn.execute("SELECT username FROM users WHERE NOT disabled AND coalesce(last_login_at, created_at) < now() - interval '90 days'").fetchall()]
        failed = conn.execute("SELECT count(*) FROM audit_log WHERE action = 'login_failed' AND at > now() - interval '24 hours'").fetchone()[0]
        admin_nvrs = [a for (a,) in conn.execute("SELECT alias FROM nvrs WHERE lower(username) = 'admin'").fetchall()]
        bad_tests = [a for (a,) in conn.execute("SELECT alias FROM nvrs WHERE enabled AND test_ok IS false").fetchall()]
        nvr_count = conn.execute("SELECT count(*) FROM nvrs WHERE enabled").fetchone()[0]
        stale_health = conn.execute("SELECT count(*) FROM device_health WHERE checked_at > now() - interval '5 minutes'").fetchone()[0]
    out.append(check("2fa", "Two-factor for administrators and the CSO", "fail" if no2fa else "ok",
                     f"Without two-factor: {', '.join(no2fa)}." if no2fa else "All have it on.", "Each signs in and turns it on under Settings."))
    out.append(check("stale-users", "No unused accounts", "warn" if stale else "ok",
                     f"Not signed in for 90 days: {', '.join(stale[:8])}." if stale else "Every account was used in the last 90 days.",
                     "Disable accounts that are no longer needed (Users)."))
    out.append(check("failed-logins", "Failed sign-ins, last 24 hours", "warn" if failed > 20 else "ok", f"{failed} failed sign-ins.",
                     "Check the Audit log for where they come from."))
    out.append(check("nvr-users", "NVRs use a dedicated user", "warn" if admin_nvrs else "ok",
                     f"Using the NVR admin account: {', '.join(admin_nvrs)}." if admin_nvrs else "No NVR uses its admin account.",
                     "Create a limited NVR user (docs/edge.md) and edit the NVR in Devices."))
    out.append(check("nvr-tests", "NVR logins work", "warn" if bad_tests else "ok",
                     f"Last connection test failed: {', '.join(bad_tests)}." if bad_tests else "All pass.", "Devices › Edit › Test and save."))
    if nvr_count:
        out.append(check("edge", "Edge service checking NVRs", "ok" if stale_health else "fail",
                         "Health reported in the last 5 minutes." if stale_health else "No NVR health in the last 5 minutes.",
                         "docker compose --profile edge up -d; docker compose logs edge"))
    try:
        from .console import load_devices
        dev = load_devices()
        disks = [n["name"] for n in dev["nvrs"] if n.get("disk_problem")]
        drift = sum(1 for n in dev["nvrs"] for c in n["channels"] if c.get("clock_drift_s") is not None and abs(c["clock_drift_s"]) > 30)
        out.append(check("drives", "NVR drives healthy", "fail" if disks else "ok", f"Drive fault on {', '.join(disks)}." if disks else "No drive faults.",
                         "Replace the drive; recordings on it are at risk."))
        out.append(check("clocks", "Camera clocks correct", "warn" if drift else "ok", f"{drift} camera clock(s) off by more than 30 s." if drift else "No large drift found.",
                         "Set every NVR and camera to NTP (docs/hardening.md)."))
    except Exception as exc:
        out.append(check("devices", "Device data", "warn", f"Couldn't read device data ({exc.__class__.__name__})."))
    short = retention_short()
    target = days("HSS_RECORDING_DAYS", 30)
    if short is not None:
        out.append(check("recording-days", f"NVRs keep {target} days of video", "warn" if short else "ok",
                         f"{len(short)} camera(s) hold less: {', '.join(short[:6])}{'…' if len(short) > 6 else ''}." if short else "Every checked camera holds enough.",
                         "Add drive space, lower the bitrate, or record on events only for less important cameras."))
    out.append(age_check("backup", "Daily backup", last_report("backup"), timedelta(hours=36), now,
                         "Set up tools/backup/hss-backup.sh with cron (docs/backup.md)."))
    out.append(age_check("restore-test", "Restore test in the last 35 days", last_report("restore_test"), timedelta(days=35), now,
                         "Run tools/backup/hss-restore.sh --test (docs/backup.md).", missing_status="warn"))
    try:
        from .evidence import chain_status
        ok, detail = chain_status()
        out.append(check("custody", "Evidence custody log intact", "ok" if ok else "fail", detail, "Keep the server as it is and investigate."))
    except Exception:
        pass
    usage = shutil.disk_usage(os.environ.get("HSS_DATA_DIR", "/data"))
    free = usage.free / usage.total
    out.append(check("disk", "Server disk space", "fail" if free < 0.10 else "warn" if free < 0.20 else "ok",
                     f"{free:.0%} free ({usage.free / 1e9:.0f} GB).", "Free space or add storage; backups and evidence need room."))
    vault_env = bool(os.environ.get("HSS_VAULT_KEY"))
    out.append(check("vault-key", "Vault key backed up", "ok" if last_report("backup", "ok") else "warn",
                     ("Key in .env" if vault_env else "Key file in the API data volume") + "; it is inside each backup.",
                     "Run backups, and keep the backup passphrase offline."))
    st = licence.status()
    out.append(check("licence", "Licence", {"licensed": "ok", "not_set_up": "ok", "grace": "warn"}.get(st["state"], "fail"), st["summary"],
                     "Settings › Licence: send the installation id to the vendor and load the licence file."))
    try:
        from .legal import status as legal_status
        ls = legal_status()
        if ls.get("expires_at") and ls["expires_at"] - now < timedelta(days=30):
            out.append(check("legal", "Face and plate legal review", "warn", f"Acceptance expires {ls['expires_at']:%d %b %Y}.",
                             "Review the DPIA and accept the review again before it expires."))
    except Exception:
        pass
    return out


@router.get("/security")
def security(_: dict = Depends(require("admin", "cso"))) -> dict:
    checks = run_checks()
    order = {"fail": 0, "warn": 1, "ok": 2}
    checks.sort(key=lambda c: order[c["status"]])
    counts = {s: sum(1 for c in checks if c["status"] == s) for s in order}
    return {"checks": checks, "counts": counts, "checked_at": datetime.now(timezone.utc),
            "backups": {"last": last_report("backup"), "last_ok": last_report("backup", "ok"), "restore_test": last_report("restore_test")},
            "retention": {"event_days": days("HSS_EVENT_DAYS", 365), "position_days": days("HSS_POSITION_DAYS", 30),
                          "recording_days": days("HSS_RECORDING_DAYS", 30), "last_run": last_report("retention")}}


# ------------------------------------------------------------------ licence

@router.get("/licence")
def get_licence(_: dict = Depends(require("admin", "cso", "management"))) -> dict:
    return licence.status()


class LicenceIn(BaseModel):
    text: str = Field(min_length=10, max_length=20_000)


@router.put("/licence")
def put_licence(body: LicenceIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    st = licence.load(body.text)
    audit("licence_loaded", user_id=user["id"], username=user["username"], ip=client_ip(request),
          licence=st["licence"]["id"], site=st["licence"]["site"])
    return st


# ------------------------------------------------------------------ retention

def retention_short() -> list[str] | None:
    """Cameras holding fewer days of recording than HSS_RECORDING_DAYS (None = never checked)."""
    target = days("HSS_RECORDING_DAYS", 30)
    with connect() as conn:
        rows = conn.execute("SELECT alias, info->'recording' FROM nvrs WHERE info ? 'recording'").fetchall()
    if not rows:
        return None
    return [f"{alias}-ch{int(ch):02d} ({d['days']} d)" for alias, rec in rows for ch, d in sorted((rec or {}).get("channels", {}).items(), key=lambda x: int(x[0]))
            if d.get("days") is not None and d["days"] < target]


def recording_days(earliest: str | None, now: datetime) -> float | None:
    """Days of video from the NVR's oldest recording time (pure, tested). NVRs write local time with or
    without a zone; a few hours either way doesn't matter for days."""
    if not earliest:
        return None
    try:
        t = datetime.fromisoformat(earliest.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return round((now - t).total_seconds() / 86400, 1)


def check_recordings() -> int:
    from . import vault
    from .isapi import earliest_recordings
    now = datetime.now(timezone.utc)
    with connect() as conn:
        nvrs = conn.execute("SELECT id, address, username, secret, scheme, info FROM nvrs WHERE enabled").fetchall()
    n = 0
    for nid, address, user, secret, scheme, info in nvrs:
        chans = [int(c["id"]) for c in (info or {}).get("channels", [])]
        if not chans:
            continue
        try:
            found = earliest_recordings(address, user, vault.decrypt(secret), chans, scheme=scheme)
        except Exception as exc:
            log.warning("%s: recording check failed: %s", address, exc)
            continue
        rec = {"checked_at": now.isoformat(), "channels": {str(ch): {"earliest": e, "days": recording_days(e, now)} for ch, e in found.items()}}
        with connect() as conn:
            conn.execute("UPDATE nvrs SET info = info || %s WHERE id = %s", (Jsonb({"recording": rec}), nid))
        n += len(found)
    return n


def apply_retention() -> dict:
    event_days, pos_days = days("HSS_EVENT_DAYS", 365), days("HSS_POSITION_DAYS", 30)
    data = Path(os.environ.get("HSS_DATA_DIR", "/data"))
    with connect() as conn:
        old = ("e.occurred_at < now() - %s * interval '1 day' AND NOT EXISTS "
               "(SELECT 1 FROM alerts a WHERE a.event_id = e.id AND a.status <> 'closed')")
        clip_files = [p for (p,) in conn.execute(f"SELECT c.path FROM clips c JOIN events e ON e.id = c.event_id WHERE {old} AND c.path IS NOT NULL",
                                                  (event_days,)).fetchall()]
        rows = conn.execute(
            "DELETE FROM events e WHERE e.occurred_at < now() - %s * interval '1 day' "
            "AND NOT EXISTS (SELECT 1 FROM alerts a WHERE a.event_id = e.id AND a.status <> 'closed') "
            "RETURNING e.snapshot_ref", (event_days,)).fetchall()
        positions = conn.execute("DELETE FROM unit_positions WHERE at < now() - %s * interval '1 day'", (pos_days,)).rowcount
        conn.execute("DELETE FROM legal_reads WHERE opened_at < now() - interval '30 days'")
        views = conn.execute("DELETE FROM view_log WHERE started_at < now() - %s * interval '1 day'", (days("HSS_VIEW_LOG_DAYS", 365),)).rowcount
    files = 0
    for ref in [r for (r,) in rows if r]:
        p = data / ref
        if p.exists():
            p.unlink()
            files += 1
    clips = 0
    for path in clip_files:
        p = data / path
        if p.exists():
            p.unlink()
            clips += 1
    return {"events": len(rows), "snapshots": files, "clips": clips, "positions": positions, "viewing_log": views}


def retention_once() -> dict:
    result = apply_retention()
    try:
        result["recording_channels_checked"] = check_recordings()
    except Exception as exc:
        result["recording_error"] = str(exc)[:200]
    with connect() as conn:
        conn.execute("INSERT INTO system_reports (kind, status, detail, data) VALUES ('retention', 'ok', %s, %s)",
                     (f"{result['events']} old events, {result['snapshots']} snapshots and {result['positions']} positions removed; "
                      f"{result.get('recording_channels_checked', 0)} cameras' recordings checked", Jsonb(result)))
    log.info("retention: %s", result)
    return result


@router.post("/retention/run")
def run_retention(request: Request, user: dict = Depends(require("admin"))) -> dict:
    result = retention_once()
    audit("retention_run", user_id=user["id"], username=user["username"], ip=client_ip(request), **{k: v for k, v in result.items() if isinstance(v, int)})
    return result


async def background_loop() -> None:
    await asyncio.sleep(300)
    while True:
        try:
            await asyncio.to_thread(retention_once)
        except Exception as exc:
            log.warning("retention: %s", exc)
        await asyncio.sleep(24 * 3600)


# ------------------------------------------------------------------ getting started (Phase 9 onboarding)

def onboarding_steps() -> list[dict]:
    """First-run checklist. Each step is worked out from the live system, so it ticks itself off."""
    def q(sql, *args):
        try:
            with connect() as conn:
                return conn.execute(sql, args).fetchone()[0]
        except Exception:
            return None

    def step(sid, title, done, why, link, *, optional=False, detail=""):
        return {"id": sid, "title": title, "done": bool(done), "why": why, "link": link, "optional": optional, "detail": detail}

    brand = q("SELECT value->>'site_name' FROM settings WHERE key = 'branding'")
    nvrs = q("SELECT count(*) FROM nvrs") or 0
    roles = {r: q("SELECT count(*) FROM users WHERE role = %s AND NOT disabled", r) or 0 for r in ("admin", "cso", "operator", "management")}
    admins_2fa = q("SELECT count(*) FROM users WHERE role IN ('admin', 'cso') AND NOT disabled AND totp_enabled") or 0
    no_2fa = q("SELECT count(*) FROM users WHERE role IN ('admin', 'cso') AND NOT disabled AND NOT totp_enabled") or 0
    health = q("SELECT count(*) FROM device_health WHERE checked_at > now() - interval '10 minutes'") or 0
    checked = q("SELECT count(*) FROM nvrs WHERE info ? 'event_checked_at'") or 0
    real_alerts = q("SELECT count(*) FROM alerts a JOIN events e ON e.id = a.event_id WHERE e.source_kind IN ('nvr', 'edge') "
                    "AND e.type NOT IN ('nvr_offline', 'nvr_online', 'camera_offline', 'camera_online', 'drive_fault', 'drive_ok')") or 0
    screens = q("SELECT count(*) FROM wall_screens") or 0
    assigned = q("SELECT count(*) FROM wall_layouts WHERE path LIKE '/wall/?s=%%'") or 0
    wa = q("SELECT status FROM gateway_events ORDER BY at DESC LIMIT 1")
    try:
        from .notify import load_recipients
        recipients = len(load_recipients())
    except Exception:
        recipients = 0
    plans = q("SELECT count(*) FROM site_plans WHERE jsonb_array_length(refs) = 2") or 0
    units = q("SELECT count(*) FROM tracked_units") or 0
    backup = last_report("backup", "ok")
    restore = last_report("restore_test", "ok")
    lic = licence.status()["state"]
    try:
        from .legal import status as legal_status
        legal = legal_status()
    except Exception:
        legal = {}
    fails = sum(1 for c in run_checks() if c["status"] == "fail")
    return [
        step("branding", "Name and logo", brand and brand != "HSS Security Platform",
             "The site name and logo appear on the sign-in page, the console and every report.", "#/settings", detail=brand or ""),
        step("accounts", "People and roles", roles["cso"] and roles["operator"],
             "Each person signs in with their own account: the CSO, the control-room operators, management.", "#/users",
             detail=", ".join(f"{n} {r}" for r, n in roles.items() if n)),
        step("2fa", "Two-factor for administrators and the CSO", admins_2fa and not no_2fa,
             "Their accounts can change everything; a password alone is not enough.", "#/settings",
             detail=f"{no_2fa} still without it" if no_2fa else ""),
        step("nvrs", "Add the NVRs", nvrs, "Each NVR's login is tested and stored encrypted; its cameras appear in live view.", "#/devices",
             detail=f"{nvrs} added" if nvrs else ""),
        step("edge", "Edge service watching the NVRs", health,
             "Live device health, NVR events and clips. Start it with the edge profile (docs/edge.md).", "#/devices"),
        step("event-setup", "Check event settings and walk test", checked and real_alerts,
             "Tick Notify Surveillance Center on the NVRs, then walk past the cameras: real events must raise alerts.", "#/event-setup",
             detail=f"settings read on {checked} NVR(s); {real_alerts} alerts from real camera events"),
        step("walls", "Video wall screens", screens and assigned,
             "One screen per NVR or a rotation, assigned to each TV of the wall PCs.", "#/walls",
             detail=f"{screens} screens, {assigned} TVs assigned"),
        step("whatsapp", "WhatsApp and recipients", wa == "ready" and recipients,
             "Alerts and reports reach the GM, CSO and IT Manager on WhatsApp.", "#/notify",
             detail=f"gateway {wa or 'not seen'}, {recipients} recipient(s)"),
        step("reports", "Scheduled reports", bool(os.environ.get("HSS_REPORT_TIME")),
             "Daily, weekly and monthly reports go out on their own (HSS_REPORT_TIME in .env).", "#/reports",
             detail=os.environ.get("HSS_REPORT_TIME", "")),
        step("map", "Site map", plans, "The plan tied to GPS, cameras placed, zones drawn.", "#/map", optional=True),
        step("gps", "Guard phones", units, "Guards' phones report through Traccar Client; zones and patrols raise alerts.", "#/map", optional=True,
             detail=f"{units} added" if units else ""),
        step("backups", "Backups and a restore test", backup and restore,
             "Daily encrypted backups and a passed restore test (installed by install.sh; docs/backup.md).", "#/security",
             detail=("last backup " + backup["at"].strftime("%d %b")) if backup else ""),
        step("licence", "Licence", lic in ("licensed", "not_set_up"), "Load this installation's licence file.", "#/settings", detail=lic),
        step("face-plate", "Face and plate recognition", legal.get("face") or legal.get("plate"),
             "Only after the legal review, DPIA, signs and notices are in place.", "#/face-plate", optional=True),
        step("security", "Security page all green", fails == 0, "Every failed check fixed.", "#/security",
             detail=f"{fails} failed check(s)" if fails else ""),
    ]


@router.get("/onboarding")
def onboarding(_: dict = Depends(require("admin", "cso"))) -> dict:
    steps = onboarding_steps()
    required = [s for s in steps if not s["optional"]]
    return {"steps": steps, "done": sum(s["done"] for s in required), "total": len(required)}
