"""hss-nvrload: how many stream pulls can an NVR serve at once? (task 20)

Opens RTSP pulls through the NVR in steps (for example 8, 16, 24 ... sub-streams), holds each step
for a while and measures what every pull receives. It stops at the first step where the NVR
refuses a pull (for example "453 Not Enough Bandwidth"), drops one, or slows any pull below half
of its own starting rate, then closes everything.

It changes no settings, but it does load the NVR: run it at a quiet time, and expect staff
watching the same NVR in iVMS to see a short stutter if the limit is reached.

Output in --out (default probe-output/nvrload): nvrload.md and nvrload.json.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

from .cli import credentials
from .collect import parse_channels, parse_device, parse_streams
from .isapi import IsapiClient
from .rtsp import PullResult, RtspError, RtspPull

# Published incoming / outgoing bandwidth of the site's NVR models (Mbps), from Hikvision datasheets.
# Used only to put the measurement in context; check the datasheet of your exact model and firmware.
DATASHEET_MBPS = {
    "DS-7632NXI-K2/16P": (256, 256),
    "DS-7616NI-Q2": (160, 160),
    "DS-7732NI-K4/16P": (256, 256),
}


class Puller(threading.Thread):
    def __init__(self, url: str, label: str, user: str, password: str, end: float, stop: threading.Event,
                 timeout: float, factory=RtspPull):
        super().__init__(daemon=True, name=f"pull-{label}")
        self.result = PullResult(url, label)
        self.client = factory(url, user, password, timeout=timeout)
        self.end, self.stop = end, stop
        self.opened = threading.Event()

    @property
    def bytes(self) -> int:
        return self.client.bytes

    def run(self) -> None:
        try:
            self.client.open()
            self.result.opened = True
            self.opened.set()
            self.client.receive_until(self.end, self.stop)
        except RtspError as exc:
            self.result.error, self.result.status = str(exc), exc.status
        except OSError as exc:
            self.result.error = f"connection error: {exc}"
        finally:
            self.opened.set()
            self.client.close()

    @property
    def alive_ok(self) -> bool:
        return self.result.opened and not self.result.error


def plan_urls(host: str, channels: list[int], stream: str, total: int, port: int = 554) -> list[tuple[str, str]]:
    """Pull URLs in order; beyond one pull per channel, channels repeat (as several viewers would)."""
    suffix = "02" if stream == "sub" else "01"
    out = []
    i = 0
    while len(out) < total and channels:
        ch = channels[i % len(channels)]
        copy = i // len(channels) + 1
        out.append((f"rtsp://{host}:{port}/Streaming/Channels/{ch}{suffix}", f"ch{ch:02d}" + (f"#{copy}" if copy > 1 else "")))
        i += 1
    return out


def streaming_sessions(client: IsapiClient) -> int | None:
    r = client.get("/ISAPI/Streaming/status")
    if not r.ok:
        return None
    return len(re.findall(r"<StreamingSessionStatus>", r.text))


def ramp(host: str, user: str, password: str, urls: list[tuple[str, str]], *, step: int, hold: float,
         warmup: float = 3.0, min_ratio: float = 0.5, timeout: float = 10.0, isapi: IsapiClient | None = None,
         factory=RtspPull, log=print) -> dict:
    stop = threading.Event()
    end = time.monotonic() + 24 * 3600          # pulls run until we stop them
    active: list[Puller] = []
    baseline: dict[str, float] = {}             # each pull's kbps in the step it started
    steps = []
    verdict = ""
    try:
        for start in range(0, len(urls), step):
            new = [Puller(u, lbl, user, password, end, stop, timeout, factory) for u, lbl in urls[start:start + step]]
            for p in new:
                p.start()
            for p in new:
                p.opened.wait(timeout + 2)
            active += new
            time.sleep(warmup)
            before = {p.result.label: p.bytes for p in active}
            t0 = time.monotonic()
            time.sleep(hold)
            secs = time.monotonic() - t0
            rates = {p.result.label: (p.bytes - before[p.result.label]) * 8 / 1000 / secs for p in active}
            for p in new:
                if p.alive_ok:
                    baseline[p.result.label] = rates[p.result.label]
            refused = [p for p in new if not p.result.opened]
            dropped = [p for p in active if p.result.opened and p.result.error]
            slow = [p for p in active if p.alive_ok and baseline.get(p.result.label, 0) > 0
                    and rates[p.result.label] < min_ratio * baseline[p.result.label]]
            ok_pulls = [p for p in active if p.alive_ok]
            total_mbps = sum(rates[p.result.label] for p in ok_pulls) / 1000
            worst = min((rates[p.result.label] / baseline[p.result.label] for p in ok_pulls
                         if baseline.get(p.result.label)), default=1.0)
            nvr_sessions = streaming_sessions(isapi) if isapi else None
            row = {
                "pulls_requested": len(active), "pulls_ok": len(ok_pulls), "total_mbps": round(total_mbps, 1),
                "slowest_vs_start_pct": round(100 * worst), "nvr_sessions": nvr_sessions,
                "refused": [f"{p.result.label}: {p.result.error}" for p in refused],
                "dropped": [f"{p.result.label}: {p.result.error}" for p in dropped],
                "slowed": [f"{p.result.label}: {rates[p.result.label]:.0f} of {baseline[p.result.label]:.0f} kbps"
                           for p in slow],
            }
            steps.append(row)
            log(f"  {len(active):3d} pulls: {len(ok_pulls)} ok, {total_mbps:6.1f} Mbps, slowest {row['slowest_vs_start_pct']}% "
                f"of its start" + (f", NVR reports {nvr_sessions} sessions" if nvr_sessions is not None else "")
                + (f"; refused {len(refused)}" if refused else "") + (f"; dropped {len(dropped)}" if dropped else "")
                + (f"; slowed {len(slow)}" if slow else ""))
            if refused or dropped or slow:
                first = (refused or dropped)[0].result.error if (refused or dropped) else row["slowed"][0]
                verdict = f"first trouble at {len(active)} pulls ({first})"
                break
        if not verdict:
            verdict = f"no limit reached: {len(urls)} pulls served (the most this test asked for)"
    finally:
        stop.set()
        for p in active:
            p.join(timeout=5)
    ok_steps = [s for s in steps if not (s["refused"] or s["dropped"] or s["slowed"])]
    best = ok_steps[-1] if ok_steps else None
    return {"host": host, "steps": steps, "verdict": verdict,
            "max_ok_pulls": best["pulls_ok"] if best else 0, "max_ok_mbps": best["total_mbps"] if best else 0.0}


def report(results: list[dict], stream: str) -> str:
    out = ["# NVR connection and bandwidth limits (task 20)", "",
           f"Measured {datetime.now().strftime('%Y-%m-%d %H:%M')} with `hss-nvrload` ({stream}-streams). "
           "Each step adds pulls and holds them; a step fails if the NVR refuses or drops a pull, or a pull "
           "falls below half of its starting rate.", "",
           "| NVR | Model | Online channels | Result | Most pulls without trouble | Their total |",
           "| --- | --- | --- | --- | --- | --- |"]
    for r in results:
        out.append(f"| {r['host']} | {r['model']} | {r['online']} | {r['verdict']} | {r['max_ok_pulls']} | "
                   f"{r['max_ok_mbps']} Mbps |")
    for r in results:
        dmin, dout = DATASHEET_MBPS.get(r["model"], (None, None))
        out += ["", f"## {r['host']} ({r['model']}, firmware {r['firmware']})", ""]
        if dout:
            out.append(f"Datasheet: {dmin} Mbps incoming, {dout} Mbps outgoing. Sessions already open before the "
                       f"test (iVMS, gateway, phones): {r['sessions_before'] if r['sessions_before'] is not None else 'not reported'}.")
            out.append("")
        out += ["| Pulls | OK | Total Mbps | Slowest vs start | NVR sessions | Problems |",
                "| --- | --- | --- | --- | --- | --- |"]
        for s in r["steps"]:
            problems = "; ".join(s["refused"] + s["dropped"] + s["slowed"])[:300] or "none"
            out.append(f"| {s['pulls_requested']} | {s['pulls_ok']} | {s['total_mbps']} | {s['slowest_vs_start_pct']}% | "
                       f"{s['nvr_sessions'] if s['nvr_sessions'] is not None else '-'} | {problems} |")
    out += ["", "## What it means for the platform", "",
            "- The gateway pulls each camera once and shares it with every viewer, so one pull per camera is "
            "the normal load. The NVR must also serve its own iVMS and phone viewers, so keep a margin.",
            "- If an NVR can't serve one sub-stream pull per online camera plus about 25%, pull some cameras "
            "directly from the camera instead of through the NVR (the gateway supports both).",
            "- \"First trouble\" can also be a camera going offline during the test: check the problem column.",
            "- Run again when the 2 or 3 new NVRs arrive.", ""]
    return "\n".join(out)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Measure how many stream pulls an NVR serves at once (task 20).")
    p.add_argument("--host", action="append", default=[], help="NVR address, repeatable")
    p.add_argument("--stream", choices=["sub", "main"], default="sub")
    p.add_argument("--rtsp-port", type=int, default=554, help="NVR RTSP port (default 554)")
    p.add_argument("--step", type=int, default=8, help="pulls added per step (default 8)")
    p.add_argument("--hold", type=float, default=20, help="seconds to measure each step (default 20)")
    p.add_argument("--max-pulls", type=int, default=0,
                   help="stop after this many pulls (default: one per online channel; use e.g. 64 to find the limit)")
    p.add_argument("--min-ratio", type=float, default=0.5, help="a pull below this share of its start rate fails")
    p.add_argument("--yes", action="store_true", help="don't ask for confirmation")
    p.add_argument("--out", type=Path, default=Path("probe-output/nvrload"))
    return p.parse_args(argv)


def main(argv=None, client_class=IsapiClient, factory=RtspPull) -> int:
    args = parse_args(argv)
    if not args.host:
        print("Give at least one --host.", file=sys.stderr)
        return 2
    if not args.yes:
        print("This loads each NVR with many stream pulls for a few minutes. Staff watching the same NVR may "
              "see a short stutter if its limit is reached. No settings are changed.")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            return 1
    user, password = credentials()
    results = []
    for host in args.host:
        isapi = client_class(f"http://{host}", user, password)
        try:
            dev = parse_device(isapi.get("/ISAPI/System/deviceInfo").xml())
            chans = parse_channels(isapi.get("/ISAPI/ContentMgmt/InputProxy/channels").xml(),
                                   isapi.get("/ISAPI/ContentMgmt/InputProxy/channels/status").xml())
            streams = parse_streams(isapi.get("/ISAPI/ContentMgmt/StreamingProxy/channels").xml())
            online = sorted(c for c, ch in chans.items() if ch.get("online"))
            before = streaming_sessions(isapi)
            total = args.max_pulls or len(online)
            print(f"{host}: {dev['model'] or '?'}, {len(online)} channels online; ramping to {total} {args.stream}-stream "
                  f"pulls in steps of {args.step} ({args.hold:.0f} s each)", flush=True)
            res = ramp(host, user, password, plan_urls(host.split(":")[0], online, args.stream, total, args.rtsp_port), step=args.step,
                       hold=args.hold, min_ratio=args.min_ratio, isapi=isapi, factory=factory)
        finally:
            isapi.close()
        configured = sum((streams.get(c, {}).get(args.stream, {}).get("bitrate_kbps") or 0) for c in online) / 1000
        res.update(model=dev["model"], firmware=dev["firmware"], online=len(online), sessions_before=before,
                   configured_mbps_one_each=round(configured, 1))
        print(f"  {res['verdict']}", flush=True)
        results.append(res)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "nvrload.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    (args.out / "nvrload.md").write_text(report(results, args.stream), encoding="utf-8")
    print(f"Wrote {args.out}/nvrload.md and nvrload.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
