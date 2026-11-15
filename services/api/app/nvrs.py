"""NVR registry (Phase 1): add, test, edit and remove NVRs from the console, and per-camera tier overrides.

An NVR's password is encrypted by the vault (app/vault.py) and never sent back to the browser. The edge
service fetches the list with the worker token, and the stream gateway gets one path per channel
(<alias>-chNN, sub-stream), added through MediaMTX's API and re-checked every two minutes so a gateway
restart doesn't lose them. Paths already defined in gateway/cameras.env are left as they are.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field, field_validator

from . import vault
from .auth import audit, client_ip, require
from .db import connect
from .events import check_worker_token
from .isapi import DeviceError, read_nvr

log = logging.getLogger("hss.nvrs")
router = APIRouter(tags=["nvrs"])
ADDRESS = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$")
ALIAS = re.compile(r"^[a-z][a-z0-9]{1,19}$")
TIERS = {"E": "Camera AI", "N": "NVR AI", "S": "Server AI"}
COLS = ("id, address, alias, name, username, scheme, rtsp_port, segment, enabled, live_view, info, test_ok, test_detail, "
        "tested_at, created_at, updated_at")


def host(address: str) -> str:
    return address.rsplit(":", 1)[0] if address.count(":") == 1 else address


def default_alias(address: str) -> str:
    m = re.search(r"\.(\d+)$", host(address))
    return f"nvr{m.group(1)}" if m else ("nvr" + re.sub(r"[^a-z0-9]", "", host(address).lower()))[:20]


def _row(r) -> dict:
    d = dict(zip([c.strip() for c in COLS.split(",")], r))
    d["channels"] = len((d["info"] or {}).get("channels", []))
    return d


def registry(enabled_only: bool = False) -> list[dict]:
    """Registered NVRs without passwords. Empty if the table doesn't exist yet."""
    try:
        with connect() as conn:
            rows = conn.execute(f"SELECT {COLS} FROM nvrs" + (" WHERE enabled" if enabled_only else "") + " ORDER BY alias").fetchall()
    except Exception:
        return []
    return [_row(r) for r in rows]


def registry_alias(address: str) -> str | None:
    for n in registry():
        if n["address"] == address or host(n["address"]) == host(address):
            return n["alias"]
    return None


def overrides() -> dict[str, dict]:
    try:
        with connect() as conn:
            rows = conn.execute("SELECT camera_id, tier, note, updated_by, updated_at FROM camera_overrides").fetchall()
    except Exception:
        return {}
    return {r[0]: {"tier": r[1], "note": r[2], "by": r[3], "at": r[4]} for r in rows}


# ------------------------------------------------------------------ models

class NvrIn(BaseModel):
    address: str = Field(min_length=1, max_length=255)
    name: str = Field(default="", max_length=60)
    alias: str = Field(default="", max_length=20)
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(default="", max_length=128)        # blank on edit = keep the stored one
    scheme: str = Field(default="http", pattern=r"^https?$")
    rtsp_port: int = Field(default=554, ge=1, le=65535)
    segment: str = Field(default="", max_length=60)
    enabled: bool = True
    live_view: bool = True
    save_anyway: bool = False                                # store even if the connection test fails

    @field_validator("address")
    @classmethod
    def _addr(cls, v: str) -> str:
        v = v.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
        if not ADDRESS.match(v):
            raise ValueError("Enter the NVR's IP address or host name, with :port only if its web port isn't 80, e.g. 10.1.3.4")
        return v

    @field_validator("alias")
    @classmethod
    def _alias(cls, v: str) -> str:
        v = v.strip().lower()
        if v and not ALIAS.match(v):
            raise ValueError("Short name: 2 to 20 lowercase letters and digits, starting with a letter, e.g. nvr4")
        return v


class TierIn(BaseModel):
    tier: str | None = Field(default=None, pattern=r"^[ENS]$")     # None = back to automatic
    note: str = Field(default="", max_length=200)


# ------------------------------------------------------------------ endpoints

@router.get("/nvrs")
def list_nvrs(_: dict = Depends(require("admin", "cso"))) -> list[dict]:
    return registry()


def _test(body: NvrIn, password: str) -> tuple[bool, str, dict]:
    try:
        info = read_nvr(body.address, body.username, password, scheme=body.scheme)
    except DeviceError as exc:
        return False, str(exc), {}
    detail = f"{info['model'] or 'NVR'} answered: {len(info['channels'])} channels"
    if info["warnings"]:
        detail += f" ({'; '.join(info['warnings'])})"
    return True, detail, info


@router.post("/nvrs", status_code=201)
def add_nvr(body: NvrIn, request: Request, admin: dict = Depends(require("admin"))) -> dict:
    if not body.password:
        raise HTTPException(status_code=422, detail="Enter the NVR user's password.")
    alias = body.alias or default_alias(body.address)
    with connect() as conn:
        clash = conn.execute("SELECT address, alias FROM nvrs WHERE address = %s OR alias = %s", (body.address, alias)).fetchone()
    if clash:
        raise HTTPException(status_code=409, detail=f"{clash[0]} is already registered" if clash[0] == body.address else
                            f"The short name {alias} is taken by {clash[0]}; choose another.")
    ok, detail, info = _test(body, body.password)
    if not ok and not body.save_anyway:
        raise HTTPException(status_code=422, detail=f"Connection test failed: {detail}")
    from .licence import allows
    current = registry()
    allowed, why = allows("nvr", nvrs=len(current) + 1, cameras=sum(n["channels"] for n in current) + len(info.get("channels", [])))
    if not allowed:
        raise HTTPException(status_code=402, detail=why)
    with connect() as conn:
        nid = conn.execute(
            "INSERT INTO nvrs (address, alias, name, username, secret, scheme, rtsp_port, segment, enabled, live_view, info, "
            "test_ok, test_detail, tested_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, now()) RETURNING id",
            (body.address, alias, body.name or info.get("name", ""), body.username, vault.encrypt(body.password), body.scheme,
             body.rtsp_port, body.segment, body.enabled, body.live_view, Jsonb(info), ok, detail)).fetchone()[0]
    audit("nvr_added", user_id=admin["id"], username=admin["username"], ip=client_ip(request),
          address=body.address, alias=alias, test=detail)
    _sync_soon()
    return _get(nid)


@router.put("/nvrs/{nid}")
def edit_nvr(nid: int, body: NvrIn, request: Request, admin: dict = Depends(require("admin"))) -> dict:
    old = _get(nid)
    alias = body.alias or old["alias"]
    with connect() as conn:
        clash = conn.execute("SELECT address FROM nvrs WHERE (address = %s OR alias = %s) AND id <> %s",
                             (body.address, alias, nid)).fetchone()
        secret = conn.execute("SELECT secret FROM nvrs WHERE id = %s", (nid,)).fetchone()[0]
    if clash:
        raise HTTPException(status_code=409, detail=f"Another NVR ({clash[0]}) already uses that address or short name.")
    password = body.password or vault.decrypt(secret)
    ok, detail, info = _test(body, password)
    if not ok and not body.save_anyway:
        raise HTTPException(status_code=422, detail=f"Connection test failed: {detail}")
    with connect() as conn:
        conn.execute(
            "UPDATE nvrs SET address = %s, alias = %s, name = %s, username = %s, secret = %s, scheme = %s, rtsp_port = %s, "
            "segment = %s, enabled = %s, live_view = %s, info = CASE WHEN %s THEN %s ELSE info END, test_ok = %s, "
            "test_detail = %s, tested_at = now(), updated_at = now() WHERE id = %s",
            (body.address, alias, body.name or old["name"], body.username,
             vault.encrypt(body.password) if body.password else secret, body.scheme, body.rtsp_port, body.segment,
             body.enabled, body.live_view, ok, Jsonb(info), ok, detail, nid))
    changed = [k for k in ("address", "alias", "name", "username", "scheme", "rtsp_port", "segment", "enabled", "live_view")
               if getattr(body, k) != old[k] and not (k in ("alias", "name") and not getattr(body, k))]
    audit("nvr_changed", user_id=admin["id"], username=admin["username"], ip=client_ip(request), address=body.address,
          changed=", ".join(changed + (["password"] if body.password else [])) or "nothing", test=detail)
    _sync_soon()
    return _get(nid)


@router.post("/nvrs/{nid}/test")
def test_nvr(nid: int, _: dict = Depends(require("admin"))) -> dict:
    n = _get(nid)
    with connect() as conn:
        secret = conn.execute("SELECT secret FROM nvrs WHERE id = %s", (nid,)).fetchone()[0]
    body = NvrIn(address=n["address"], username=n["username"], scheme=n["scheme"])
    ok, detail, info = _test(body, vault.decrypt(secret))
    with connect() as conn:
        conn.execute("UPDATE nvrs SET test_ok = %s, test_detail = %s, tested_at = now(), "
                     "info = CASE WHEN %s THEN %s ELSE info END WHERE id = %s", (ok, detail, ok, Jsonb(info), nid))
    _sync_soon()
    return _get(nid)


@router.delete("/nvrs/{nid}")
def remove_nvr(nid: int, request: Request, admin: dict = Depends(require("admin"))) -> dict:
    n = _get(nid)
    with connect() as conn:
        conn.execute("DELETE FROM nvrs WHERE id = %s", (nid,))
    audit("nvr_removed", user_id=admin["id"], username=admin["username"], ip=client_ip(request), address=n["address"], alias=n["alias"])
    _sync_soon()
    return {"removed": n["address"]}


def _get(nid: int) -> dict:
    with connect() as conn:
        r = conn.execute(f"SELECT {COLS} FROM nvrs WHERE id = %s", (nid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="no such NVR")
    return _row(r)


@router.get("/nvrs/edge", dependencies=[Depends(check_worker_token)])
def nvrs_for_edge() -> list[dict]:
    """The edge service's NVR list, with passwords. Only the worker token can read this."""
    with connect() as conn:
        rows = conn.execute("SELECT address, alias, username, secret, scheme, rtsp_port FROM nvrs WHERE enabled ORDER BY alias").fetchall()
    out = []
    for a, al, u, s, sc, rp in rows:
        try:
            out.append({"address": a, "alias": al, "username": u, "password": vault.decrypt(s), "scheme": sc, "rtsp_port": rp})
        except vault.VaultError as exc:
            log.error("%s: %s", a, exc)
    return out


@router.put("/cameras/{camera_id}/tier")
def set_tier(camera_id: str, body: TierIn, request: Request, user: dict = Depends(require("admin", "cso"))) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9]{1,19}-ch\d{2,3}", camera_id):
        raise HTTPException(status_code=422, detail="camera id looks like nvr4-ch22")
    with connect() as conn:
        if body.tier is None:
            conn.execute("DELETE FROM camera_overrides WHERE camera_id = %s", (camera_id,))
        else:
            conn.execute("INSERT INTO camera_overrides (camera_id, tier, note, updated_by, updated_at) VALUES (%s, %s, %s, %s, now()) "
                         "ON CONFLICT (camera_id) DO UPDATE SET tier = EXCLUDED.tier, note = EXCLUDED.note, "
                         "updated_by = EXCLUDED.updated_by, updated_at = now()", (camera_id, body.tier, body.note, user["username"]))
    audit("tier_changed", user_id=user["id"], username=user["username"], ip=client_ip(request), camera=camera_id,
          tier=body.tier or "automatic", note=body.note)
    return {"camera_id": camera_id, "tier": body.tier, "note": body.note}


# ------------------------------------------------------------------ stream gateway paths

def desired_paths() -> dict[str, str]:
    """Gateway path name -> RTSP source (sub-stream, N02) for every channel of every NVR with live view on."""
    out = {}
    with connect() as conn:
        rows = conn.execute("SELECT address, alias, username, secret, rtsp_port, info FROM nvrs WHERE enabled AND live_view").fetchall()
    for address, alias, user, secret, port, info in rows:
        try:
            pw = vault.decrypt(secret)
        except vault.VaultError:
            continue
        cred = f"{quote(user, safe='')}:{quote(pw, safe='')}"
        for ch in (info or {}).get("channels", []):
            out[f"{alias}-ch{int(ch['id']):02d}"] = f"rtsp://{cred}@{host(address)}:{port}/Streaming/Channels/{int(ch['id'])}02"
    return out


def plan_sync(desired: dict[str, str], configured: dict[str, str], owned: set[str]) -> dict[str, list]:
    """What to add, change and remove in the gateway (pure function, tested).
    Paths we didn't add (gateway/cameras.env) are never touched."""
    add = [n for n in desired if n not in configured]
    change = [n for n in desired if n in configured and n in owned and configured[n] != desired[n]]
    remove = [n for n in owned if n not in desired and n in configured]
    keep_env = [n for n in desired if n in configured and n not in owned]
    return {"add": sorted(add), "change": sorted(change), "remove": sorted(remove), "env": sorted(keep_env)}


def sync_gateway() -> dict:
    url = os.environ.get("HSS_GATEWAY_API", "http://gateway:9997")
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = 'gateway_owned_paths'").fetchone()
    owned = set(row[0]) if row else set()
    desired = desired_paths()
    with httpx.Client(base_url=url, timeout=5) as gw:
        r = gw.get("/v3/config/paths/list", params={"itemsPerPage": 1000})
        r.raise_for_status()
        configured = {i["name"]: i.get("source", "") for i in r.json().get("items", [])}
        plan = plan_sync(desired, configured, owned)
        for n in plan["add"]:
            gw.post(f"/v3/config/paths/add/{n}", json={"source": desired[n], "sourceOnDemand": True}).raise_for_status()
            owned.add(n)
        for n in plan["change"]:
            gw.patch(f"/v3/config/paths/patch/{n}", json={"source": desired[n]}).raise_for_status()
        for n in plan["remove"]:
            gw.delete(f"/v3/config/paths/delete/{n}").raise_for_status()
            owned.discard(n)
    owned &= set(desired)          # forget paths that went away with a gateway restart
    with connect() as conn:
        conn.execute("INSERT INTO settings (key, value) VALUES ('gateway_owned_paths', %s) "
                     "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value", (Jsonb(sorted(owned)),))
    if plan["add"] or plan["change"] or plan["remove"]:
        log.info("gateway paths: %d added, %d changed, %d removed", len(plan["add"]), len(plan["change"]), len(plan["remove"]))
    return {k: len(v) for k, v in plan.items()}


_wake: asyncio.Event | None = None
_loop: asyncio.AbstractEventLoop | None = None


def _sync_soon() -> None:
    if _wake is not None and _loop is not None:
        _loop.call_soon_threadsafe(_wake.set)


async def background_loop(every_s: float = 120) -> None:
    global _wake, _loop
    _wake, _loop = asyncio.Event(), asyncio.get_running_loop()
    await asyncio.sleep(5)
    while True:
        try:
            await asyncio.to_thread(sync_gateway)
        except Exception as exc:       # gateway down or restarting: try again next round
            (log.warning if registry() else log.debug)("gateway sync: %s", exc)
        try:
            await asyncio.wait_for(_wake.wait(), timeout=every_s)
        except asyncio.TimeoutError:
            pass
        _wake.clear()
