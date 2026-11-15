"""One NVR: event stream, health check, snapshots and clips."""
from __future__ import annotations

import base64
import logging
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

from .hikvision import Debouncer, MultipartSplitter, notifications

log = logging.getLogger("edge.nvr")


def alias(address: str) -> str:
    m = re.search(r"\.(\d+)$", address.split(":")[0])
    return f"nvr{m.group(1)}" if m else re.sub(r"[^A-Za-z0-9]", "", address)[:20]


def _strip(root):
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _t(el, path, default=""):
    f = el.find(path) if el is not None else None
    return f.text.strip() if f is not None and f.text else default


class Nvr:
    def __init__(self, address: str, user: str, password: str, *, scheme: str = "http", rtsp_port: int = 554,
                 transport: httpx.BaseTransport | None = None):
        self.address, self.user, self.password = address, user, password
        self.alias = alias(address)
        self.rtsp_port = rtsp_port
        self.http = httpx.Client(base_url=f"{scheme}://{address}", auth=httpx.DigestAuth(user, password),
                                 timeout=httpx.Timeout(10, read=30), verify=False, transport=transport)
        self.name = ""

    def get_xml(self, path: str):
        r = self.http.get(path)
        r.raise_for_status()
        return _strip(ET.fromstring(r.text))

    # ------------------------------------------------------------ health
    def health(self) -> dict:
        try:
            dev = self.get_xml("/ISAPI/System/deviceInfo")
        except httpx.HTTPStatusError as exc:
            return {"nvr": self.address, "reachable": False, "detail": f"login refused (HTTP {exc.response.status_code})"
                    if exc.response.status_code in (401, 403) else f"HTTP {exc.response.status_code}"}
        except (httpx.HTTPError, ET.ParseError) as exc:
            return {"nvr": self.address, "reachable": False, "detail": f"no answer ({exc.__class__.__name__})"}
        self.name = _t(dev, "deviceName") or self.alias
        out = {"nvr": self.address, "reachable": True, "name": self.name, "model": _t(dev, "model"),
               "firmware": _t(dev, "firmwareVersion"), "channels": [], "disks": []}
        try:
            names = {int(_t(c, "id")): (_t(c, "name"), _t(c, "sourceInputPortDescriptor/ipAddress"))
                     for c in self.get_xml("/ISAPI/ContentMgmt/InputProxy/channels").iter("InputProxyChannel") if _t(c, "id").isdigit()}
            for st in self.get_xml("/ISAPI/ContentMgmt/InputProxy/channels/status").iter("InputProxyChannelStatus"):
                cid = _t(st, "id")
                if cid.isdigit():
                    n, ip = names.get(int(cid), ("", ""))
                    out["channels"].append({"id": int(cid), "name": n, "ip": ip, "online": _t(st, "online").lower() == "true"})
        except (httpx.HTTPError, ET.ParseError) as exc:
            log.warning("%s: channel status unavailable: %s", self.address, exc)
        try:
            for hdd in self.get_xml("/ISAPI/ContentMgmt/Storage").iter("hdd"):
                cap, free = _t(hdd, "capacity"), _t(hdd, "freeSpace")
                out["disks"].append({"name": _t(hdd, "hddName") or f"hdd{_t(hdd, 'id')}", "status": _t(hdd, "status"),
                                     "capacity_gb": round(int(cap) / 1024, 1) if cap.isdigit() else None,
                                     "free_gb": round(int(free) / 1024, 1) if free.isdigit() else None})
        except (httpx.HTTPError, ET.ParseError) as exc:
            log.warning("%s: storage unavailable: %s", self.address, exc)
        try:
            out["time_mode"] = _t(self.get_xml("/ISAPI/System/time"), "timeMode")
        except (httpx.HTTPError, ET.ParseError):
            pass
        return out

    # ------------------------------------------------------------ snapshots
    def snapshot(self, channel: int) -> bytes | None:
        try:
            r = self.http.get(f"/ISAPI/Streaming/channels/{channel}01/picture", params={"snapShotImageType": "JPEG"}, timeout=8)
            return r.content if r.status_code == 200 and r.content[:2] == b"\xff\xd8" else None
        except httpx.HTTPError:
            return None

    # ------------------------------------------------------------ event stream
    def stream_events(self, on_event, stop, *, ignore: set[str], quiet_s: float = 10.0) -> None:
        """Read alertStream until it ends or `stop` is set; call on_event(platform_event) for each new activity."""
        debounce = Debouncer(quiet_s)
        with self.http.stream("GET", "/ISAPI/Event/notification/alertStream", timeout=httpx.Timeout(10, read=90)) as r:
            r.raise_for_status()
            m = re.search(r"boundary=\"?([^\";]+)", r.headers.get("content-type", ""))
            split = MultipartSplitter(m.group(1) if m else None)
            log.info("%s: event stream open", self.address)
            for chunk in r.iter_bytes():
                if stop.is_set():
                    return
                for n in notifications(split.feed(chunk)):
                    if n.raw_type in ignore or n.channel == 0 or not debounce.should_raise(n):
                        continue
                    on_event(self.to_event(n))

    def to_event(self, n) -> dict:
        ptype, severity = n.platform
        cam = f"{self.alias}-ch{n.channel:02d}"
        return {"camera_id": cam, "source_kind": "nvr" if not n.object_class else "edge", "source_ref": self.address,
                "tier": "N", "type": ptype, "object_class": n.object_class, "zone": None,
                "severity": severity, "occurred_at": datetime.now(timezone.utc).isoformat(),
                "snapshot_jpeg_b64": base64.b64encode(n.image).decode() if n.image else None,
                "raw": {"hik_type": n.raw_type, "device_time": n.device_time, "channel": n.channel,
                        "description": n.description}, "_channel": n.channel}

    # ------------------------------------------------------------ clips
    def playback_url(self, channel: int, start: datetime, end: datetime, tz: ZoneInfo) -> str:
        """RTSP playback of the recording. Hikvision expects the NVR's local time, written with a Z."""
        fmt = lambda t: t.astimezone(tz).strftime("%Y%m%dT%H%M%SZ")  # noqa: E731
        host = self.address.split(":")[0]
        return (f"rtsp://{quote(self.user, safe='')}:{quote(self.password, safe='')}@{host}:{self.rtsp_port}"
                f"/Streaming/tracks/{channel}01?starttime={fmt(start)}&endtime={fmt(end)}")

    def cut_clip(self, channel: int, start: datetime, end: datetime, tz: ZoneInfo, timeout_extra: int = 60) -> bytes:
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg is not installed")
        seconds = max(1, int((end - start).total_seconds()))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "clip.mp4"
            cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-rtsp_transport", "tcp",
                   "-i", self.playback_url(channel, start, end, tz), "-t", str(seconds), "-map", "0:v:0", "-c", "copy",
                   "-movflags", "+faststart", "-f", "mp4", str(out)]
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=seconds + timeout_extra)
            if p.returncode != 0 or not out.exists() or out.stat().st_size < 1000:
                err = (p.stderr or "no video").strip().splitlines()
                raise RuntimeError(re.sub(r"rtsp://[^@\s]+@", "rtsp://", err[-1] if err else "no video")[:300])
            # H.265 needs the hvc1 tag to play in Safari (iPhone); harmless to check every time.
            probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(out)], capture_output=True, text=True)
            if "Video: hevc" in probe.stderr:
                tagged = Path(tmp) / "clip-hvc1.mp4"
                subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(out), "-c", "copy", "-tag:v", "hvc1",
                                "-movflags", "+faststart", str(tagged)], check=True, timeout=60)
                out = tagged
            return out.read_bytes()
