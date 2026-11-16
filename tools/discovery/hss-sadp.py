#!/usr/bin/env python3
"""List Hikvision devices on this network segment with SADP, Hikvision's discovery protocol (read only).

Run it on the HSS server itself (not in Docker), or on a laptop plugged into the camera network:

    python3 tools/discovery/hss-sadp.py            # table
    python3 tools/discovery/hss-sadp.py --json     # for scripts
    python3 tools/discovery/hss-sadp.py --seconds 6 --interface 10.1.3.20

It sends one multicast probe (239.255.255.250, UDP 37020) and lists the answers: model, serial, address, MAC,
firmware, ports, channels and whether the device is activated. It finds devices even on default or unknown
addresses (for example 192.0.0.64), which an address scan can't. It never changes or activates anything:
activate new devices with a strong password in Hikvision SADP or on their web page, then add them in the
console (Devices › Find devices, or Add NVR).

Multicast doesn't cross routers: run it on each camera VLAN.
"""
from __future__ import annotations

import argparse
import json
import socket
import struct
import sys
import time
import uuid
import xml.etree.ElementTree as ET

GROUP, PORT = "239.255.255.250", 37020
FIELDS = {"DeviceDescription": "model", "DeviceSN": "serial", "IPv4Address": "ip", "IPv4SubnetMask": "mask", "IPv4Gateway": "gateway",
          "MAC": "mac", "SoftwareVersion": "firmware", "HttpPort": "http_port", "CommandPort": "sdk_port", "DHCP": "dhcp",
          "Activated": "activated", "DigitalChannelNum": "ip_channels", "AnalogChannelNum": "analog_channels", "DeviceType": "type"}


def probe_xml(probe_id: str) -> bytes:
    return (f'<?xml version="1.0" encoding="utf-8"?><Probe><Uuid>{probe_id}</Uuid><Types>inquiry</Types></Probe>').encode()


def parse_reply(data: bytes) -> dict | None:
    """One ProbeMatch answer -> a device dict (pure, tested)."""
    try:
        root = ET.fromstring(data.decode("utf-8", "replace").strip())
    except ET.ParseError:
        return None
    if root.tag.split("}")[-1] != "ProbeMatch":
        return None
    out = {}
    for el in root:
        key = FIELDS.get(el.tag.split("}")[-1])
        if key:
            out[key] = (el.text or "").strip()
    if "ip" not in out:
        return None
    out["activated"] = out.get("activated", "").lower() == "true" if "activated" in out else None
    model = out.get("model", "")
    out["kind"] = "nvr" if model.upper().startswith(("DS-7", "DS-8", "DS-9", "IDS-7", "IDS-9")) or int(out.get("ip_channels") or 0) > 1 else \
        "camera" if model.upper().startswith(("DS-2", "IDS-2")) else "device"
    return out


def discover(seconds: float, interface: str | None) -> list[dict]:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", PORT))
    mreq = struct.pack("4s4s", socket.inet_aton(GROUP), socket.inet_aton(interface or "0.0.0.0"))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
    if interface:
        s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(interface))
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 1)
    probe_id = str(uuid.uuid4()).upper()
    s.sendto(probe_xml(probe_id), (GROUP, PORT))
    found: dict[str, dict] = {}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        s.settimeout(max(0.05, end - time.monotonic()))
        try:
            data, _addr = s.recvfrom(65535)
        except socket.timeout:
            break
        d = parse_reply(data)
        if d:
            found[d.get("mac") or d["ip"]] = d
    s.close()
    return sorted(found.values(), key=lambda d: tuple(int(x) for x in d["ip"].split(".") if x.isdigit()))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--seconds", type=float, default=4.0)
    p.add_argument("--interface", help="this computer's address on the camera network, if it has several")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    try:
        devices = discover(a.seconds, a.interface)
    except OSError as exc:
        print(f"Can't use multicast here ({exc}). Run on the server itself, not inside Docker.", file=sys.stderr)
        return 2
    if a.json:
        print(json.dumps(devices, indent=2))
        return 0
    if not devices:
        print("No Hikvision devices answered. Multicast doesn't cross routers: run this on the camera network's VLAN.")
        return 1
    print(f"{'Address':16} {'Kind':7} {'Model':22} {'Serial':28} {'Firmware':16} {'Ch':>3} {'Activated':9} MAC")
    for d in devices:
        print(f"{d['ip']:16} {d['kind']:7} {d.get('model', '')[:22]:22} {d.get('serial', '')[-28:]:28} {d.get('firmware', '')[:16]:16} "
              f"{d.get('ip_channels', '') or '':>3} {'yes' if d['activated'] else 'NO' if d['activated'] is False else '?':9} {d.get('mac', '')}")
    n = sum(1 for d in devices if d["activated"] is False)
    if n:
        print(f"\n{n} device(s) not activated: activate them with a strong password before adding them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
