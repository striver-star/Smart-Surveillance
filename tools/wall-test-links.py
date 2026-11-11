#!/usr/bin/env python3
"""Build web/wall-test/links.html: one wall-test link per NVR, from gateway/cameras.env.

Cameras the last probe found offline are left out when the probe's compatibility matrix is
given. Usage (from the repository folder):
  python3 tools/wall-test-links.py [--matrix tools/probe/probe-output/compatibility-matrix.csv]
"""
import argparse
import csv
import html
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
p.add_argument("--cameras", type=Path, default=ROOT / "gateway" / "cameras.env")
p.add_argument("--matrix", type=Path, default=ROOT / "tools" / "probe" / "probe-output" / "compatibility-matrix.csv")
p.add_argument("--out", type=Path, default=ROOT / "web" / "wall-test" / "links.html")
p.add_argument("--tiles", type=int, default=32)
p.add_argument("--minutes", type=int, default=60)
args = p.parse_args()

# MTX_PATHS_NVR4-CH01_SOURCE=rtsp://user:pass@10.1.3.4:554/Streaming/Channels/102
paths = defaultdict(list)
for line in args.cameras.read_text().splitlines():
    m = re.match(r"MTX_PATHS_([A-Z0-9_-]+)-CH(\d+)_SOURCE=rtsp://.*@([\d.]+):\d+/", line.strip())
    if m:
        paths[(m.group(1).lower(), m.group(3))].append(int(m.group(2)))

offline = set()
if args.matrix.exists():
    for row in csv.DictReader(args.matrix.open(encoding="utf-8")):
        if row.get("online") == "no":
            offline.add((row["nvr_address"], int(row["channel"])))

links = []
for (name, ip), chans in sorted(paths.items()):
    live = [c for c in sorted(set(chans)) if (ip, c) not in offline]
    if not live:
        continue
    plist = ",".join(f"{name}-ch{c:02d}" for c in live)
    url = f"/wall-test/?n={args.tiles}&minutes={args.minutes}&label=TV-{name.upper()}&paths={plist}"
    links.append((f"{name.upper()} ({ip}): {args.tiles} tiles from {len(live)} cameras", url))
if not links:
    raise SystemExit(f"No cameras found in {args.cameras}; run tools/nvr-paths.sh first.")
quick = links[0][1].split("&paths=")[1].split(",")[:4]
links.insert(0, ("Quick check: 4 tiles", f"/wall-test/?n=4&minutes=10&label=quick&paths={','.join(quick)}"))

args.out.write_text(
    "<!doctype html><meta charset=\"utf-8\"><title>Wall test links</title>\n"
    "<style>body{font:18px Arial,sans-serif;background:#111;color:#eee;padding:30px}"
    "a{color:#F2A900;display:block;margin:16px 0}</style>\n<h2>Wall capacity test</h2>\n"
    + "\n".join(f'<a href="{html.escape(u)}">{html.escape(t)}</a>' for t, u in links) + "\n",
    encoding="utf-8")
print(f"Wrote {args.out} with {len(links)} links:")
for t, _ in links:
    print(" -", t)
