"""Users, login sessions, roles, two-factor codes (TOTP) and the audit log.

Security choices (Section 15 of the context document):
  - Passwords: scrypt (Python standard library) with a random salt; at least 12 characters.
  - Sessions: a random 256-bit token in an HttpOnly, Secure, SameSite=Strict cookie. Only its
    SHA-256 is stored, so a database copy can't be used to log in. Sessions expire after
    HSS_SESSION_IDLE_MIN of inactivity (default 120) and HSS_SESSION_MAX_H at most (default 12).
  - Changes need the X-HSS header as well as the cookie (a simple guard against cross-site requests).
  - 5 wrong passwords lock the account for 15 minutes. Errors never say which part was wrong.
  - Two-factor codes: RFC 6238 TOTP (any authenticator app), each code usable once.
  - Every login, failure, logout and user change goes to the audit log.

Roles: admin (everything, including users and settings), cso (security: live, events, reports),
operator (live view and events), management (overview and reports).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import secrets
import struct
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from .db import connect

router = APIRouter(tags=["auth"])

ROLES = ("admin", "cso", "operator", "management")
COOKIE = "hss_session"
MIN_PASSWORD = 12
MAX_FAILED, LOCK_MINUTES = 5, 15
SCRYPT = {"n": 2 ** 15, "r": 8, "p": 1}


def _idle() -> timedelta:
    return timedelta(minutes=int(os.environ.get("HSS_SESSION_IDLE_MIN", "120")))


def _max_age() -> timedelta:
    return timedelta(hours=int(os.environ.get("HSS_SESSION_MAX_H", "12")))


# ------------------------------------------------------------------ passwords

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, maxmem=64 * 1024 * 1024, dklen=32, **SCRYPT)
    return "scrypt${n}${r}${p}${salt}${dk}".format(**SCRYPT, salt=base64.b64encode(salt).decode(),
                                                   dk=base64.b64encode(digest).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, dk = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                                maxmem=64 * 1024 * 1024, dklen=32)
        return hmac.compare_digest(digest, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))   # keeps "no such user" as slow as a wrong password


def check_password_rules(password: str, username: str = "") -> None:
    problems = []
    if len(password) < MIN_PASSWORD:
        problems.append(f"at least {MIN_PASSWORD} characters")
    if username and username.lower() in password.lower():
        problems.append("must not contain the username")
    if password.lower() in {"password1234", "admin@123456", "123456789012", "qwertyuiopas"}:
        problems.append("too common")
    if problems:
        raise HTTPException(status_code=422, detail="Password: " + "; ".join(problems))


# ------------------------------------------------------------------ TOTP (RFC 6238)

def totp(secret_b32: str, step: int, digits: int = 6) -> str:
    key = base64.b32decode(secret_b32 + "=" * (-len(secret_b32) % 8), casefold=True)
    mac = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(code).zfill(digits)


def verify_totp(secret_b32: str, code: str, last_step: int | None, now: float | None = None) -> int | None:
    """The accepted time step, or None. Allows one step of clock drift; a code works once."""
    step, _ = check_totp(secret_b32, code, last_step, now)
    return step


def check_totp(secret_b32: str, code: str, last_step: int | None, now: float | None = None) -> tuple[int | None, bool]:
    """(accepted step or None, True if the code was right but already used)."""
    code = "".join(ch for ch in str(code) if ch.isdigit())
    if len(code) != 6:
        return None, False
    current = int((now or time.time()) // 30)
    reused = False
    for step in (current, current - 1, current + 1):
        if hmac.compare_digest(totp(secret_b32, step), code):
            if last_step is not None and step <= last_step:
                reused = True
                continue
            return step, False
    return None, reused


# ------------------------------------------------------------------ audit

def audit(action: str, *, user_id=None, username: str | None = None, ip: str | None = None, **detail) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO audit_log (user_id, username, action, detail, ip) VALUES (%s, %s, %s, %s, %s)",
                     (user_id, username, action, json.dumps(detail, default=str), ip))


def client_ip(request: Request) -> str:
    # Caddy sets X-Forwarded-For; the API is only reachable through it.
    return (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else ""))


# ------------------------------------------------------------------ sessions

USER_COLS = ("id, username, display_name, role, must_change_password, totp_enabled, disabled, "
             "last_login_at, created_at")


def _row_user(row) -> dict:
    keys = [c.strip() for c in USER_COLS.split(",")]
    u = dict(zip(keys, row))
    u["id"] = str(u["id"])
    return u


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(user_id, request: Request, response: Response) -> None:
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    with connect() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at < now()")
        conn.execute("INSERT INTO sessions (token_hash, user_id, expires_at, ip, user_agent) VALUES (%s, %s, %s, %s, %s)",
                     (_token_hash(token), user_id, now + _max_age(), client_ip(request),
                      (request.headers.get("user-agent") or "")[:200]))
    response.set_cookie(COOKIE, token, httponly=True, secure=True, samesite="strict", path="/",
                        max_age=int(_max_age().total_seconds()))


def session_user(request: Request) -> dict | None:
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    with connect() as conn:
        row = conn.execute(
            f"SELECT s.last_seen_at, s.expires_at, {', '.join('u.' + c.strip() for c in USER_COLS.split(','))} "
            "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash = %s", (_token_hash(token),)).fetchone()
        if not row:
            return None
        last_seen, expires = row[0], row[1]
        user = _row_user(row[2:])
        now = datetime.now(timezone.utc)
        if user["disabled"] or now > expires or now - last_seen > _idle():
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))
            return None
        if now - last_seen > timedelta(minutes=1):
            conn.execute("UPDATE sessions SET last_seen_at = now() WHERE token_hash = %s", (_token_hash(token),))
    return user


def require(*roles: str, allow_admin_token: bool = False):
    """Dependency: a logged-in user with one of `roles` (any role if none given).

    With allow_admin_token, the HSS_ADMIN_TOKEN bearer token is also accepted (scripts and tools).
    Requests that change something must carry the X-HSS header (browsers can't add it cross-site).
    """
    def dep(request: Request, authorization: str | None = Header(default=None)) -> dict:
        admin_token = os.environ.get("HSS_ADMIN_TOKEN", "")
        if allow_admin_token and admin_token and authorization and hmac.compare_digest(
                authorization.encode(), f"Bearer {admin_token}".encode()):
            return {"id": None, "username": "admin-token", "role": "admin", "must_change_password": False}
        user = session_user(request)
        if user is None:
            raise HTTPException(status_code=401, detail="not logged in")
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-hss") != "1":
            raise HTTPException(status_code=403, detail="missing X-HSS header")
        if user["must_change_password"] and request.url.path not in ("/auth/me", "/auth/password", "/auth/logout"):
            raise HTTPException(status_code=403, detail="password change required")
        if roles and user["role"] not in roles:
            raise HTTPException(status_code=403, detail="your role does not allow this")
        return user
    return dep


# ------------------------------------------------------------------ endpoints

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=10)


@router.post("/auth/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    ip = client_ip(request)
    fail = HTTPException(status_code=401, detail="Wrong username or password, or the account is locked.")
    with connect() as conn:
        row = conn.execute("SELECT id, password_hash, disabled, failed_attempts, locked_until, totp_enabled, "
                           "totp_secret, totp_last_step FROM users WHERE tenant_id = 'default' AND lower(username) = lower(%s)",
                           (body.username,)).fetchone()
    if row is None:
        verify_password(body.password, _DUMMY_HASH)
        audit("login_failed", username=body.username[:80], ip=ip, reason="unknown user")
        raise fail
    uid, pw_hash, disabled, failed, locked_until, totp_on, secret, last_step = row
    now = datetime.now(timezone.utc)
    if disabled or (locked_until and locked_until > now):
        verify_password(body.password, _DUMMY_HASH)
        audit("login_failed", user_id=uid, username=body.username, ip=ip, reason="disabled" if disabled else "locked")
        raise fail
    if not verify_password(body.password, pw_hash):
        failed += 1
        lock = now + timedelta(minutes=LOCK_MINUTES) if failed >= MAX_FAILED else None
        with connect() as conn:
            conn.execute("UPDATE users SET failed_attempts = %s, locked_until = %s WHERE id = %s",
                         (0 if lock else failed, lock, uid))
        audit("login_failed", user_id=uid, username=body.username, ip=ip,
              reason="wrong password" + (f"; locked for {LOCK_MINUTES} min" if lock else ""))
        raise fail
    if totp_on:
        if not body.code:
            return {"need_code": True}
        step, reused = check_totp(secret, body.code, last_step)
        if step is None:
            audit("login_failed", user_id=uid, username=body.username, ip=ip,
                  reason="2FA code already used" if reused else "wrong 2FA code")
            raise HTTPException(status_code=401, detail="That code was already used. Wait for the next code in your app."
                                if reused else "Wrong or expired code.")
        with connect() as conn:
            conn.execute("UPDATE users SET totp_last_step = %s WHERE id = %s", (step, uid))
    with connect() as conn:
        conn.execute("UPDATE users SET failed_attempts = 0, locked_until = NULL, last_login_at = now() WHERE id = %s", (uid,))
        user = _row_user(conn.execute(f"SELECT {USER_COLS} FROM users WHERE id = %s", (uid,)).fetchone())
    create_session(uid, request, response)
    audit("login", user_id=uid, username=user["username"], ip=ip, two_factor=bool(totp_on))
    return {"user": user}


@router.post("/auth/logout")
def logout(request: Request, response: Response) -> dict:
    token = request.cookies.get(COOKIE)
    user = session_user(request) if token else None
    if token:
        with connect() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = %s", (_token_hash(token),))
    if user:
        audit("logout", user_id=user["id"], username=user["username"], ip=client_ip(request))
    response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="strict")
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict = Depends(require())) -> dict:
    return user


class PasswordIn(BaseModel):
    current: str = Field(max_length=200)
    new: str = Field(max_length=200)


@router.post("/auth/password")
def change_password(body: PasswordIn, request: Request, user: dict = Depends(require())) -> dict:
    with connect() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],)).fetchone()[0]
    if not verify_password(body.current, stored):
        raise HTTPException(status_code=401, detail="Current password is wrong.")
    check_password_rules(body.new, user["username"])
    token = request.cookies.get(COOKIE, "")
    with connect() as conn:
        conn.execute("UPDATE users SET password_hash = %s, must_change_password = false WHERE id = %s",
                     (hash_password(body.new), user["id"]))
        conn.execute("DELETE FROM sessions WHERE user_id = %s AND token_hash <> %s", (user["id"], _token_hash(token)))
    audit("password_changed", user_id=user["id"], username=user["username"], ip=client_ip(request))
    return {"ok": True}


@router.post("/auth/2fa/setup")
def totp_setup(user: dict = Depends(require())) -> dict:
    import segno
    secret = base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")
    with connect() as conn:
        conn.execute("UPDATE users SET totp_secret = %s, totp_enabled = false WHERE id = %s", (secret, user["id"]))
        site = (conn.execute("SELECT value FROM settings WHERE key = 'branding'").fetchone() or [{}])[0].get("site_name") or "HSS"
    from urllib.parse import quote
    uri = f"otpauth://totp/{quote(site)}:{quote(user['username'])}?secret={secret}&issuer={quote(site)}&digits=6&period=30"
    buf = io.BytesIO()
    segno.make(uri, error="m").save(buf, kind="svg", scale=5, border=2, dark="#0b1220")
    return {"secret": secret, "uri": uri, "qr_svg": buf.getvalue().decode()}


class CodeIn(BaseModel):
    code: str = Field(max_length=10)


@router.post("/auth/2fa/enable")
def totp_enable(body: CodeIn, request: Request, user: dict = Depends(require())) -> dict:
    with connect() as conn:
        secret = conn.execute("SELECT totp_secret FROM users WHERE id = %s", (user["id"],)).fetchone()[0]
    step = verify_totp(secret or "", body.code, None) if secret else None
    if step is None:
        raise HTTPException(status_code=401, detail="That code didn't match. Check the phone's clock and try the next code.")
    with connect() as conn:
        conn.execute("UPDATE users SET totp_enabled = true, totp_last_step = %s WHERE id = %s", (step, user["id"]))
    audit("2fa_enabled", user_id=user["id"], username=user["username"], ip=client_ip(request))
    return {"ok": True}


class PasswordOnly(BaseModel):
    password: str = Field(max_length=200)


@router.post("/auth/2fa/disable")
def totp_disable(body: PasswordOnly, request: Request, user: dict = Depends(require())) -> dict:
    with connect() as conn:
        stored = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user["id"],)).fetchone()[0]
    if not verify_password(body.password, stored):
        raise HTTPException(status_code=401, detail="Password is wrong.")
    with connect() as conn:
        conn.execute("UPDATE users SET totp_enabled = false, totp_secret = NULL, totp_last_step = NULL WHERE id = %s",
                     (user["id"],))
    audit("2fa_disabled", user_id=user["id"], username=user["username"], ip=client_ip(request))
    return {"ok": True}


# ------------------------------------------------------------------ user management (admin)

class UserIn(BaseModel):
    username: str = Field(pattern=r"^[A-Za-z0-9._@-]{3,40}$")
    display_name: str = Field(default="", max_length=80)
    role: str


class UserPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=80)
    role: str | None = None
    disabled: bool | None = None
    reset_password: bool = False


def _temp_password() -> str:
    words = secrets.token_urlsafe(12)
    return f"{words[:4]}-{words[4:8]}-{words[8:12]}-{secrets.randbelow(90) + 10}"


@router.get("/users")
def list_users(_: dict = Depends(require("admin", allow_admin_token=True))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(f"SELECT {USER_COLS}, locked_until FROM users ORDER BY lower(username)").fetchall()
    out = []
    for r in rows:
        u = _row_user(r[:-1])
        u["locked"] = bool(r[-1] and r[-1] > datetime.now(timezone.utc))
        out.append(u)
    return out


@router.post("/users", status_code=201)
def create_user(body: UserIn, request: Request, admin: dict = Depends(require("admin", allow_admin_token=True))) -> dict:
    if body.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {', '.join(ROLES)}")
    temp = _temp_password()
    try:
        with connect() as conn:
            row = conn.execute("INSERT INTO users (username, display_name, role, password_hash, must_change_password) "
                               f"VALUES (%s, %s, %s, %s, true) RETURNING {USER_COLS}",
                               (body.username, body.display_name, body.role, hash_password(temp))).fetchone()
    except Exception as exc:
        if "users_tenant_username" in str(exc):
            raise HTTPException(status_code=409, detail="That username is taken.") from exc
        raise
    user = _row_user(row)
    audit("user_created", user_id=admin["id"], username=admin["username"], ip=client_ip(request),
          target=body.username, role=body.role)
    return {"user": user, "temporary_password": temp}


@router.patch("/users/{user_id}")
def update_user(user_id: uuid.UUID, body: UserPatch, request: Request,
                admin: dict = Depends(require("admin", allow_admin_token=True))) -> dict:
    if body.role is not None and body.role not in ROLES:
        raise HTTPException(status_code=422, detail=f"role must be one of {', '.join(ROLES)}")
    if str(user_id) == admin["id"] and (body.disabled or (body.role and body.role != "admin")):
        raise HTTPException(status_code=422, detail="You can't disable yourself or remove your own admin role.")
    sets, params, out = [], [], {}
    for col in ("display_name", "role", "disabled"):
        val = getattr(body, col)
        if val is not None:
            sets.append(f"{col} = %s")
            params.append(val)
    if body.reset_password:
        temp = _temp_password()
        sets += ["password_hash = %s", "must_change_password = true", "failed_attempts = 0", "locked_until = NULL",
                 "totp_enabled = false", "totp_secret = NULL"]
        params.append(hash_password(temp))
        out["temporary_password"] = temp
    if not sets:
        raise HTTPException(status_code=422, detail="nothing to change")
    with connect() as conn:
        row = conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s RETURNING {USER_COLS}",
                           (*params, user_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no such user")
        if body.disabled or body.reset_password or body.role:
            conn.execute("DELETE FROM sessions WHERE user_id = %s", (user_id,))
    out["user"] = _row_user(row)
    audit("user_changed", user_id=admin["id"], username=admin["username"], ip=client_ip(request),
          target=out["user"]["username"], **body.model_dump(exclude_none=True))
    return out


@router.get("/audit")
def audit_list(limit: int = 100, _: dict = Depends(require("admin", allow_admin_token=True))) -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT at, username, action, detail, ip FROM audit_log ORDER BY at DESC LIMIT %s",
                            (max(1, min(limit, 1000)),)).fetchall()
    return [{"at": r[0], "username": r[1], "action": r[2], "detail": r[3], "ip": r[4]} for r in rows]


# ------------------------------------------------------------------ first admin (command line)

def create_admin_cli(argv=None) -> int:
    """docker compose exec api python -m app.auth create-admin <username>"""
    import argparse
    import getpass
    p = argparse.ArgumentParser(prog="python -m app.auth")
    p.add_argument("command", choices=["create-admin"])
    p.add_argument("username")
    a = p.parse_args(argv)
    from .db import migrate
    migrate()
    pw = getpass.getpass("New password (12+ characters): ")
    if pw != getpass.getpass("Repeat it: "):
        print("The passwords don't match.")
        return 1
    try:
        check_password_rules(pw, a.username)
    except HTTPException as exc:
        print(exc.detail)
        return 1
    with connect() as conn:
        conn.execute("INSERT INTO users (username, display_name, role, password_hash) VALUES (%s, %s, 'admin', %s) "
                     "ON CONFLICT (tenant_id, lower(username)) DO UPDATE SET password_hash = EXCLUDED.password_hash, "
                     "role = 'admin', disabled = false, failed_attempts = 0, locked_until = NULL",
                     (a.username, a.username, hash_password(pw)))
    audit("admin_created_cli", username=a.username)
    print(f"Admin '{a.username}' is ready. Log in at https://<server>/")
    return 0


if __name__ == "__main__":
    raise SystemExit(create_admin_cli())
