"""Command line entry point: hss-probe --host 192.168.1.64 [--host ...]"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
from pathlib import Path

from .collect import collect
from .isapi import IsapiClient
from .report import write_matrix, write_summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Read-only Hikvision NVR capability probe (GET requests only).")
    p.add_argument("--host", action="append", default=[], help="NVR address, repeatable (host or host:port)")
    p.add_argument("--hosts-file", type=Path, help="text file with one NVR address per line")
    p.add_argument("--https", action="store_true", help="use HTTPS instead of HTTP")
    p.add_argument("--insecure", action="store_true", help="accept the NVR's self-signed certificate")
    p.add_argument("--listen-events", type=float, default=0, metavar="SECONDS",
                   help="also listen to the alert stream for this many seconds per NVR")
    p.add_argument("--target-days", type=int, default=30)
    p.add_argument("--bandwidth-limit-mbps", type=float, default=256,
                   help="NVR incoming bandwidth limit (256 for DS-7632NXI-K2/16P)")
    p.add_argument("--out", type=Path, default=Path("probe-output"))
    return p.parse_args(argv)


def credentials() -> tuple[str, str]:
    user = os.environ.get("HSS_NVR_USER") or input("NVR user: ")
    password = os.environ.get("HSS_NVR_PASSWORD") or getpass.getpass("NVR password: ")
    return user, password


def main(argv=None) -> int:
    args = parse_args(argv)
    hosts = list(args.host)
    if args.hosts_file:
        hosts += [ln.strip() for ln in args.hosts_file.read_text().splitlines()
                  if ln.strip() and not ln.startswith("#")]
    if not hosts:
        print("Give at least one --host or a --hosts-file.", file=sys.stderr)
        return 2

    user, password = credentials()
    scheme = "https" if args.https else "http"
    args.out.mkdir(parents=True, exist_ok=True)
    inventories = []
    for host in hosts:
        print(f"Probing {host} ...", flush=True)
        client = IsapiClient(f"{scheme}://{host}", user, password, verify_tls=not args.insecure)
        try:
            inv, raw = collect(client, host, listen_seconds=args.listen_events)
        finally:
            client.close()
        if not inv["device"]["model"]:
            status = inv["endpoint_status"].get("/ISAPI/System/deviceInfo")
            print(f"  could not read device info (HTTP status {status}); check address and credentials",
                  file=sys.stderr)
        raw_dir = args.out / "raw" / re.sub(r"[^A-Za-z0-9._-]", "_", host)
        raw_dir.mkdir(parents=True, exist_ok=True)
        for name, body in raw.items():
            (raw_dir / name).write_text(body, encoding="utf-8")
        inventories.append(inv)
        print(f"  {inv['device']['model'] or '?'} firmware {inv['device']['firmware'] or '?'}: "
              f"{len(inv['channels'])} channels", flush=True)

    (args.out / "inventory.json").write_text(json.dumps(inventories, indent=2), encoding="utf-8")
    write_matrix(inventories, args.out / "compatibility-matrix.csv")
    write_summary(inventories, args.out / "summary.md",
                  target_days=args.target_days, bandwidth_limit_mbps=args.bandwidth_limit_mbps)
    print(f"Wrote {args.out}/inventory.json, compatibility-matrix.csv, summary.md and raw/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
