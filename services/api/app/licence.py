"""Per-site perpetual licence (Phase 8).

A licence is a small JSON file signed with the vendor's Ed25519 private key (kept offline, made with
tools/licence/hss-licence.py). This API checks it with the vendor's public key in
app/licence_public.key. A licence is for one installation (its installation id), never expires for
the features it covers, and carries the date updates and support run to.

The licence never stops what is already running: recording, live view, events and alerts always
work. It limits what can be added (NVRs, cameras) and turns on the optional features (face and plate
recognition, GPS tracking). Without a licence an installation runs fully for 30 days, then can't add
NVRs or turn on the optional features until a licence is loaded. If the public key file is missing,
licensing is not set up and nothing is limited (development and the PoC).
"""
from __future__ import annotations

import base64
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .db import connect

PUBLIC_KEY = Path(__file__).parent / "licence_public.key"
GRACE_DAYS = 30
FEATURES = {"face_plate": "Face and number plate recognition", "gps": "GPS tracking of guards and vehicles"}
FIELDS = ("id", "licensee", "site", "installation_id", "issued", "support_until", "max_nvrs", "max_cameras", "features")


def canonical(lic: dict) -> bytes:
    """The exact bytes that are signed: the licence fields as sorted, compact JSON."""
    return json.dumps({k: lic[k] for k in FIELDS}, sort_keys=True, separators=(",", ":")).encode()


def verify(text: str, public_key_b64: str) -> dict:
    """Check a licence file (pure, tested). Returns the licence fields; raises ValueError with a reason."""
    try:
        doc = json.loads(text)
        lic, sig = doc["licence"], base64.b64decode(doc["signature"])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError("This isn't an HSS licence file.") from exc
    missing = [k for k in FIELDS if k not in lic]
    if missing:
        raise ValueError(f"The licence is missing {', '.join(missing)}.")
    try:
        Ed25519PublicKey.from_public_bytes(base64.b64decode(public_key_b64)).verify(sig, canonical(lic))
    except (InvalidSignature, ValueError) as exc:
        raise ValueError("The licence signature is not valid: it was changed, or not issued for this software.") from exc
    return {k: lic[k] for k in FIELDS}


def _setting(conn, key):
    r = conn.execute("SELECT value FROM settings WHERE key = %s", (key,)).fetchone()
    return r[0] if r else None


def _put(conn, key, value):
    conn.execute("INSERT INTO settings (key, value) VALUES (%s, %s) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (key, Jsonb(value)))


def installation() -> dict:
    """This installation's id and first start (made once)."""
    with connect() as conn:
        inst = _setting(conn, "installation")
        if not inst:
            inst = {"id": str(uuid.uuid4()), "since": datetime.now(timezone.utc).isoformat()}
            _put(conn, "installation", inst)
    return inst


def status(today: date | None = None) -> dict:
    today = today or date.today()
    inst = installation()
    base = {"installation_id": inst["id"], "features_known": FEATURES}
    if not PUBLIC_KEY.exists():
        return {**base, "state": "not_set_up", "enforced": False, "summary": "Licensing is not set up on this build; nothing is limited."}
    with connect() as conn:
        stored = _setting(conn, "licence")
    since = datetime.fromisoformat(inst["since"]).date()
    grace_end = since + timedelta(days=GRACE_DAYS)
    if stored:
        try:
            lic = verify(stored["text"], PUBLIC_KEY.read_text().strip())
        except ValueError as exc:
            return {**base, "state": "invalid", "enforced": True, "summary": str(exc), "grace_until": str(grace_end)}
        if lic["installation_id"] not in (inst["id"], "*"):
            return {**base, "state": "invalid", "enforced": True, "summary": "This licence is for another installation.",
                    "grace_until": str(grace_end)}
        support_ok = date.fromisoformat(lic["support_until"]) >= today
        return {**base, "state": "licensed", "enforced": True, "licence": lic, "support_ok": support_ok,
                "summary": f"Licensed to {lic['licensee']} for {lic['site']}: up to {lic['max_nvrs']} NVRs and {lic['max_cameras']} cameras. "
                           + (f"Updates and support until {lic['support_until']}." if support_ok else
                              f"Updates and support ended {lic['support_until']}; the system keeps working.")}
    in_grace = today <= grace_end
    return {**base, "state": "grace" if in_grace else "unlicensed", "enforced": True, "grace_until": str(grace_end),
            "summary": (f"No licence yet: everything works until {grace_end}, then NVRs can't be added until a licence is loaded."
                        if in_grace else "No licence: the system keeps running, but NVRs can't be added and optional features stay off until a licence is loaded.")}


def allows(what: str, *, nvrs: int = 0, cameras: int = 0) -> tuple[bool, str]:
    """Whether adding something is allowed: what = 'nvr' (with the counts after adding) or a feature name."""
    st = status()
    if not st["enforced"]:
        return True, ""
    if st["state"] == "grace":
        return True, ""
    if st["state"] != "licensed":
        return False, st["summary"] + " Load a licence under Settings › Licence."
    lic = st["licence"]
    if what == "nvr":
        if nvrs > lic["max_nvrs"]:
            return False, f"The licence covers {lic['max_nvrs']} NVR{'s' if lic['max_nvrs'] != 1 else ''}. Ask for a licence upgrade to add more."
        if cameras > lic["max_cameras"]:
            return False, f"The licence covers {lic['max_cameras']} cameras; this NVR would bring it to {cameras}."
        return True, ""
    if what in FEATURES and what not in lic["features"]:
        return False, f"The licence doesn't include {FEATURES[what].lower()}."
    return True, ""


def require_feature(what: str) -> None:
    ok, why = allows(what)
    if not ok:
        raise HTTPException(status_code=402, detail=why)


def load(text: str) -> dict:
    if not PUBLIC_KEY.exists():
        raise HTTPException(status_code=409, detail="Licensing is not set up on this build (no public key).")
    try:
        lic = verify(text, PUBLIC_KEY.read_text().strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if lic["installation_id"] not in (installation()["id"], "*"):
        raise HTTPException(status_code=422, detail=f"This licence is for installation {lic['installation_id']}, not this one.")
    with connect() as conn:
        _put(conn, "licence", {"text": text, "loaded_at": datetime.now(timezone.utc).isoformat()})
    return status()
