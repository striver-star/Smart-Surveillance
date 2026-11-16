#!/usr/bin/env python3
"""A pretend Hikvision access controller or video intercom door station, for training, demos and tests before
real devices exist. Standard library only. It answers the ISAPI calls HSS uses (access_control.py); it is not a
full device.

    python3 tools/simulators/hik-access-sim.py controller 8601 --doors 2
    python3 tools/simulators/hik-access-sim.py doorstation 8602

Add it in the console (Doors › Add device) with address <this computer>:8601, any user and password.
Make things happen (from a browser or curl on the same computer):

    /test/swipe?door=1&name=Ada%20Obi&ok=1     a card or face: granted (ok=1) or refused (ok=0)
    /test/forced?door=1                        door forced open
    /test/held?door=1                          door held open
    /test/contact?door=1&open=1                door contact open (1) or closed (0)
    /test/ring                                 the door station rings (doorstation only)
"""
from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

KIND = sys.argv[1] if len(sys.argv) > 1 else "controller"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8601
DOORS = int(sys.argv[sys.argv.index("--doors") + 1]) if "--doors" in sys.argv else (2 if KIND == "controller" else 1)
lock = threading.Lock()
state = {"events": [], "serial": 1000, "lock": [0] * DOORS, "mode": [4] * DOORS, "contact": [0] * DOORS, "call": "idle", "commands": []}


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def add(minor: int, door: int, **kw) -> None:
    with lock:
        state["serial"] += 1
        state["events"].append({"major": 5, "minor": minor, "time": now(), "doorNo": door, "serialNo": state["serial"], **kw})


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code: int, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        door = int(q.get("door", 1))
        if u.path == "/ISAPI/System/deviceInfo":
            model = "DS-K2602T (simulated)" if KIND == "controller" else "DS-KV8113-WME1 (simulated)"
            return self.send(200, f"<DeviceInfo><deviceName>{KIND} simulator</deviceName><model>{model}</model><serialNumber>SIM{PORT}</serialNumber>"
                                  f"<firmwareVersion>V1.0 sim</firmwareVersion><deviceType>ACS</deviceType></DeviceInfo>", "application/xml")
        if u.path == "/ISAPI/AccessControl/AcsWorkStatus":
            with lock:
                return self.send(200, {"AcsWorkStatus": {"doorLockStatus": state["lock"], "doorStatus": state["mode"], "magneticStatus": state["contact"]}})
        if u.path == "/ISAPI/VideoIntercom/callStatus":
            return self.send(200, {"CallStatus": {"status": state["call"]}})
        if u.path == "/test/swipe":
            ok = q.get("ok", "1") == "1"
            add(75 if ok else 76, door, name=q.get("name", ""), employeeNoString=q.get("emp", ""), cardNo=q.get("card", "1234567890"), currentVerifyMode="cardOrFace")
            if ok:
                add(21, door)
                threading.Timer(5, lambda d=door: add(22, d)).start()
            return self.send(200, {"ok": True})
        if u.path == "/test/forced":
            add(27, door)
            with lock:
                state["contact"][door - 1] = 1
            return self.send(200, {"ok": True})
        if u.path == "/test/held":
            add(28, door)
            return self.send(200, {"ok": True})
        if u.path == "/test/contact":
            o = q.get("open", "1") == "1"
            add(25 if o else 26, door)
            with lock:
                state["contact"][door - 1] = 1 if o else 0
            return self.send(200, {"ok": True})
        if u.path == "/test/ring":
            state["call"] = "ring"
            return self.send(200, {"ok": True})
        if u.path == "/test/commands":
            return self.send(200, state["commands"])
        self.send(404, {"error": "not simulated"})

    def do_POST(self):
        u = urlparse(self.path)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        if u.path == "/ISAPI/AccessControl/AcsEvent":
            c = body.get("AcsEventCond", {})
            start, end = datetime.fromisoformat(c["startTime"]), datetime.fromisoformat(c["endTime"])
            with lock:
                hits = [e for e in state["events"] if start <= datetime.fromisoformat(e["time"]) <= end]
            pos, n = int(c.get("searchResultPosition", 0)), int(c.get("maxResults", 30))
            page = hits[pos:pos + n]
            return self.send(200, {"AcsEvent": {"searchID": c.get("searchID"), "totalMatches": len(hits), "numOfMatches": len(page),
                                                "responseStatusStrg": "MORE" if pos + n < len(hits) else ("OK" if hits else "NO MATCH"), "InfoList": page}})
        self.send(404, {"error": "not simulated"})

    def do_PUT(self):
        u = urlparse(self.path)
        raw = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0).decode()
        if u.path.startswith("/ISAPI/AccessControl/RemoteControl/door/"):
            door = int(u.path.rsplit("/", 1)[1])
            cmd = raw.split("<cmd>")[1].split("</cmd>")[0]
            with lock:
                state["commands"].append({"door": door, "cmd": cmd, "at": now()})
                state["mode"][door - 1] = {"alwaysOpen": 2, "alwaysClose": 3}.get(cmd, 4)
                state["lock"][door - 1] = 1 if cmd in ("open", "alwaysOpen") else 0
            if cmd == "open":                       # like a real lock: unlock, then relock after 5 seconds
                add(21, door)
                def relock(d=door):
                    with lock:
                        if state["mode"][d - 1] == 4:
                            state["lock"][d - 1] = 0
                    add(22, d)
                threading.Timer(5, relock).start()
            return self.send(200, "<ResponseStatus><statusCode>1</statusCode></ResponseStatus>", "application/xml")
        if u.path == "/ISAPI/VideoIntercom/callSignal":
            cmd = json.loads(raw or "{}").get("CallSignal", {}).get("cmdType")
            state["commands"].append({"call": cmd, "at": now()})
            state["call"] = "idle" if cmd in ("reject", "hangUp") else "onCall"
            return self.send(200, {"statusCode": 1})
        self.send(404, {"error": "not simulated"})


print(f"{KIND} simulator on port {PORT} with {DOORS} door(s)")
ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
