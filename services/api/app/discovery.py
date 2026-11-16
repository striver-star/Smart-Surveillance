"""Network discovery for new sites (release 2.0, third batch): find the Hikvision NVRs and cameras on the
site's network from the console, then identify and add them.

A scan checks every address in the given private ranges (at most 4,096 addresses) for the ports Hikvision
devices answer on (80, 443, 8000 for the SDK, 554 for RTSP). Devices that answer are fingerprinted without
logging in: the web server's name, the login realm, the activation page. That tells a Hikvision NVR from a
camera, shows devices still waiting to be activated, and marks the NVRs already added in Devices.
"Identify" then logs in with credentials the administrator types (not stored) for the model, serial,
firmware and channels, and "Add as NVR" opens the usual form.

Hikvision's own multicast discovery (SADP) only works on the same network segment and not from inside
Docker; tools/discovery/hss-sadp.py runs it on the server itself.

Only private addresses can be scanned (10/8, 172.16/12, 192.168/16, 169.254/16), and every scan is audited.
"""
from __future__ import annotations

import ipaddress
import logging
import os
import re
import socket
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import audit, client_ip, require
from .db import connect

log = logging.getLogger("hss.discovery")
router = APIRouter(prefix="/discovery", tags=["discovery"])
PORTS = (80, 443, 8000, 554)
MAX_ADDRESSES = 4096
PRIVATE = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")]
NVR_SERVERS = re.compile(r"DNVRS-Webs|DVRDVS-Webs", re.I)
HIK_SERVERS = re.compile(r"DNVRS-Webs|DVRDVS-Webs|App-webs|Hikvision-Webs", re.I)
NVR_MODEL = re.compile(r"\b(i?DS-(7|8|9)\d|NVR|DVR)", re.I)
CAM_MODEL = re.compile(r"\b(i?DS-2|IP ?Camera|IPC)", re.I)


# ------------------------------------------------------------------ pure helpers (tested)

def parse_targets(text: str) -> list[str]:
    """'10.1.3.0/24, 10.1.4.10-20, 10.1.5.7' -> addresses. Private ranges only, at most MAX_ADDRESSES (pure, tested)."""
    out: list[str] = []
    for part in re.split(r"[,\s]+", text.strip()):
        if not part:
            continue
        try:
            if "/" in part:
                net = ipaddress.ip_network(part, strict=False)
                hosts = [str(h) for h in (net.hosts() if net.num_addresses > 2 else net)]
                if net.num_addresses > MAX_ADDRESSES:
                    raise HTTPException(status_code=422, detail=f"{part} is too large: scan at most {MAX_ADDRESSES} addresses (a /20) at a time.")
                first = net.network_address
            elif "-" in part:
                a, b = part.split("-", 1)
                start = ipaddress.ip_address(a)
                end = ipaddress.ip_address(b) if "." in b else ipaddress.ip_address(".".join(a.split(".")[:3] + [b]))
                if int(end) < int(start) or int(end) - int(start) >= MAX_ADDRESSES:
                    raise HTTPException(status_code=422, detail=f"{part}: give a range of at most {MAX_ADDRESSES} addresses, low to high.")
                hosts = [str(ipaddress.ip_address(i)) for i in range(int(start), int(end) + 1)]
                first = start
            else:
                first = ipaddress.ip_address(part)
                hosts = [part]
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"'{part[:40]}' isn't an address, a range (10.1.3.10-50) or a network (10.1.3.0/24).") from exc
        if first.version != 4 or not any(first in n for n in PRIVATE):
            raise HTTPException(status_code=422, detail=f"{part}: only the site's private addresses can be scanned (10.x, 172.16-31.x, 192.168.x).")
        seen = set(out)
        out += [h for h in hosts if h not in seen]
        if len(out) > MAX_ADDRESSES:
            raise HTTPException(status_code=422, detail=f"Scan at most {MAX_ADDRESSES} addresses at a time.")
    if not out:
        raise HTTPException(status_code=422, detail="Give at least one address, range or network.")
    return out


def fingerprint(ports: list[int], server: str = "", realm: str = "", body: str = "", activated: bool | None = None,
                has_activate_page: bool = False) -> dict:
    """What a device probably is, from what it shows without a login (pure, tested)."""
    hik = bool(HIK_SERVERS.search(server)) or has_activate_page or bool(re.search(r"\bDS-|HIK", realm, re.I)) \
        or (8000 in ports and "doc/page/login.asp" in body)
    if hik:
        hint = f"{server} {realm}"
        kind = "nvr" if NVR_SERVERS.search(server) or NVR_MODEL.search(realm) else "camera" if CAM_MODEL.search(hint) or "App-webs" in server else "hikvision"
    elif 554 in ports:
        kind = "other_camera"
    elif ports:
        kind = "other"
    else:
        kind = "none"
    notes = []
    if hik and activated is False:
        notes.append("Not activated: set a strong admin password first (SADP or the device's web page).")
    if hik and 8000 in ports and not ({80, 443} & set(ports)):
        notes.append("Only the SDK port answers: turn on the web server (HTTP/HTTPS) so the platform can use ISAPI.")
    if kind == "other_camera":
        notes.append("Answers on RTSP but isn't recognised as Hikvision: another make, or Hikvision with the web server off.")
    return {"vendor": "hikvision" if hik else None, "kind": kind, "activated": activated, "notes": notes,
            "model_hint": (re.search(r"i?DS-[0-9A-Z-]+", realm) or [None])[0]}


# ------------------------------------------------------------------ scanning

def _open_ports(ip: str, ports: list[int], timeout: float) -> list[int]:
    found = []
    for p in ports:
        try:
            with socket.create_connection((ip, p), timeout=timeout):
                found.append(p)
        except OSError:
            pass
    return found


def _probe(ip: str, ports: list[int], web_ports: list[int]) -> dict:
    server, realm, body, activated, has_page, scheme, port = "", "", "", None, False, None, None
    web = [p for p in web_ports if p in ports]
    for p in web:
        sch = "https" if p == 443 or p % 1000 == 443 else "http"
        base = f"{sch}://{ip}" + ("" if p in (80, 443) else f":{p}")
        try:
            with httpx.Client(base_url=base, timeout=2.5, verify=False, follow_redirects=False) as http:
                r = http.get("/")
                server, body = r.headers.get("server", ""), r.text[:4000]
                a = http.get("/SDK/activateStatus")
                if a.status_code == 200 and "<Activated>" in a.text:
                    has_page = True
                    activated = "<Activated>true</Activated>" in a.text.replace(" ", "")
                d = http.get("/ISAPI/System/deviceInfo")
                server = server or d.headers.get("server", "")
                m = re.search(r'realm="([^"]*)"', d.headers.get("www-authenticate", ""))
                realm = m.group(1) if m else ""
                scheme, port = sch, p
                break
        except httpx.HTTPError:
            continue
    fp = fingerprint(ports, server, realm, body, activated, has_page)
    address = ip if port in (None, 80, 443) else f"{ip}:{port}"
    return {"ip": ip, "address": address, "scheme": scheme or "http", "ports": ports, "server": server[:60], "realm": realm[:80], **fp}


class Scans:
    def __init__(self):
        self.lock = threading.Lock()
        self.items: dict[str, dict] = {}

    def start(self, targets: list[str], ports: list[int], by: str) -> str:
        sid = uuid.uuid4().hex[:12]
        with self.lock:
            if any(s["state"] == "running" for s in self.items.values()):
                raise HTTPException(status_code=409, detail="A scan is already running; wait for it to finish.")
            self.items = {k: v for k, v in self.items.items() if time.time() - v["started"] < 6 * 3600}
            self.items[sid] = {"id": sid, "state": "running", "started": time.time(), "by": by, "total": len(targets), "done": 0,
                               "devices": [], "ports": ports}
        threading.Thread(target=self._run, args=(sid, targets, ports), daemon=True).start()
        return sid

    def _run(self, sid: str, targets: list[str], ports: list[int]) -> None:
        web_ports = [p for p in ports if p not in (554, 8000)]
        try:
            def one(ip):
                open_ = _open_ports(ip, ports, 0.6)
                with self.lock:
                    self.items[sid]["done"] += 1
                if open_:
                    d = _probe(ip, open_, web_ports)
                    with self.lock:
                        self.items[sid]["devices"].append(d)
            with ThreadPoolExecutor(max_workers=96) as pool:
                list(pool.map(one, targets))
            state = "done"
        except Exception as exc:          # a broken scan must say so, not hang at "running"
            log.exception("scan %s failed", sid)
            state = f"failed: {exc.__class__.__name__}"
        with self.lock:
            self.items[sid]["state"] = state
            self.items[sid]["finished"] = time.time()

    def get(self, sid: str) -> dict:
        with self.lock:
            s = self.items.get(sid)
            if not s:
                raise HTTPException(status_code=404, detail="no such scan (scans are kept for 6 hours)")
            return {**s, "devices": sorted(s["devices"], key=lambda d: tuple(int(x) for x in d["ip"].split(".")))}


scans = Scans()


def _registered() -> dict[str, str]:
    with connect() as conn:
        return {a: alias for a, alias in conn.execute("SELECT address, alias FROM nvrs").fetchall()}


# ------------------------------------------------------------------ endpoints

@router.get("/suggest")
def suggest(_: dict = Depends(require("admin"))) -> dict:
    """Ranges to start from: the server's own network and those of the NVRs already added."""
    nets = []
    server = os.environ.get("HSS_SERVER_IP", "")
    for ip in [server] + [a.split(":")[0] for a in _registered()]:
        try:
            a = ipaddress.ip_address(ip)
        except ValueError:
            continue
        if a.version == 4 and any(a in n for n in PRIVATE) and not a.is_loopback:
            net = str(ipaddress.ip_network(f"{ip}/24", strict=False))
            if net not in nets:
                nets.append(net)
    return {"ranges": nets, "ports": list(PORTS)}


class ScanIn(BaseModel):
    targets: str = Field(min_length=1, max_length=2000)
    ports: list[int] = Field(default_factory=lambda: list(PORTS), max_length=8)


@router.post("/scans", status_code=202)
def start_scan(body: ScanIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    targets = parse_targets(body.targets)
    ports = [p for p in body.ports if 1 <= p <= 65535] or list(PORTS)
    sid = scans.start(targets, ports, user["username"])
    audit("network_scan", user_id=user["id"], username=user["username"], ip=client_ip(request), targets=body.targets[:200],
          addresses=len(targets), ports=ports)
    return {"id": sid, "addresses": len(targets)}


@router.get("/scans/{sid}")
def scan(sid: str, _: dict = Depends(require("admin"))) -> dict:
    s = scans.get(sid)
    reg = _registered()
    for d in s["devices"]:
        d["registered"] = reg.get(d["address"]) or reg.get(d["ip"])          # added as "10.1.3.4" or "10.1.3.4:8080"
    hik = [d for d in s["devices"] if d["vendor"] == "hikvision"]
    s["summary"] = {"answered": len(s["devices"]), "nvrs": sum(d["kind"] == "nvr" for d in hik),
                    "cameras": sum(d["kind"] == "camera" for d in hik), "not_activated": sum(d["activated"] is False for d in hik),
                    "new_nvrs": sum(d["kind"] == "nvr" and not d["registered"] for d in hik)}
    s["started_at"] = datetime.fromtimestamp(s["started"], timezone.utc)
    return s


class IdentifyIn(BaseModel):
    address: str = Field(min_length=3, max_length=255)
    scheme: str = Field(default="http", pattern=r"^https?$")
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@router.post("/identify")
def identify(body: IdentifyIn, request: Request, user: dict = Depends(require("admin"))) -> dict:
    """Log in once (the password isn't stored) for the model, serial, firmware and, for an NVR, its channels."""
    host = body.address.split(":")[0]
    try:
        if not any(ipaddress.ip_address(host) in n for n in PRIVATE):
            raise HTTPException(status_code=422, detail="Only devices on the site's private network.")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Give the device's IP address.") from exc
    from .isapi import DeviceError, read_nvr
    try:
        info = read_nvr(body.address, body.username, body.password, scheme=body.scheme, timeout=6)
    except DeviceError as exc:
        audit("device_identify", user_id=user["id"], username=user["username"], ip=client_ip(request), device=body.address, ok=False)
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit("device_identify", user_id=user["id"], username=user["username"], ip=client_ip(request), device=body.address, ok=True,
          model=info.get("model"))
    kind = "nvr" if info["channels"] or NVR_MODEL.search(info.get("model", "")) else "camera"
    return {"address": body.address, "scheme": body.scheme, "kind": kind, "name": info.get("name"), "model": info.get("model"),
            "serial": info.get("serial"), "firmware": info.get("firmware"), "channels": len(info["channels"]),
            "online": sum(1 for c in info["channels"] if c.get("online")), "disks": info.get("disks", []), "warnings": info.get("warnings", [])}
