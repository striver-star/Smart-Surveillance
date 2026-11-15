"""Legal review gate for face and number plate recognition.

Face and plate recognition stay locked until an administrator has opened the legal review
(app/legal/face-plate-review.md), kept it open long enough to read it, and accepted every
condition in its section 14, recording the legal opinion and the DPIA. The acceptance:

- is tied to the exact text (a hash): any change to the document locks the features again;
- covers face, plate or both;
- expires after 12 months;
- can be withdrawn by an administrator or the CSO at any time, which locks the features at once.

While locked, the API drops recognition events (face matches, plate reads) instead of storing them,
and the recognition trial tool refuses to run.
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token

router = APIRouter(prefix="/legal", tags=["legal"])
DOC_ID = "face-plate"
DOC_PATH = Path(__file__).parent / "legal" / "face-plate-review.md"
VALID_DAYS = 365
SCOPES = ("face", "plate")


def min_read_s() -> int:
    return int(os.environ.get("HSS_LEGAL_MIN_READ_S", "120"))


@lru_cache(maxsize=1)
def document() -> dict:
    text = DOC_PATH.read_text(encoding="utf-8")
    m = re.search(r"^## 14\..*?$(.*?)^## ", text, re.S | re.M)
    conditions = [re.sub(r"\s+", " ", c).strip() for c in re.findall(r"^\d+\.\s+(.+?)(?=^\d+\.|\Z)", m.group(1).strip() + "\n", re.S | re.M)] if m else []
    title = text.splitlines()[0].lstrip("# ").strip()
    edition = re.search(r"^Edition [^\n]+", text, re.M)
    return {"id": DOC_ID, "title": title, "edition": edition.group(0) if edition else "",
            "version": hashlib.sha256(text.encode()).hexdigest()[:16], "text": text, "conditions": conditions}


# ------------------------------------------------------------------ state

def current_acceptance(now: datetime | None = None) -> dict | None:
    """The acceptance in force: not withdrawn, not expired, and for the document as it is now."""
    now = now or datetime.now(timezone.utc)
    try:
        with connect() as conn:
            r = conn.execute("SELECT id, version, scopes, username, full_name, position, reviewer_name, reviewer_firm, "
                             "opinion_ref, opinion_date, dpia_ref, accepted_at, expires_at FROM legal_acceptances "
                             "WHERE document = %s AND revoked_at IS NULL ORDER BY accepted_at DESC LIMIT 1", (DOC_ID,)).fetchone()
    except Exception:
        return None
    if not r:
        return None
    keys = ["id", "version", "scopes", "username", "full_name", "position", "reviewer_name", "reviewer_firm",
            "opinion_ref", "opinion_date", "dpia_ref", "accepted_at", "expires_at"]
    a = dict(zip(keys, r))
    a["current_version"] = a["version"] == document()["version"]
    a["expired"] = a["expires_at"] <= now
    return a


def status() -> dict:
    a = current_acceptance()
    reason = None
    if a is None:
        reason = "The legal review has not been accepted."
    elif not a["current_version"]:
        reason = "The legal review was updated; it must be read and accepted again."
    elif a["expired"]:
        reason = f"The acceptance expired on {a['expires_at']:%d %B %Y}; it must be reviewed and accepted again."
    ok = reason is None
    return {"face": ok and "face" in a["scopes"], "plate": ok and "plate" in a["scopes"], "locked_reason": reason,
            "version": document()["version"], "expires_at": a["expires_at"] if ok else None}


def unlocked(scope: str) -> bool:
    return bool(status().get(scope))


FACE_ID = re.compile(r"^(face_(match|recogni[sz]ed|identified)|watchlist_face)")
PLATE = re.compile(r"^(vehicle_plate|plate_|anpr|watchlist_plate)")


def recognition_scope(event_type: str) -> str | None:
    """Which locked feature an event type belongs to (None = an ordinary event). Face capture without
    identification (face_detected) is ordinary CCTV and is not gated."""
    t = event_type.lower()
    return "face" if FACE_ID.match(t) else "plate" if PLATE.match(t) else None


# ------------------------------------------------------------------ endpoints

@router.get("/face-plate")
def get_review(user: dict = Depends(require("admin", "cso", "management"))) -> dict:
    d = document()
    with connect() as conn:
        rows = conn.execute("SELECT version, scopes, username, full_name, position, reviewer_name, reviewer_firm, opinion_ref, "
                            "opinion_date, dpia_ref, accepted_at, expires_at, revoked_at, revoked_by, revoke_reason "
                            "FROM legal_acceptances WHERE document = %s ORDER BY accepted_at DESC LIMIT 20", (DOC_ID,)).fetchall()
    keys = ["version", "scopes", "username", "full_name", "position", "reviewer_name", "reviewer_firm", "opinion_ref",
            "opinion_date", "dpia_ref", "accepted_at", "expires_at", "revoked_at", "revoked_by", "revoke_reason"]
    return {**{k: d[k] for k in ("id", "title", "edition", "version", "text", "conditions")},
            "status": status(), "min_read_s": min_read_s(), "two_factor_ready": bool(user.get("totp_enabled")),
            "history": [dict(zip(keys, r)) for r in rows]}


@router.post("/face-plate/open")
def open_review(user: dict = Depends(require("admin"))) -> dict:
    with connect() as conn:
        rid = conn.execute("INSERT INTO legal_reads (document, version, user_id) VALUES (%s, %s, %s) RETURNING id",
                           (DOC_ID, document()["version"], user["id"])).fetchone()[0]
    return {"read_id": str(rid), "min_read_s": min_read_s()}


class AcceptIn(BaseModel):
    read_id: str
    version: str
    scopes: list[str] = Field(min_length=1)
    conditions: list[bool]
    read_to_end: bool
    full_name: str = Field(min_length=3, max_length=100)
    position: str = Field(min_length=2, max_length=100)
    reviewer_name: str = Field(min_length=3, max_length=100)
    reviewer_firm: str = Field(min_length=2, max_length=150)
    opinion_ref: str = Field(min_length=2, max_length=100)
    opinion_date: date
    dpia_ref: str = Field(min_length=2, max_length=100)


def check_acceptance(body: AcceptIn, *, version: str, n_conditions: int, opened_at: datetime | None, now: datetime,
                     two_factor: bool) -> list[str]:
    """Everything wrong with an acceptance (pure function, tested). Empty = it can be recorded."""
    problems = []
    if not two_factor:
        problems.append("Turn on two-factor sign-in for your account (Settings) before accepting.")
    if body.version != version:
        problems.append("The document changed while you were reading it; reload the page and read it again.")
    if opened_at is None:
        problems.append("Open the review on this page and read it before accepting.")
    elif (now - opened_at).total_seconds() < min_read_s():
        problems.append(f"Take at least {min_read_s() // 60} minutes to read the review before accepting.")
    if not body.read_to_end:
        problems.append("Read the review to the end.")
    if len(body.conditions) != n_conditions or not all(body.conditions):
        problems.append("Every condition in section 14 must be accepted.")
    if not set(body.scopes) <= set(SCOPES) or not body.scopes:
        problems.append("Choose face recognition, plate recognition or both.")
    if body.opinion_date > now.date():
        problems.append("The legal opinion's date can't be in the future.")
    elif body.opinion_date < now.date() - timedelta(days=VALID_DAYS):
        problems.append("The legal opinion is more than 12 months old; get it renewed.")
    return problems


@router.post("/face-plate/accept")
def accept(body: AcceptIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    d = document()
    now = datetime.now(timezone.utc)
    with connect() as conn:
        row = conn.execute("SELECT opened_at FROM legal_reads WHERE id::text = %s AND user_id = %s AND version = %s",
                           (body.read_id, user["id"], d["version"])).fetchone()
    opened_at = row[0] if row else None
    problems = check_acceptance(body, version=d["version"], n_conditions=len(d["conditions"]), opened_at=opened_at,
                                now=now, two_factor=bool(user.get("totp_enabled")))
    if problems:
        raise HTTPException(status_code=422, detail=" ".join(problems))
    scopes = sorted(set(body.scopes))
    expires = now + timedelta(days=VALID_DAYS)
    with connect() as conn:
        conn.execute("UPDATE legal_acceptances SET revoked_at = now(), revoked_by = %s, revoke_reason = 'replaced by a new acceptance' "
                     "WHERE document = %s AND revoked_at IS NULL", (user["username"], DOC_ID))
        conn.execute("INSERT INTO legal_acceptances (document, version, scopes, user_id, username, full_name, position, reviewer_name, "
                     "reviewer_firm, opinion_ref, opinion_date, dpia_ref, conditions, read_seconds, expires_at) "
                     "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                     (DOC_ID, d["version"], scopes, user["id"], user["username"], body.full_name.strip(), body.position.strip(),
                      body.reviewer_name.strip(), body.reviewer_firm.strip(), body.opinion_ref.strip(), body.opinion_date,
                      body.dpia_ref.strip(), Jsonb(d["conditions"]), int((now - opened_at).total_seconds()), expires))
    audit("legal_accepted", user_id=user["id"], username=user["username"], ip=client_ip(request), document=DOC_ID,
          version=d["version"], scopes=", ".join(scopes), reviewer=f"{body.reviewer_name} ({body.reviewer_firm})",
          opinion=body.opinion_ref, dpia=body.dpia_ref, expires=f"{expires:%Y-%m-%d}")
    return status()


class RevokeIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)


@router.post("/face-plate/revoke")
def revoke(body: RevokeIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    with connect() as conn:
        n = conn.execute("UPDATE legal_acceptances SET revoked_at = now(), revoked_by = %s, revoke_reason = %s "
                         "WHERE document = %s AND revoked_at IS NULL", (user["username"], body.reason, DOC_ID)).rowcount
    if not n:
        raise HTTPException(status_code=409, detail="Face and plate recognition are already locked.")
    audit("legal_revoked", user_id=user["id"], username=user["username"], ip=client_ip(request), document=DOC_ID, reason=body.reason)
    return status()


@router.get("/face-plate/status", dependencies=[Depends(check_worker_token)])
def worker_status() -> dict:
    """For workers and tools: which recognition features are unlocked."""
    return status()
