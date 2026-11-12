"""hss-cameras: ask every camera behind the NVRs what it is (task 13). Read-only, GET requests only.

The NVR's own capability answers can't tell camera classes apart (NVR4 reports its own AI for
every channel). This tool asks each camera directly:

  - model, firmware, serial and clock (deviceInfo, time)
  - smart events and AcuSense human/vehicle filtering (Event, Smart, FieldDetection capabilities)
  - supplement light, to spot ColorVu and hybrid-light models (Image capabilities)

How it reaches a camera:
  1. directly at the IP the NVR uses for it, when that IP is reachable from the server
     (cameras on the site LAN, such as NVR4's 10.1.3.x cameras);
  2. for PoE cameras on the NVR's internal 192.168.254.x network, through the NVR's
     "virtual host" ports (NVR web UI: Network > Advanced > enable Virtual Host), which
     forward NVR_IP:65001 and up to the cameras' web servers. The camera answering on each
     port is matched to its channel by its IP address.

It also checks, per channel, whether the NVR lets us read the camera's intrusion and line
crossing settings (/ISAPI/Smart/FieldDetection/<ch>), which is what the platform will need to
send zones to cameras through the NVR later.

Output in --out (default probe-output/cameras): cameras.json, cameras.csv, cameras-summary.md
and raw/ with every response.
"""
from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .classify import SMART_EVENTS
from .cli import credentials
from .collect import parse_channels, parse_device, parse_event_types, parse_supported_flags, parse_time
from .isapi import IsapiClient

CAMERA_ENDPOINTS = {
    "device_info": "/ISAPI/System/deviceInfo",
    "time": "/ISAPI/System/time",
    "network": "/ISAPI/System/Network/interfaces",
    "event_caps": "/ISAPI/Event/capabilities",
    "smart_caps": "/ISAPI/Smart/capabilities",
    "field_caps": "/ISAPI/Smart/FieldDetection/1/capabilities",
    "image_caps": "/ISAPI/Image/channels/1/capabilities",
    "supplement_light": "/ISAPI/Image/channels/1/supplementLight",
}
# Per channel, asked of the NVR: can the platform read (and later write) the camera's rules here?
NVR_RULE_ENDPOINTS = {
    "field_detection": "/ISAPI/Smart/FieldDetection/{ch}",
    "line_detection": "/ISAPI/Smart/LineDetection/{ch}",
    "motion_detection": "/ISAPI/System/Video/inputs/channels/{ch}/motionDetection",
}
VIRTUAL_HOST_BASE = 65000
POE_NET = ipaddress.ip_network("192.168.254.0/24")

ClientFactory = Callable[[str], IsapiClient]


# ---------------------------------------------------------------------------- classification

def model_hints(model: str) -> dict[str, str]:
    """What a Hikvision model code suggests. Weak evidence: capabilities override it."""
    m = model.upper()
    hints = {}
    if m.startswith(("IDS-2CD7", "IDS-2CD8", "IDS-2CD6")):
        hints["deepinview"] = f"model {model} is a DeepinView series"
    suffix = re.search(r"G(\d)[A-Z]?-([A-Z/()]+)", m)
    if suffix:
        gen, opts = int(suffix.group(1)), suffix.group(2)
        if opts.startswith("LI"):
            hints["hybrid_light"] = f"model suffix -{opts}: smart hybrid light (IR, white light on events)"
        elif opts.startswith("L"):
            hints["colorvu"] = f"model suffix -{opts}: ColorVu (white light, colour at night)"
        if gen >= 2 and ("I" in opts.split("/")[0] or opts.startswith("LI")):
            hints["acusense"] = f"G{gen} model with -{opts}: AcuSense generation"
    return hints


# Camera capability flags (isSupportXxx = true in Event/Smart capabilities) -> event names.
FLAG_EVENTS = {
    "linedetection": "linedetection", "fielddetection": "fielddetection", "intrusiondetection": "fielddetection",
    "regionentrance": "regionentrance", "regionexiting": "regionexiting", "loitering": "loitering",
    "group": "group", "peoplegathering": "group", "rapidmove": "rapidmove", "fastmoving": "rapidmove",
    "parking": "parking", "unattendedbaggage": "unattendedbaggage", "attendedbaggage": "attendedbaggage",
    "objectremoval": "attendedbaggage", "facedetect": "facedetection", "facedetection": "facedetection",
    "facesnap": "facesnap", "facecapture": "facesnap", "vehicledetection": "vehicledetection",
    "humanrecognition": "humanrecognition", "motiondetection": "vmd", "vmd": "vmd",
    "tamperdetection": "tamperdetection", "shelteralarm": "shelteralarm", "videotampering": "tamperdetection",
    "audioexception": "audioexception", "scenechangedetection": "scenechangedetection",
}


def events_from_flags(flags: list[str]) -> set[str]:
    """isSupportLineDetection -> linedetection, and so on (cameras report flags, not event lists)."""
    out = set()
    for f in flags:
        name = re.sub(r"^(isSupport|isSupported|support)", "", f, flags=re.I).lower()
        if name in FLAG_EVENTS:
            out.add(FLAG_EVENTS[name])
    return out


def camera_class(cam: dict) -> tuple[str, list[str]]:
    """Return (class, evidence).

    Light type (ColorVu, Smart Hybrid Light) comes from the model code: cameras without white light
    still list it in their image capabilities, so those can't be trusted. AcuSense comes from the
    camera offering human/vehicle target filtering in its smart rules, or a G2+ -I model with smart events.
    """
    evidence: list[str] = []
    model = cam.get("model", "")
    hints = model_hints(model)
    caps_text = cam.get("_caps_text", "").lower()
    events = set(cam.get("event_types", []))
    smart = events & SMART_EVENTS

    target_filter = bool(re.search(r"detectiontarget|targettype|humanvehicle|human_vehicle|"
                                   r"issupporttargetdetection", caps_text))
    acusense = target_filter or ("acusense" in hints and bool(smart))
    if target_filter:
        evidence.append("smart rules offer human/vehicle target filtering (AcuSense)")
    elif "acusense" in hints and smart:
        evidence.append(hints["acusense"])
    colorvu, hybrid = "colorvu" in hints, "hybrid_light" in hints
    if colorvu:
        evidence.append(hints["colorvu"])
    if hybrid:
        evidence.append(hints["hybrid_light"])
    if smart:
        evidence.append(f"smart events: {', '.join(sorted(smart))}")

    if "deepinview" in hints:
        return "DeepinView", [hints["deepinview"]] + evidence
    light = "ColorVu" if colorvu else "Hybrid light" if hybrid else ""
    if acusense:
        return (f"{light} + AcuSense" if light else "AcuSense"), evidence
    if smart:
        return (f"{light} + Smart" if light else "Smart (VCA, no human/vehicle filter)"), evidence
    if light:
        return f"{light} (no AI)", evidence + ([f"events: {', '.join(sorted(events))}"] if events else [])
    if events:
        return "Basic (no AI)", evidence + [f"events: {', '.join(sorted(events))}"]
    return "unknown", evidence + ["camera gave no event capabilities"]


def ai_source(cam: dict | None, nvr_channel_events: list[str]) -> tuple[str, str]:
    """Where the smart events for this channel come from: camera (E), NVR (N) or our server (S)."""
    if cam and set(cam.get("event_types", [])) & SMART_EVENTS:
        return "E", "camera runs its own AI"
    nvr_smart = set(nvr_channel_events) & SMART_EVENTS
    if cam and nvr_smart:
        return "N", "camera has no AI; NVR AI available for a limited number of channels"
    if cam:
        return "S", "no device AI: server AI needed"
    return "?", "camera not reachable: tier unconfirmed"


def clock_drift_seconds(local_time: str, now: datetime | None = None) -> int | None:
    try:
        t = datetime.fromisoformat(local_time.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        return None
    return int((t - (now or datetime.now(timezone.utc))).total_seconds())


# ---------------------------------------------------------------------------- collection

def read_camera(client: IsapiClient) -> tuple[dict | None, dict[str, str]]:
    raw: dict[str, str] = {}
    roots = {}
    for key, path in CAMERA_ENDPOINTS.items():
        r = client.get(path)
        raw[f"{key}.xml"] = r.text if r.status else f"(no answer) {r.text}"
        roots[key] = r.xml()
        if key == "device_info" and roots[key] is None:
            raw["_reason"] = ("wrong user or password (HTTP 401)" if r.status == 401 else
                              "refused (HTTP 403): user lacks rights or ISAPI is off" if r.status == 403 else
                              "no answer: camera not reachable from the server" if r.status == 0 else
                              f"HTTP {r.status}")
            return None, raw     # not reachable, wrong password or not a camera: stop here
    dev = parse_device(roots["device_info"])
    tm = parse_time(roots["time"])
    ips = sorted({el.text.strip() for el in (roots["network"].iter("ipAddress") if roots["network"] is not None else [])
                  if el.text and el.text.strip()})
    cam = {
        "model": dev["model"], "firmware": dev["firmware"], "firmware_date": dev["firmware_date"],
        "serial": dev["serial"], "mac": dev["mac"], "device_name": dev["name"],
        "ip_addresses": ips,
        "time_mode": tm["mode"], "local_time": tm["local_time"],
        "clock_drift_s": clock_drift_seconds(tm["local_time"]),
        "smart_flags": parse_supported_flags(roots["smart_caps"]),
        "event_types": sorted(set(parse_event_types(roots["event_caps"]))
                              | events_from_flags(parse_supported_flags(roots["event_caps"])
                                                  + parse_supported_flags(roots["smart_caps"]))),
        "_caps_text": " ".join(raw.get(k, "") for k in ("smart_caps.xml", "field_caps.xml", "event_caps.xml")),
        "_light_text": " ".join(raw.get(k, "") for k in ("image_caps.xml", "supplement_light.xml")),
    }
    cam["class"], cam["class_evidence"] = camera_class(cam)
    return cam, raw


def reachable_directly(ip: str) -> bool:
    try:
        return bool(ip) and ipaddress.ip_address(ip) not in POE_NET
    except ValueError:
        return True   # a host name


def survey_nvr(nvr: str, nvr_client: IsapiClient, client_for: ClientFactory, *,
               scheme: str = "http", virtual_host: bool = True, workers: int = 8) -> tuple[dict, dict[str, str]]:
    raw: dict[str, str] = {}
    dev_r = nvr_client.get("/ISAPI/System/deviceInfo")
    ch_r = nvr_client.get("/ISAPI/ContentMgmt/InputProxy/channels")
    st_r = nvr_client.get("/ISAPI/ContentMgmt/InputProxy/channels/status")
    raw.update({"nvr_device_info.xml": dev_r.text, "nvr_channels.xml": ch_r.text, "nvr_channel_status.xml": st_r.text})
    nvr_dev = parse_device(dev_r.xml())
    channels = parse_channels(ch_r.xml(), st_r.xml())

    def nvr_side(cid: int) -> dict:
        out = {"nvr_event_types": parse_event_types(
            nvr_client.get(f"/ISAPI/Event/channels/{cid}/capabilities").xml())}
        for key, tmpl in NVR_RULE_ENDPOINTS.items():
            r = nvr_client.get(tmpl.format(ch=cid))
            out[f"nvr_reads_{key}"] = r.status
            raw[f"ch{cid:02d}_nvr_{key}.xml"] = r.text
        return out

    def direct(cid: int) -> tuple[int, dict | None, dict[str, str], str]:
        ch = channels[cid]
        if not ch.get("online") or not reachable_directly(ch["camera_ip"]):
            return cid, None, {}, ""
        c = client_for(f"{scheme}://{ch['camera_ip']}")
        try:
            cam, r = read_camera(c)
        finally:
            c.close()
        return cid, cam, r, "direct" if cam else ""

    results: dict[int, dict] = {cid: {"via": "", "camera": None, "why": ""} for cid in channels}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for cid, extra in zip(channels, pool.map(nvr_side, list(channels))):
            results[cid].update(extra)
        for cid, cam, r, via in pool.map(direct, list(channels)):
            results[cid].update(camera=cam, via=via, why=r.pop("_reason", ""))
            raw.update({f"ch{cid:02d}_{k}": v for k, v in r.items()})

    # PoE cameras: try the NVR's virtual host ports and match each answer to a channel by IP.
    host = nvr.split(":")[0]
    missing = [cid for cid in channels if results[cid]["camera"] is None and channels[cid].get("online")
               and not reachable_directly(channels[cid]["camera_ip"])]
    vh_status = "not needed"
    if missing and virtual_host:
        by_ip = {channels[cid]["camera_ip"]: cid for cid in missing}
        ports = [VIRTUAL_HOST_BASE + n for n in range(1, max(channels) + 1)]

        def via_port(port: int):
            c = client_for(f"http://{host}:{port}")
            try:
                return port, *read_camera(c)
            finally:
                c.close()
        answered, refused = 0, 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for port, cam, r in pool.map(via_port, ports):
                if cam is None:
                    refused += r.get("_reason", "").startswith(("wrong user", "refused"))
                    continue
                answered += 1
                cid = next((by_ip[ip] for ip in cam["ip_addresses"] if ip in by_ip), None)
                if cid is None:
                    raw[f"port{port}_unmatched_device_info.xml"] = r.get("device_info.xml", "")
                    continue
                results[cid].update(camera=cam, via=f"virtual host :{port}")
                raw.update({f"ch{cid:02d}_{k}": v for k, v in r.items()})
        vh_status = (f"{answered} camera(s) answered on ports {ports[0]}-{ports[-1]}" if answered else
                     "no answer on the virtual host ports: enable Virtual Host on the NVR "
                     "(Network > Advanced) to reach its PoE cameras")
        if refused:
            vh_status += f"; {refused} port(s) refused the password (PoE cameras may use another password)"
        for cid in missing:
            if results[cid]["camera"] is None:
                results[cid]["why"] = ("PoE camera behind the NVR: " +
                                       ("its virtual host port refused the password" if refused else
                                        "no camera answered on the virtual host ports"))

    rows = []
    for cid in sorted(channels):
        ch, res = channels[cid], results[cid]
        cam = res["camera"]
        tier, tier_reason = ai_source(cam, res.get("nvr_event_types", []))
        if not cam and res["why"] and ch.get("online"):
            tier_reason = f"not reached: {res['why']}"
        row = {
            "nvr": nvr, "nvr_model": nvr_dev["model"], "channel": cid, "name": ch["name"],
            "camera_ip": ch["camera_ip"], "online": ch.get("online"), "reached_via": res["via"] or "not reached",
            "model": cam["model"] if cam else "", "firmware": cam["firmware"] if cam else "",
            "firmware_date": cam["firmware_date"] if cam else "", "serial": cam["serial"] if cam else "",
            "class": cam["class"] if cam else ("offline" if ch.get("online") is False else "not reached"),
            "class_evidence": "; ".join(cam["class_evidence"]) if cam else "",
            "tier": tier, "tier_reason": tier_reason,
            "camera_event_types": " ".join(cam["event_types"]) if cam else "",
            "nvr_event_types": " ".join(res.get("nvr_event_types", [])),
            "time_mode": cam["time_mode"] if cam else "", "clock_drift_s": cam["clock_drift_s"] if cam else None,
            "nvr_reads_field_detection": res.get("nvr_reads_field_detection"),
            "nvr_reads_line_detection": res.get("nvr_reads_line_detection"),
            "nvr_reads_motion_detection": res.get("nvr_reads_motion_detection"),
        }
        rows.append(row)
    return {"nvr": nvr, "nvr_device": nvr_dev, "virtual_host": vh_status, "cameras": rows}, raw


# ---------------------------------------------------------------------------- report

CSV_FIELDS = ["nvr", "nvr_model", "channel", "name", "camera_ip", "online", "reached_via", "model", "firmware",
              "firmware_date", "class", "tier", "tier_reason", "class_evidence", "time_mode", "clock_drift_s",
              "nvr_reads_field_detection", "nvr_reads_line_detection", "nvr_reads_motion_detection",
              "camera_event_types", "nvr_event_types", "serial"]


def pick_walk_test(rows: list[dict]) -> dict[str, dict]:
    """One online camera per class for the event walk test, preferring named ones."""
    picks: dict[str, dict] = {}
    for want, match in (("ColorVu", lambda c: c.startswith("ColorVu")), ("AcuSense", lambda c: "AcuSense" in c),
                        ("Non-AI", lambda c: c.startswith("Basic"))):
        cands = [r for r in rows if r["online"] and match(r["class"])]
        used = {id(p) for p in picks.values()}
        cands.sort(key=lambda r: (id(r) in used, bool(re.match(r"(?i)camera ?\d+$", r["name"] or "")),
                                  r["nvr"], r["channel"]))
        if cands:
            picks[want] = cands[0]
    return picks


def summary(surveys: list[dict]) -> str:
    rows = [r for s in surveys for r in s["cameras"]]
    reached = [r for r in rows if r["model"]]
    out = ["# Camera classes and firmware (task 13)", "",
           f"Surveyed {datetime.now().strftime('%Y-%m-%d %H:%M')} with `hss-cameras` (read-only). "
           f"{len(rows)} channels on {len(surveys)} NVR(s); {len(reached)} cameras answered "
           "(directly or through the NVR's virtual host).", ""]
    out += ["## How each NVR's cameras were reached", "", "| NVR | Model | Reached | Virtual host |", "| --- | --- | --- | --- |"]
    for s in surveys:
        n = sum(1 for r in s["cameras"] if r["model"])
        out.append(f"| {s['nvr']} | {s['nvr_device']['model']} | {n} of {len(s['cameras'])} | {s['virtual_host']} |")
    out += ["", "## Camera classes", "", "| Class | Cameras | Tier E (own AI) | Tier N | Tier S |", "| --- | --- | --- | --- | --- |"]
    by_class: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_class[r["class"]].append(r)
    for cls, rs in sorted(by_class.items(), key=lambda x: -len(x[1])):
        t = Counter(r["tier"] for r in rs)
        out.append(f"| {cls} | {len(rs)} | {t.get('E', 0)} | {t.get('N', 0)} | {t.get('S', 0)} |")
    out += ["", "## Models and firmware versions", "",
            "Two or more firmware versions of one model are worth testing separately (task 13).", "",
            "| Model | Firmware (cameras) |", "| --- | --- |"]
    fw: dict[str, Counter] = defaultdict(Counter)
    for r in reached:
        fw[r["model"]][f"{r['firmware']} {r['firmware_date']}".strip()] += 1
    for model, c in sorted(fw.items()):
        out.append(f"| {model} | " + ", ".join(f"{v} ({n})" for v, n in c.most_common()) + " |")
    picks = pick_walk_test(rows)
    out += ["", "## Suggested walk test (one camera per class)", "",
            "Walk through each camera's view while `hss-probe --host <NVR> --listen-events 300` runs, and "
            "check the event arrives through the NVR with the right channel.", ""]
    for want in ("ColorVu", "AcuSense", "Non-AI"):
        r = picks.get(want)
        out.append(f"- **{want}:** " + (f"{r['name']} (NVR {r['nvr']} ch {r['channel']}, {r['model']})" if r
                                         else "none found among reachable cameras"))
    readable = [r for r in rows if r["online"] and r["nvr_reads_field_detection"] == 200]
    out += ["", "## Can the platform send zones through the NVR?", "",
            f"The NVR returned the intrusion (field detection) settings for {len(readable)} of "
            f"{sum(1 for r in rows if r['online'])} online channels. Those channels can take zones from the "
            "platform through the NVR; the others need zones drawn in the platform (Tier S) or set on the "
            "camera directly.", ""]
    drift = [r for r in reached if r["clock_drift_s"] is not None and abs(r["clock_drift_s"]) > 30]
    manual = [r for r in reached if r["time_mode"] and r["time_mode"].upper() != "NTP"]
    out += ["## Camera clocks", "",
            f"{len(drift)} cameras are more than 30 seconds off the server clock; {len(manual)} are not set to NTP.",
            "Event times come from the cameras, so set every camera and NVR to NTP (the server can be the NTP source).", ""]
    if drift:
        out += ["| Camera | NVR ch | Off by (s) | Mode |", "| --- | --- | --- | --- |"]
        for r in sorted(drift, key=lambda r: -abs(r["clock_drift_s"]))[:40]:
            out.append(f"| {r['name']} | {r['nvr']} ch {r['channel']} | {r['clock_drift_s']} | {r['time_mode']} |")
        out.append("")
    unreached = [r for r in rows if r["online"] and not r["model"]]
    if unreached:
        out += ["## Online but not reached", "",
                "Usually a different camera password, a firewall, or PoE cameras without Virtual Host. "
                "Their tier stays as the NVR probe guessed.", ""]
        why = Counter(r["tier_reason"].removeprefix("not reached: ") for r in unreached)
        out += ["| Reason | Cameras |", "| --- | --- |"] + [f"| {k} | {n} |" for k, n in why.most_common()] + [""]
        out += [f"- {r['name'] or '(unnamed)'}: NVR {r['nvr']} ch {r['channel']}, {r['camera_ip']}: "
                f"{r['tier_reason'].removeprefix('not reached: ')}" for r in unreached]
        out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------- CLI

def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Ask every camera behind the NVRs what it is (read-only).")
    p.add_argument("--host", action="append", default=[], help="NVR address, repeatable")
    p.add_argument("--https", action="store_true", help="use HTTPS to the NVRs and LAN cameras")
    p.add_argument("--insecure", action="store_true", help="accept self-signed certificates")
    p.add_argument("--no-virtual-host", action="store_true", help="don't try the NVR virtual host ports")
    p.add_argument("--camera-user", help="camera user if different from the NVR's (env HSS_CAMERA_USER)")
    p.add_argument("--timeout", type=float, default=5.0)
    p.add_argument("--out", type=Path, default=Path("probe-output/cameras"))
    return p.parse_args(argv)


def main(argv=None, client_class=IsapiClient) -> int:
    import getpass
    import os
    args = parse_args(argv)
    if not args.host:
        print("Give at least one --host.", file=sys.stderr)
        return 2
    user, password = credentials()
    cam_user = args.camera_user or os.environ.get("HSS_CAMERA_USER") or user
    cam_pass = os.environ.get("HSS_CAMERA_PASSWORD") or (
        getpass.getpass("Camera password (Enter = same as NVR): ") if args.camera_user else "") or password
    scheme = "https" if args.https else "http"

    def client_for(base: str) -> IsapiClient:
        return client_class(base, cam_user, cam_pass, verify_tls=not args.insecure, timeout=args.timeout)

    surveys = []
    raw_root = args.out / "raw"
    for nvr in args.host:
        print(f"Surveying cameras on {nvr} ...", flush=True)
        nvr_client = client_class(f"{scheme}://{nvr}", user, password, verify_tls=not args.insecure,
                                  timeout=max(args.timeout, 10))
        try:
            survey, raw = survey_nvr(nvr, nvr_client, client_for, scheme=scheme,
                                     virtual_host=not args.no_virtual_host)
        finally:
            nvr_client.close()
        d = raw_root / re.sub(r"[^A-Za-z0-9._-]", "_", nvr)
        d.mkdir(parents=True, exist_ok=True)
        for name, body in raw.items():
            (d / name).write_text(body, encoding="utf-8")
        reached = sum(1 for r in survey["cameras"] if r["model"])
        print(f"  {survey['nvr_device']['model'] or '?'}: {reached} of {len(survey['cameras'])} cameras answered; "
              f"virtual host: {survey['virtual_host']}", flush=True)
        surveys.append(survey)

    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "cameras.json").write_text(json.dumps(surveys, indent=2), encoding="utf-8")
    with (args.out / "cameras.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        for s in surveys:
            w.writerows(s["cameras"])
    (args.out / "cameras-summary.md").write_text(summary(surveys), encoding="utf-8")
    print(f"Wrote {args.out}/cameras-summary.md, cameras.csv, cameras.json and raw/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
