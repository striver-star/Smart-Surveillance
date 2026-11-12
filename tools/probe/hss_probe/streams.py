"""hss-streams: change camera stream codecs on many Hikvision NVRs at once.

Default is a dry run that only shows what would change. With --apply it backs up each stream's
settings, changes only the codec, checks the result, and writes a report. --restore puts saved
settings back. Example:

  hss-streams --host 10.1.3.4 --host 10.1.3.5 --sub-h264            # preview
  hss-streams --host 10.1.3.4 --host 10.1.3.5 --sub-h264 --apply    # change
  hss-streams --host 10.1.3.4 --sub-fps 12 --apply                  # lighter wall load
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
FPS = re.compile(r"(<maxFrameRate>)([^<]*)(</maxFrameRate>)")   # hundredths: 2500 = 25 fps, 0 = full rate
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
    edits: dict = field(default_factory=dict)   # {"codec": "H.264", "fps": 1200}
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


def _video_value(xml: str, pattern: re.Pattern) -> str:
    block = VIDEO_BLOCK.search(xml)
    m = pattern.search(block.group(0)) if block else None
    return m.group(2).strip() if m else ""


def _with_video_value(xml: str, pattern: re.Pattern, value: str, what: str) -> str:
    """Change one setting inside <Video>, keeping every other setting and the XML namespace."""
    block = VIDEO_BLOCK.search(xml)
    if not block:
        raise ValueError("no <Video> section in the stream settings")
    new_block, n = pattern.subn(lambda m: m.group(1) + value + m.group(3), block.group(0), count=1)
    if n != 1:
        raise ValueError(f"no {what} in the stream settings")
    return xml[:block.start()] + new_block + xml[block.end():]


def current_codec(xml: str) -> str:
    return _video_value(xml, CODEC)


def with_codec(xml: str, codec: str) -> str:
    return _with_video_value(xml, CODEC, codec, "videoCodecType")


def current_fps(xml: str) -> int | None:
    """Frame rate in hundredths (2500 = 25 fps); 0 means the camera's full rate; None if not reported."""
    v = _video_value(xml, FPS)
    return int(v) if v.isdigit() else None


def with_fps(xml: str, hundredths: int) -> str:
    return _with_video_value(xml, FPS, str(hundredths), "maxFrameRate")


def fps_label(hundredths: int | None) -> str:
    if hundredths is None:
        return "?"
    return "full fps" if hundredths == 0 else f"{hundredths / 100:g} fps"


def apply_edits(xml: str, edits: dict) -> str:
    if "codec" in edits:
        xml = with_codec(xml, edits["codec"])
    if "fps" in edits:
        xml = with_fps(xml, edits["fps"])
    return xml


def capabilities(client: IsapiClient, stream_id: int) -> str | None:
    r = client.get(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{stream_id}/capabilities")
    return r.text if r.ok else None


def _options(caps: str | None, tag: str) -> list[str] | None:
    if caps is None:
        return None
    m = re.search(rf"<{tag}\b[^>]*\bopt=\"([^\"]*)\"", caps)
    return [c.strip() for c in m.group(1).split(",") if c.strip()] if m else None


def supported_codecs(caps: str | None) -> list[str] | None:
    """Codecs the camera accepts for this stream, or None when the NVR does not say."""
    return _options(caps, "videoCodecType")


def best_fps(caps: str | None, wanted: int) -> int | None:
    """The highest frame rate the camera offers that is not above `wanted` (hundredths).
    Returns `wanted` when the camera lists no options, None when nothing fits."""
    opts = _options(caps, "maxFrameRate")
    if opts is None:
        return wanted
    values = sorted({int(o) for o in opts if o.isdigit() and int(o) > 0})
    fitting = [v for v in values if v <= wanted]
    return fitting[-1] if fitting else None


def response_status(text: str) -> tuple[str, str]:
    code = re.search(r"<statusCode>(\d+)</statusCode>", text)
    sub = re.search(r"<subStatusCode>([^<]+)</subStatusCode>", text)
    return (code.group(1) if code else ""), (sub.group(1) if sub else "")


def plan_host(client: IsapiClient, host: str, *, sub_codec: str | None, main_codec: str | None,
              channels: set[int] | None, sub_fps: int | None = None) -> list[Change]:
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
        codec_target = {"sub": sub_codec, "main": main_codec}.get(kind)
        fps_target = sub_fps if kind == "sub" else None
        if not (codec_target or fps_target) or (channels is not None and ch not in channels):
            continue
        r = client.get(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{sid}")
        cur_codec = current_codec(r.text) if r.ok else ""
        cur_fps = current_fps(r.text) if r.ok else None
        now = " ".join(x for x in [cur_codec if codec_target else "", fps_label(cur_fps) if fps_target else ""] if x)
        c = Change(host, sid, ch, kind, names.get(ch, ""), now, "", original_xml=r.text if r.ok else "")
        if online.get(ch) is False:
            c.action, c.reason = "skip", "camera offline"
        elif not r.ok:
            c.action, c.reason = "skip", f"cannot read settings (HTTP {r.status})"
        else:
            caps = capabilities(client, sid)
            reasons = []
            if codec_target:
                opts = supported_codecs(caps)
                if cur_codec.upper() == codec_target.upper():
                    reasons.append(f"already {codec_target}")
                elif opts is not None and not any(o.upper() == codec_target.upper() for o in opts):
                    reasons.append(f"camera does not offer {codec_target} (offers {', '.join(opts)})")
                else:
                    c.edits["codec"] = codec_target
            if fps_target:
                if cur_fps is None:
                    reasons.append("frame rate not reported")
                elif cur_fps != 0 and cur_fps <= fps_target:
                    reasons.append(f"already {fps_label(cur_fps)}")
                else:
                    best = best_fps(caps, fps_target)
                    if best is None:
                        reasons.append(f"camera offers no rate at or below {fps_label(fps_target)}")
                    else:
                        c.edits["fps"] = best
            c.target = " ".join(x for x in [c.edits.get("codec", ""), fps_label(c.edits["fps"]) if "fps" in c.edits else ""] if x)
            c.action = "change" if c.edits else "skip"
            c.reason = "; ".join(reasons)
        plan.append(c)
    return plan


def apply_change(client: IsapiClient, c: Change, backup_dir: Path) -> None:
    host_dir = backup_dir / re.sub(r"[^A-Za-z0-9._-]", "_", c.host)
    host_dir.mkdir(parents=True, exist_ok=True)
    (host_dir / f"{c.stream_id}.xml").write_text(c.original_xml, encoding="utf-8")
    r = client.put(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{c.stream_id}", apply_edits(c.original_xml, c.edits))
    code, sub = response_status(r.text)
    if r.status != 200 or code not in (STATUS_OK, STATUS_REBOOT):
        c.result = f"refused: HTTP {r.status} {sub or code}".strip()
        return
    check = client.get(f"/ISAPI/ContentMgmt/StreamingProxy/channels/{c.stream_id}")
    wrong = []
    if "codec" in c.edits:
        now = current_codec(check.text) if check.ok else "?"
        if now.upper() != c.edits["codec"].upper():
            wrong.append(now)
    if "fps" in c.edits:
        now_fps = current_fps(check.text) if check.ok else None
        if now_fps != c.edits["fps"]:
            wrong.append(fps_label(now_fps))
    if not wrong:
        c.result = "changed" + (" (camera asks for a reboot)" if code == STATUS_REBOOT else "")
    else:
        c.result = f"not confirmed: camera reports {' '.join(wrong)}"


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
    print(f"{'NVR':<14}{'Ch':>4} {'Stream':<5} {'Name':<28}{'Now':<16}{'Target':<16}Action")
    for c in changes:
        what = c.result or (c.action if c.action == "change" else f"skip: {c.reason}")
        if c.action == "change" and c.reason and not c.result:
            what += f" (also: {c.reason})"
        print(f"{c.host:<14}{c.channel:>4} {c.kind:<5} {c.name[:27]:<28}{c.current:<16}{c.target:<16}{what}")


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Change stream codecs on Hikvision NVR channels. Dry run unless --apply.")
    p.add_argument("--host", action="append", default=[], help="NVR address, repeatable")
    p.add_argument("--hosts-file", type=Path, help="text file with one NVR address per line")
    p.add_argument("--sub-h264", action="store_true", help="set sub-streams to H.264 (needed for browser playback)")
    p.add_argument("--main-h265", action="store_true", help="set main streams to H.265 (saves NVR storage)")
    p.add_argument("--sub-fps", type=float, metavar="FPS",
                   help="lower sub-stream frame rates to at most FPS, e.g. 12 (lighter load on wall PCs)")
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
    if not hosts or not (args.sub_h264 or args.main_h265 or args.sub_fps):
        print("Give NVRs with --host and at least one of --sub-h264, --main-h265 or --sub-fps.", file=sys.stderr)
        return 2

    run_dir = args.backup_dir / datetime.now().strftime("%Y%m%d-%H%M%S")
    channels = parse_channels(args.channels)
    all_changes: list[Change] = []
    for host in hosts:
        client = IsapiClient(f"{scheme}://{host}", user, password, verify_tls=not args.insecure)
        try:
            plan = plan_host(client, host, sub_codec="H.264" if args.sub_h264 else None,
                             main_codec="H.265" if args.main_h265 else None, channels=channels,
                             sub_fps=round(args.sub_fps * 100) if args.sub_fps else None)
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
