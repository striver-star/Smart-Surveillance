"""hss-streams: change camera stream codecs on many Hikvision NVRs at once.

Default is a dry run that only shows what would change. With --apply it backs up each stream's
settings, changes only the codec, checks the result, and writes a report. --restore puts saved
settings back. Example:

  hss-streams --host 10.1.3.4 --host 10.1.3.5 --sub-h264            # preview
  hss-streams --host 10.1.3.4 --host 10.1.3.5 --sub-h264 --apply    # change
  hss-streams --restore stream-backups/20261111-120000 --apply      # undo
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .cli import credentials
from .isapi import IsapiClient

VIDEO_BLOCK = re.compile(r"<Video\b.*?</Video>", re.S)
CODEC = re.compile(r"(<videoCodecType>)([^<]*)(</videoCodecType>)")
STATUS_OK, STATUS_REBOOT = "1", "7"


@dataclass
class Change:
    host: str
    stream_id: int
    channel: int
    kind: str              # sub or main
    name: str
    current: str
    target: str
    action: str = ""       # change, skip
    reason: str = ""
    result: str = ""
    original_xml: str = field(default="", repr=False)


def parse_channels(range_text: str | None) -> set[int] | None:
    """'1-8,12' -> {1..8, 12}; None means all channels."""
    if not range_text:
        return None
    chans: set[int] = set()
    for part in range_text.split(","):
        part = part.strip()
        if "-" in part:
            a, b = part.split("-", 1)
            chans.update(range(int(a), int(b) + 1))
        elif part:
            chans.add(int(part))
    return chans


def current_codec(xml: str) -> str:
    block = VIDEO_BLOCK.search(xml)
    m = CODEC.search(block.group(0)) if block else None
    return m.group(2).strip() if m else ""


def with_codec(xml: str, codec: str) -> str:
    """Change only the codec inside <Video>, keeping every other setting and the XML namespace."""
    block = VIDEO_BLOCK.search(xml)
    if not block:
        raise ValueError("no <Video> section in the stream settings")
    new_block, n = CODEC.subn(lambda m: m.group(1) + codec + m.group(3), block.group(0), count=1)
    if n != 1:
        raise ValueError("no videoCodecType in the stream settings")
    return xml[:block.start()] + new_block + xml[block.end():]


def supported_codecs(client: IsapiClient, stream_id: int) -> list[str] | None:
    """Codecs the camera accepts for this stream, or None when the NVR does not say."""
    r = client.get(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{stream_id}/capabilities")
    if not r.ok:
        return None
    m = re.search(r"<videoCodecType\b[^>]*\bopt=\"([^\"]*)\"", r.text)
    return [c.strip() for c in m.group(1).split(",")] if m else None


def response_status(text: str) -> tuple[str, str]:
    code = re.search(r"<statusCode>(\d+)</statusCode>", text)
    sub = re.search(r"<subStatusCode>([^<]+)</subStatusCode>", text)
    return (code.group(1) if code else ""), (sub.group(1) if sub else "")


def plan_host(client: IsapiClient, host: str, *, sub_codec: str | None, main_codec: str | None,
              channels: set[int] | None) -> list[Change]:
    status = client.get("/ISAPI/ContentMgmt/InputProxy/channels/status")
    online = {int(i): o == "true" for i, o in re.findall(
        r"<InputProxyChannelStatus\b.*?<id>(\d+)</id>.*?<online>(\w+)</online>", status.text, re.S)}
    names = dict((int(i), n) for i, n in re.findall(
        r"<InputProxyChannel\b.*?<id>(\d+)</id>\s*<name>([^<]*)</name>",
        client.get("/ISAPI/ContentMgmt/InputProxy/channels").text, re.S))
    listing = client.get("/ISAPI/ContentMgmt/StreamingProxy/channels")
    if not listing.ok:
        raise RuntimeError(f"cannot read stream list (HTTP status {listing.status})")
    stream_ids = sorted({int(i) for i in re.findall(r"<StreamingChannel\b.*?<id>(\d+)</id>", listing.text, re.S)})

    plan: list[Change] = []
    for sid in stream_ids:
        ch, no = divmod(sid, 100)
        kind = {1: "main", 2: "sub"}.get(no)
        target = {"sub": sub_codec, "main": main_codec}.get(kind)
        if not target or (channels is not None and ch not in channels):
            continue
        r = client.get(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{sid}")
        cur = current_codec(r.text) if r.ok else ""
        c = Change(host, sid, ch, kind, names.get(ch, ""), cur, target, original_xml=r.text if r.ok else "")
        if online.get(ch) is False:
            c.action, c.reason = "skip", "camera offline"
        elif not r.ok:
            c.action, c.reason = "skip", f"cannot read settings (HTTP {r.status})"
        elif cur.upper() == target.upper():
            c.action, c.reason = "skip", f"already {target}"
        else:
            opts = supported_codecs(client, sid)
            if opts is not None and not any(o.upper() == target.upper() for o in opts):
                c.action, c.reason = "skip", f"camera does not offer {target} (offers {', '.join(opts)})"
            else:
                c.action = "change"
        plan.append(c)
    return plan


def apply_change(client: IsapiClient, c: Change, backup_dir: Path) -> None:
    host_dir = backup_dir / re.sub(r"[^A-Za-z0-9._-]", "_", c.host)
    host_dir.mkdir(parents=True, exist_ok=True)
    (host_dir / f"{c.stream_id}.xml").write_text(c.original_xml, encoding="utf-8")
    r = client.put(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{c.stream_id}", with_codec(c.original_xml, c.target))
    code, sub = response_status(r.text)
    if r.status != 200 or code not in (STATUS_OK, STATUS_REBOOT):
        c.result = f"refused: HTTP {r.status} {sub or code}".strip()
        return
    check = client.get(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{c.stream_id}")
    now = current_codec(check.text) if check.ok else "?"
    if now.upper() == c.target.upper():
        c.result = "changed" + (" (camera asks for a reboot)" if code == STATUS_REBOOT else "")
    else:
        c.result = f"not confirmed: camera reports {now}"


def restore(backup_dir: Path, user: str, password: str, *, apply: bool, scheme: str, verify_tls: bool) -> int:
    files = sorted(backup_dir.glob("*/*.xml"))
    if not files:
        print(f"No backups found in {backup_dir}", file=sys.stderr)
        return 2
    failed = 0
    for f in files:
        host, sid = f.parent.name, int(f.stem)
        print(f"{host} stream {sid}: restore {current_codec(f.read_text())}", end="")
        if not apply:
            print(" (dry run)")
            continue
        client = IsapiClient(f"{scheme}://{host}", user, password, verify_tls=verify_tls)
        try:
            r = client.put(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{sid}", f.read_text())
        finally:
            client.close()
        code, sub = response_status(r.text)
        ok = r.status == 200 and code in (STATUS_OK, STATUS_REBOOT)
        failed += not ok
        print(" -> done" if ok else f" -> refused: HTTP {r.status} {sub or code}")
        time.sleep(1)
    return 1 if failed else 0


def print_plan(changes: list[Change]) -> None:
    print(f"{'NVR':<14}{'Ch':>4} {'Stream':<5} {'Name':<28}{'Now':<8}{'Target':<8}Action")
    for c in changes:
        what = c.result or (c.action if c.action == "change" else f"skip: {c.reason}")
        print(f"{c.host:<14}{c.channel:>4} {c.kind:<5} {c.name[:27]:<28}{c.current:<8}{c.target:<8}{what}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Change stream codecs on Hikvision NVR channels. Dry run unless --apply.")
    p.add_argument("--host", action="append", default=[], help="NVR address, repeatable")
    p.add_argument("--hosts-file", type=Path, help="text file with one NVR address per line")
    p.add_argument("--sub-h264", action="store_true", help="set sub-streams to H.264 (needed for browser playback)")
    p.add_argument("--main-h265", action="store_true", help="set main streams to H.265 (saves NVR storage)")
    p.add_argument("--channels", help="only these channels, e.g. 1-8,12 (default all)")
    p.add_argument("--apply", action="store_true", help="make the changes (default is a dry run)")
    p.add_argument("--restore", type=Path, metavar="BACKUP_DIR", help="put back the settings saved in BACKUP_DIR")
    p.add_argument("--backup-dir", type=Path, default=Path("stream-backups"))
    p.add_argument("--pause", type=float, default=1.0, help="seconds to wait between changes (default 1)")
    p.add_argument("--https", action="store_true")
    p.add_argument("--insecure", action="store_true", help="accept the NVR's self-signed certificate")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    scheme = "https" if args.https else "http"
    user, password = credentials()
    if args.restore:
        return restore(args.restore, user, password, apply=args.apply, scheme=scheme, verify_tls=not args.insecure)

    hosts = list(args.host)
    if args.hosts_file:
        hosts += [ln.strip() for ln in args.hosts_file.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
    if not hosts or not (args.sub_h264 or args.main_h265):
        print("Give NVRs with --host and at least one of --sub-h264 or --main-h265.", file=sys.stderr)
        return 2

    run_dir = args.backup_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    channels = parse_channels(args.channels)
    all_changes: list[Change] = []
    for host in hosts:
        client = IsapiClient(f"{scheme}://{host}", user, password, verify_tls=not args.insecure)
        try:
            plan = plan_host(client, host, sub_codec="H.264" if args.sub_h264 else None,
                             main_codec="H.265" if args.main_h265 else None, channels=channels)
            if args.apply:
                for c in plan:
                    if c.action == "change":
                        apply_change(client, c, run_dir)
                        print(f"{host} ch {c.channel} {c.kind}: {c.result}", flush=True)
                        time.sleep(args.pause)
            all_changes += plan
        except RuntimeError as exc:
            print(f"{host}: {exc}", file=sys.stderr)
        finally:
            client.close()

    print()
    print_plan(all_changes)
    todo = [c for c in all_changes if c.action == "change"]
    if not args.apply:
        print(f"\nDry run: {len(todo)} stream(s) would change. Nothing was changed. Add --apply to make the changes.")
        return 0
    run_dir.mkdir(parents=True, exist_ok=True)
    with (run_dir / "report.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["nvr", "channel", "stream", "name", "before", "target", "action", "reason", "result"])
        for c in all_changes:
            w.writerow([c.host, c.channel, c.kind, c.name, c.current, c.target, c.action, c.reason, c.result])
    changed = sum(1 for c in todo if c.result.startswith("changed"))
    print(f"\n{changed} of {len(todo)} changed. Backups and report: {run_dir}")
    print(f"To undo: hss-streams --restore {run_dir} --apply")
    return 0 if changed == len(todo) else 1


if __name__ == "__main__":
    sys.exit(main())
