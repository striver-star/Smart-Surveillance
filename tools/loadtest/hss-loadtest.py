#!/usr/bin/env python3
"""HSS load test (Phase 8 gate: 20 NVRs). Simulates NVRs posting events and health to the API and
measures how fast it answers. Standard library only; meant to run inside the API container, which has
the database address and the worker token:

  docker compose run --rm --no-deps -v ./tools/loadtest:/lt api python /lt/hss-loadtest.py \
      --nvrs 20 --cameras 32 --events-per-cam-min 2 --minutes 10
  docker compose run --rm --no-deps -v ./tools/loadtest:/lt api python /lt/hss-loadtest.py --cleanup

Events are info and warning only (never critical) so no WhatsApp messages go out; camera ids start
with "loadtest-" and --cleanup removes everything the test made. Pass: p95 under 500 ms, under 0.1%
errors, and at least 95% of the asked rate delivered.
"""
import argparse
import base64
import json
import os
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

TYPES = [("motion", "info", None), ("line_crossing", "warning", "human"), ("intrusion", "warning", "human"),
         ("region_entrance", "info", "vehicle"), ("video_loss", "warning", None)]
JPEG = b"\xff\xd8\xff\xe0" + os.urandom(30_000) + b"\xff\xd9"


def post(api, path, token, body):
    data = json.dumps(body).encode()
    req = urllib.request.Request(api + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            return (time.perf_counter() - t) * 1000, r.status
    except urllib.error.HTTPError as e:
        return (time.perf_counter() - t) * 1000, e.code
    except Exception:
        return (time.perf_counter() - t) * 1000, 0


def event(nvr, cam):
    typ, sev, obj = random.choice(TYPES)
    if typ == "intrusion" and random.random() < 0.7:
        sev = "info"
    body = {"camera_id": f"loadtest-n{nvr:02d}-ch{cam:02d}", "source_kind": "nvr", "source_ref": "loadtest", "tier": "N",
            "type": typ, "object_class": obj, "zone": f"Load test zone {cam % 4}", "severity": sev,
            "occurred_at": datetime.now(timezone.utc).isoformat()}
    if random.random() < 0.2:
        body["snapshot_jpeg_b64"] = base64.b64encode(JPEG).decode()
    return body


def health(nvr, cams):
    return {"nvr": f"loadtest-{nvr:02d}", "reachable": True, "name": f"Load test NVR {nvr}", "model": "SIM", "firmware": "0",
            "channels": [{"id": c, "name": f"Cam {c}", "online": True} for c in range(1, cams + 1)],
            "disks": [{"name": "hdd1", "status": "ok", "capacity_gb": 8000}]}


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p / 100 * (len(xs) - 1))))] if xs else 0


def run(a):
    token = os.environ["HSS_WORKER_TOKEN"]
    rate = a.nvrs * a.cameras * a.events_per_cam_min / 60.0
    total_s = a.minutes * 60
    print(f"{a.nvrs} NVRs x {a.cameras} cameras, {rate:.1f} events/s for {a.minutes} min, health every 60 s per NVR")
    lat, codes, lock = {"event": [], "health": []}, {}, threading.Lock()

    def job(kind, path, body):
        ms, code = post(a.api, path, token, body)
        with lock:
            lat[kind].append(ms)
            codes[code] = codes.get(code, 0) + 1

    start = time.monotonic()
    sent = 0
    next_health = start
    last_print = start
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        while (now := time.monotonic()) - start < total_s:
            if now >= next_health:
                for n in range(1, a.nvrs + 1):
                    pool.submit(job, "health", "/devices/health", health(n, a.cameras))
                next_health += 60
            due = int((now - start) * rate)
            while sent < due:
                pool.submit(job, "event", "/events", event(random.randint(1, a.nvrs), random.randint(1, a.cameras)))
                sent += 1
            time.sleep(0.005)
            if now - last_print >= 30:
                last_print = now
                print(f"  {int(now - start)} s: {len(lat['event'])} events answered", flush=True)
    elapsed = time.monotonic() - start
    ev = lat["event"]
    errors = sum(n for c, n in codes.items() if c not in (200, 201, 202))
    done = len(ev) + len(lat["health"])
    result = {"nvrs": a.nvrs, "cameras": a.nvrs * a.cameras, "target_events_per_s": round(rate, 1),
              "achieved_events_per_s": round(len(ev) / elapsed, 1), "events": len(ev), "health_posts": len(lat["health"]),
              "event_ms": {"p50": round(pct(ev, 50)), "p95": round(pct(ev, 95)), "p99": round(pct(ev, 99)), "max": round(max(ev or [0]))},
              "health_ms": {"p50": round(pct(lat["health"], 50)), "p95": round(pct(lat["health"], 95))},
              "errors": errors, "error_rate": round(errors / max(1, done), 5), "status_codes": codes}
    ok = result["event_ms"]["p95"] < 500 and result["error_rate"] < 0.001 and result["achieved_events_per_s"] >= 0.95 * rate
    result["verdict"] = "PASS" if ok else "FAIL"
    print(json.dumps(result, indent=2))
    if a.out:
        try:
            with open(a.out, "w") as f:
                json.dump(result, f, indent=2)
        except OSError as exc:
            print(f"(could not write {a.out}: {exc}; the result is above)")
    return 0 if ok else 1


def cleanup():
    import psycopg
    with psycopg.connect(os.environ["HSS_DATABASE_URL"]) as conn:
        refs = [r for (r,) in conn.execute("SELECT snapshot_ref FROM events WHERE source_ref = 'loadtest' AND snapshot_ref IS NOT NULL")]
        n = conn.execute("DELETE FROM events WHERE source_ref = 'loadtest' OR camera_id LIKE 'loadtest-%%'").rowcount
        h = conn.execute("DELETE FROM device_health WHERE nvr LIKE 'loadtest-%%'").rowcount
    removed = 0
    for ref in refs:
        p = os.path.join(os.environ.get("HSS_DATA_DIR", "/data"), ref)
        if os.path.exists(p):
            os.remove(p)
            removed += 1
    print(f"removed {n} load test events (and their alerts), {removed} snapshots, {h} simulated NVRs")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--api", default="http://api:8000")
    p.add_argument("--nvrs", type=int, default=20)
    p.add_argument("--cameras", type=int, default=32)
    p.add_argument("--events-per-cam-min", type=float, default=2)
    p.add_argument("--minutes", type=float, default=10)
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--out", default="")
    p.add_argument("--cleanup", action="store_true")
    a = p.parse_args()
    raise SystemExit(cleanup() if a.cleanup else run(a))
