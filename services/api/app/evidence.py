"""Evidence vault (Phase 3).

Sealing an alert's evidence writes one zip (snapshot, clip, event, alert, timeline and a SHA-256
manifest) to the vault, read-only, and records its SHA-256. The file is never rewritten. Each
download first re-checks the hash, and every action (sealed, downloaded, verified, hold, retention,
deleted) goes into a custody log where each entry carries the hash of the one before it, so a changed
or removed entry shows up when the chain is checked.

Packages are kept for HSS_EVIDENCE_DAYS (default 365) after sealing, then deleted by the daily
clean-up, unless they are on legal hold. Alerts closed as a real incident are sealed automatically.
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import os
import uuid
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.evidence")
router = APIRouter(tags=["evidence"])
MANAGERS = ("admin", "cso")
GENESIS = "0" * 64


def vault_dir() -> Path:
    d = Path(os.environ.get("HSS_DATA_DIR", "/data")) / "evidence"
    d.mkdir(parents=True, exist_ok=True)
    return d


def keep_days() -> int:
    return int(os.environ.get("HSS_EVIDENCE_DAYS", "365"))


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ------------------------------------------------------------------ packages

def build_package(alert_id, username: str) -> tuple[bytes, dict, dict]:
    """(zip bytes, manifest, alert) for one alert."""
    from .alerts import alert_detail
    from .clips import clip_file
    a = alert_detail(alert_id)
    cols = ["id", "camera_id", "source_kind", "source_ref", "tier", "type", "object_class", "zone", "severity",
            "confidence", "occurred_at", "received_at", "snapshot_ref", "raw"]
    with connect() as conn:
        ev = conn.execute(f"SELECT {', '.join(cols)} FROM events WHERE id = %s", (a["event_id"],)).fetchone()
    event = dict(zip(cols, ev))
    files: dict[str, bytes] = {
        "event.json": json.dumps(event, default=str, indent=2).encode(),
        "alert.json": json.dumps({k: v for k, v in a.items() if k != "timeline"}, default=str, indent=2).encode(),
        "timeline.json": json.dumps(a["timeline"], default=str, indent=2).encode(),
    }
    if event["snapshot_ref"]:
        snap = Path(os.environ.get("HSS_DATA_DIR", "/data")) / event["snapshot_ref"]
        if snap.exists():
            files["snapshot.jpg"] = snap.read_bytes()
    clip = clip_file(alert_id)
    if clip:
        files["clip.mp4"] = clip[0].read_bytes()
    manifest = {"alert": str(alert_id), "camera": event["camera_id"], "event_time": str(event["occurred_at"]),
                "packaged_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "packaged_by": username,
                "files": {n: sha256(b) for n, b in files.items()},
                "note": "SHA-256 of each file. Recompute to check nothing was changed."}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in {**files, "manifest.json": json.dumps(manifest, indent=2).encode()}.items():
            z.writestr(name, data)
    return buf.getvalue(), manifest, a


# ------------------------------------------------------------------ custody chain

def entry_hash(prev_hash: str, evidence_id: str, at: str, username: str, action: str, detail: str) -> str:
    return sha256("\x1f".join([prev_hash, evidence_id, at, username, action, detail]).encode())


def custody(conn, evidence_id, username: str, action: str, detail: str = "", ip: str = "") -> None:
    conn.execute("SELECT pg_advisory_xact_lock(7314)")             # one writer at a time keeps the chain straight
    row = conn.execute("SELECT hash FROM evidence_custody ORDER BY seq DESC LIMIT 1").fetchone()
    prev = row[0] if row else GENESIS
    at = datetime.now(timezone.utc).isoformat(timespec="microseconds")
    conn.execute("INSERT INTO evidence_custody (evidence_id, at, username, action, detail, ip, prev_hash, hash) "
                 "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                 (evidence_id, at, username, action, detail, ip, prev, entry_hash(prev, str(evidence_id), at, username, action, detail)))


def check_chain(rows: list[tuple]) -> tuple[bool, str]:
    """rows: (seq, evidence_id, at, username, action, detail, prev_hash, hash) in seq order (pure, tested)."""
    prev = GENESIS
    for seq, eid, at, user, action, detail, prev_hash, h in rows:
        at_s = at if isinstance(at, str) else at.astimezone(timezone.utc).isoformat(timespec="microseconds")
        if prev_hash != prev or h != entry_hash(prev, str(eid), at_s, user, action, detail):
            return False, f"custody log broken at entry {seq}"
        prev = h
    return True, f"{len(rows)} entries intact"


def chain_status() -> tuple[bool, str]:
    with connect() as conn:
        rows = conn.execute("SELECT seq, evidence_id, at, username, action, detail, prev_hash, hash FROM evidence_custody ORDER BY seq").fetchall()
    return check_chain(rows)


# ------------------------------------------------------------------ sealing

def seal(alert_id, username: str, *, reason: str = "", case_ref: str = "", ip: str = "") -> dict:
    data, manifest, a = build_package(alert_id, username)
    eid = uuid.uuid4()
    now = datetime.now(timezone.utc)
    path = vault_dir() / f"{now:%Y}" / f"{eid}.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o440)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    digest = sha256(data)
    title = f"{a.get('camera_name') or a['camera_id']} · {a['type'].replace('_', ' ')} · {a['created_at']:%d %b %Y %H:%M}" \
        if hasattr(a.get("created_at"), "strftime") else f"{a['camera_id']} · {a['type']}"
    with connect() as conn:
        conn.execute("INSERT INTO evidence (id, alert_id, camera_id, title, case_ref, reason, file, sha256, size_bytes, manifest, "
                     "sealed_by, retain_until) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (eid, alert_id, a["camera_id"], title, case_ref, reason, str(path.relative_to(vault_dir())), digest, len(data),
                      Jsonb(manifest), username, (now + timedelta(days=keep_days())).date()))
        custody(conn, eid, username, "sealed", f"SHA-256 {digest}" + (f"; {reason}" if reason else ""), ip)
        from .alerts import add_timeline
        add_timeline(conn, alert_id, "exported", f"Evidence sealed in the vault, SHA-256 {digest}", username)
    return get(eid)


COLS = ("id, alert_id, camera_id, title, case_ref, reason, file, sha256, size_bytes, manifest, sealed_by, sealed_at, retain_until, "
        "legal_hold, hold_reason, deleted_at, deleted_by")


def _row(r) -> dict:
    d = dict(zip([c.strip() for c in COLS.split(",")], r))
    d["id"] = str(d["id"])
    d["alert_id"] = str(d["alert_id"]) if d["alert_id"] else None
    d["files"] = sorted(d.pop("manifest").get("files", {}))
    d.pop("file")
    return d


def get(eid) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS} FROM evidence WHERE id = %s", (str(eid),)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such evidence package")
    return _row(r)


def _file(eid) -> tuple[Path, str]:
    with connect() as conn:
        r = conn.execute("SELECT file, sha256, deleted_at FROM evidence WHERE id = %s", (str(eid),)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such evidence package")
    if r[2]:
        raise HTTPException(status_code=410, detail="This package was deleted at the end of its retention period.")
    return vault_dir() / r[0], r[1]


# ------------------------------------------------------------------ endpoints

class SealIn(BaseModel):
    reason: str = Field(default="", max_length=300)
    case_ref: str = Field(default="", max_length=100)


@router.post("/alerts/{alert_id}/seal")
def seal_alert(alert_id: uuid.UUID, body: SealIn, request: Request, user: dict = Depends(require(*MANAGERS))) -> dict:
    out = seal(alert_id, user["username"], reason=body.reason, case_ref=body.case_ref, ip=client_ip(request))
    audit("evidence_sealed", user_id=user["id"], username=user["username"], ip=client_ip(request), alert=str(alert_id),
          evidence=out["id"], sha256=out["sha256"])
    return out


@router.get("/evidence")
def list_evidence(include_deleted: bool = False, _: dict = Depends(require(*MANAGERS))) -> dict:
    with connect() as conn:
        rows = conn.execute(f"SELECT {COLS} FROM evidence" + ("" if include_deleted else " WHERE deleted_at IS NULL")
                            + " ORDER BY sealed_at DESC LIMIT 500").fetchall()
    ok, detail = chain_status()
    return {"items": [_row(r) for r in rows], "chain_ok": ok, "chain_detail": detail, "keep_days": keep_days()}


@router.get("/evidence/{eid}")
def evidence_detail(eid: uuid.UUID, _: dict = Depends(require(*MANAGERS))) -> dict:
    d = get(eid)
    with connect() as conn:
        d["custody"] = [{"at": r[0], "username": r[1], "action": r[2], "detail": r[3], "ip": r[4], "hash": r[5]} for r in conn.execute(
            "SELECT at, username, action, detail, ip, hash FROM evidence_custody WHERE evidence_id = %s ORDER BY seq", (str(eid),)).fetchall()]
    return d


def _verify(eid, user: dict, ip: str) -> tuple[bool, bytes | None, str]:
    path, expected = _file(eid)
    data = path.read_bytes() if path.exists() else None
    actual = sha256(data) if data is not None else ""
    ok = actual == expected
    with connect() as conn:
        custody(conn, str(eid), user["username"], "verified" if ok else "verify_failed",
                f"SHA-256 matches" if ok else ("file missing" if data is None else f"expected {expected}, found {actual}"), ip)
    if not ok:
        audit("evidence_verify_failed", user_id=user["id"], username=user["username"], ip=ip, evidence=str(eid))
    return ok, data, expected


@router.post("/evidence/{eid}/verify")
def verify(eid: uuid.UUID, request: Request, user: dict = Depends(require(*MANAGERS))) -> dict:
    ok, _, expected = _verify(eid, user, client_ip(request))
    chain_ok, chain_detail = chain_status()
    return {"file_ok": ok, "sha256": expected, "chain_ok": chain_ok, "chain_detail": chain_detail}


@router.get("/evidence/{eid}/download")
def download(eid: uuid.UUID, request: Request, user: dict = Depends(require(*MANAGERS))) -> Response:
    ok, data, digest = _verify(eid, user, client_ip(request))
    if not ok:
        raise HTTPException(status_code=409, detail="The stored package no longer matches its recorded SHA-256; it was not sent. "
                                                    "This is logged; report it to the administrator.")
    with connect() as conn:
        custody(conn, str(eid), user["username"], "downloaded", "", client_ip(request))
    audit("evidence_downloaded", user_id=user["id"], username=user["username"], ip=client_ip(request), evidence=str(eid))
    return Response(data, media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="evidence-{str(eid)[:8]}.zip"', "X-Evidence-SHA256": digest})


class HoldIn(BaseModel):
    hold: bool
    reason: str = Field(min_length=3, max_length=300)


@router.put("/evidence/{eid}/hold")
def set_hold(eid: uuid.UUID, body: HoldIn, request: Request, user: dict = Depends(require(*MANAGERS))) -> dict:
    get(eid)
    with connect() as conn:
        conn.execute("UPDATE evidence SET legal_hold = %s, hold_reason = %s WHERE id = %s", (body.hold, body.reason if body.hold else "", str(eid)))
        custody(conn, str(eid), user["username"], "hold_on" if body.hold else "hold_off", body.reason, client_ip(request))
    audit("evidence_hold", user_id=user["id"], username=user["username"], ip=client_ip(request), evidence=str(eid),
          hold=body.hold, reason=body.reason)
    return get(eid)


class RetentionIn(BaseModel):
    retain_until: date
    reason: str = Field(min_length=3, max_length=300)


@router.put("/evidence/{eid}/retention")
def set_retention(eid: uuid.UUID, body: RetentionIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    d = get(eid)
    if body.retain_until < date.today():
        raise HTTPException(status_code=422, detail="Choose a date from today on.")
    with connect() as conn:
        conn.execute("UPDATE evidence SET retain_until = %s WHERE id = %s", (body.retain_until, str(eid)))
        custody(conn, str(eid), user["username"], "retention", f"{d['retain_until']} to {body.retain_until}: {body.reason}", client_ip(request))
    return get(eid)


# ------------------------------------------------------------------ retention clean-up

def expired(rows: list[dict], today: date) -> list[dict]:
    """Packages due for deletion (pure, tested): past their date, not on hold, not already deleted."""
    return [r for r in rows if r["retain_until"] < today and not r["legal_hold"] and not r["deleted_at"]]


def cleanup(today: date | None = None) -> int:
    today = today or date.today()
    with connect() as conn:
        rows = [dict(zip(["id", "file", "retain_until", "legal_hold", "deleted_at"], r)) for r in conn.execute(
            "SELECT id, file, retain_until, legal_hold, deleted_at FROM evidence WHERE deleted_at IS NULL").fetchall()]
    n = 0
    for r in expired(rows, today):
        p = vault_dir() / r["file"]
        try:
            p.chmod(0o640)
            p.unlink(missing_ok=True)
        except OSError as exc:
            log.warning("evidence %s: %s", r["id"], exc)
            continue
        with connect() as conn:
            conn.execute("UPDATE evidence SET deleted_at = now(), deleted_by = 'retention' WHERE id = %s", (r["id"],))
            custody(conn, str(r["id"]), "system", "deleted", f"retention ended {r['retain_until']}")
        n += 1
    if n:
        log.info("evidence retention: deleted %d package(s)", n)
    return n


async def background_loop() -> None:
    await asyncio.sleep(60)
    while True:
        try:
            await asyncio.to_thread(cleanup)
        except Exception as exc:
            log.warning("evidence clean-up: %s", exc)
        await asyncio.sleep(6 * 3600)
