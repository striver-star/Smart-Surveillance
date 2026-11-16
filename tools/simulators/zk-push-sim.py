#!/usr/bin/env python3
"""A pretend ZKTeco access panel (or terminal, --terminal) that calls in to HSS over the push protocol, for testing
and operator training before real devices arrive. Python standard library only.

    python3 tools/simulators/zk-push-sim.py http://SERVER:8088 --serial ZKSIM0001 --doors 2 --port 8603

It calls in every 2 seconds, sends its users, collects and carries out door commands (an open relocks after 5 s).
Make events from a browser on the same machine:
    http://127.0.0.1:8603/test/swipe?door=1&pin=1001&ok=1   (ok=0: refused)
    /test/forced?door=1   /test/held?door=1   /test/duress?door=1&pin=1001   /test/contact?door=1&open=1
    /test/commands        (the commands it has carried out)
"""
import argparse
import json
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

USERS = {"1001": "Ada Obi", "1002": "Musa Bello", "1003": "Grace Eze"}
EVENT = {"ok": 0, "refused": 27, "forced": 102, "held": 28, "duress": 101, "open": 200, "closed": 201}


class Panel:
    def __init__(self, server, serial, doors, terminal):
        self.server, self.serial, self.n, self.terminal = server.rstrip("/"), serial, doors, terminal
        self.index = int(time.time()) % 100000
        self.relay = [0] * doors          # 1 = unlocked
        self.sensor = [1] * doors         # 1 = closed, 2 = open
        self.done = []
        self.lock = threading.Lock()

    def http(self, method, path, body=None):
        url = f"{self.server}/iclock/{path}{'&' if '?' in path else '?'}SN={self.serial}"
        req = urllib.request.Request(url, data=body.encode() if body is not None else None, method=method)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()

    def now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def rtlog(self, door, event, pin="0", card="0", verify=4):
        with self.lock:
            self.index += 1
            i = self.index
        if self.terminal:
            if event != 0:
                return                    # terminals only report successful verifications
            line = f"{pin}\t{self.now()}\t0\t{15 if verify == 15 else 2}\t0\t0"
            self.http("POST", "cdata?table=ATTLOG", line)
            return
        line = (f"time={self.now()}\tpin={pin}\tcardno={card}\tsitecode=0\tlinkid=0\teventaddr={door}\tevent={event}\t"
                f"inoutstatus=0\tverifytype={verify}\tindex={i}")
        self.http("POST", "cdata?table=rtlog", line)

    def rtstate(self):
        if self.terminal:
            return
        sensor = "".join(f"{s:02X}" for s in self.sensor)
        relay = f"{sum(r << i for i, r in enumerate(self.relay)):02X}"
        self.http("POST", "cdata?table=rtstate", f"time={self.now()}\tsensor={sensor}\trelay={relay}\talarm=00000000\tdoor=00")

    def run_command(self, cid, cmd):
        ok = 0
        p = cmd.split()
        if cmd.startswith("DATA QUERY"):
            want = "tablename=user" if not self.terminal else "USERINFO"
            if want in cmd:
                if self.terminal:
                    self.http("POST", "cdata?table=USERINFO", "\n".join(f"PIN={p}\tName={n}\tPri=0\tCard=" for p, n in USERS.items()))
                else:
                    self.http("POST", "querydata?type=tabledata&tablename=user&count=3&packcnt=1&packidx=1",
                              "\n".join(f"user uid={i}\tpin={p}\tname={n}\tprivilege=0" for i, (p, n) in enumerate(USERS.items(), 1)))
            else:
                ok = -1002
            self.done.append({"id": cid, "cmd": cmd, "return": ok, "at": self.now()})
            self.http("POST", "devicecmd", f"ID={cid}&Return={ok}&CMD=DATA")
            return
        if p[:2] == ["CONTROL", "DEVICE"] and len(p) == 3 and len(p[2]) == 10:
            op, door, out, secs = (int(p[2][i:i + 2], 16) for i in (0, 2, 4, 6))
            if 1 <= door <= self.n:
                if op == 1 and out == 1:
                    self.relay[door - 1] = 1 if secs else 0
                    if secs and secs != 255:
                        threading.Timer(min(secs, 30), self.relock, (door,)).start()
                    if secs:
                        self.rtlog(door, 8)
                elif op != 4:
                    ok = -1
            else:
                ok = -1
        else:
            ok = -1
        self.done.append({"id": cid, "cmd": cmd, "return": ok, "at": self.now()})
        self.http("POST", "devicecmd", f"ID={cid}&Return={ok}&CMD={p[0] if p else ''}")
        self.rtstate()

    def relock(self, door):
        self.relay[door - 1] = 0
        self.rtstate()

    def loop(self):
        sent_users, beat = False, 0
        while True:
            try:
                self.http("GET", "cdata?options=all&pushver=2.4.1&language=69")
                if not sent_users:
                    self.http("POST", "cdata?table=USERINFO", "\n".join(f"PIN={p}\tName={n}\tPri=0\tCard=" for p, n in USERS.items()))
                    sent_users = True
                    self.rtstate()
                beat += 1
                if beat % 15 == 0:
                    self.rtstate()                        # real panels also send their state now and then
                for line in self.http("GET", "getrequest").splitlines():
                    if line.startswith("C:"):
                        _, cid, cmd = line.split(":", 2)
                        self.run_command(cid, cmd)
            except Exception as exc:                      # server down: keep trying, like a real device
                print("call-in failed:", exc)
                sent_users = False
            time.sleep(2)


def handler(panel):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(u.query))
            door = int(q.get("door", 1))
            what = u.path.rsplit("/", 1)[-1]
            try:
                if what == "swipe":
                    pin = q.get("pin", "1001")
                    panel.rtlog(door, EVENT["ok"] if q.get("ok", "1") == "1" else EVENT["refused"], pin, q.get("card", "0012345678"), int(q.get("verify", 4)))
                elif what in ("forced", "held"):
                    panel.sensor[door - 1] = 2
                    panel.rtstate()
                    panel.rtlog(door, EVENT[what])
                elif what == "duress":
                    panel.rtlog(door, EVENT["duress"], q.get("pin", "1001"))
                elif what == "contact":
                    panel.sensor[door - 1] = 2 if q.get("open") == "1" else 1
                    panel.rtstate()
                    panel.rtlog(door, EVENT["open" if q.get("open") == "1" else "closed"])
                elif what == "commands":
                    pass
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                body = json.dumps({"ok": True, "commands": panel.done[-20:], "relay": panel.relay, "sensor": panel.sensor}).encode()
                self.send_response(200)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode()
                self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
    return H


if __name__ == "__main__":
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    a.add_argument("server", help="http://SERVER:8088")
    a.add_argument("--serial", default="ZKSIM0001")
    a.add_argument("--doors", type=int, default=2, choices=(1, 2, 4))
    a.add_argument("--terminal", action="store_true", help="behave like a standalone face/card terminal (ATTLOG)")
    a.add_argument("--port", type=int, default=8603, help="local port for /test/... links")
    args = a.parse_args()
    p = Panel(args.server, args.serial, 1 if args.terminal else args.doors, args.terminal)
    threading.Thread(target=p.loop, daemon=True).start()
    print(f"ZKTeco {'terminal' if args.terminal else 'panel'} {args.serial} calling {args.server}; test links on http://127.0.0.1:{args.port}/test/...")
    ThreadingHTTPServer(("0.0.0.0", args.port), handler(p)).serve_forever()
