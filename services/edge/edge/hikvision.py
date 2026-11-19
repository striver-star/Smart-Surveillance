"""Hikvision alertStream: split the multipart stream, turn each notification into a platform event,
and raise each activity once (devices repeat "active" every second while it lasts)."""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

# Hikvision event type -> (platform type, default severity). The alert rules decide what alerts.
TYPE_MAP = {
    "linedetection": ("line_crossing", "warning"),
    "fielddetection": ("intrusion", "warning"),
    "regionentrance": ("region_entrance", "warning"),
    "regionexiting": ("region_exiting", "info"),
    "loitering": ("loitering", "warning"),
    "group": ("people_gathering", "warning"),
    "peoplegathering": ("people_gathering", "warning"),
    "rapidmove": ("rapid_move", "warning"),
    "parking": ("parking", "info"),
    "unattendedbaggage": ("unattended_object", "warning"),
    "attendedbaggage": ("object_removed", "warning"),
    "shelteralarm": ("tamper", "warning"),
    "tamperdetection": ("tamper", "warning"),
    "videoloss": ("video_loss", "warning"),
    "scenechangedetection": ("scene_change", "warning"),
    "defocus": ("defocus", "warning"),
    "vmd": ("motion", "info"),
    "motiondetection": ("motion", "info"),
    "facedetection": ("face_detected", "info"),
    "facesnap": ("face_detected", "info"),
    "facecapture": ("face_detected", "info"),
    "anpr": ("vehicle_plate", "info"),
    "vehicledetection": ("vehicle_detected", "info"),
    "audioexception": ("audio_exception", "info"),
    "io": ("alarm_input", "warning"),
    "diskerror": ("drive_fault", "critical"),
    "hderror": ("drive_fault", "critical"),
    "diskfull": ("disk_full", "warning"),
    "hdfull": ("disk_full", "warning"),
    "nicbroken": ("network_down", "warning"),
    "ipconflict": ("ip_conflict", "warning"),
    "illaccess": ("illegal_access", "warning"),
    "recordexception": ("recording_fault", "warning"),
    "videomismatch": ("video_mismatch", "info"),
}
MOTION = ("vmd", "motiondetection")


def accept(n, camera_id: str, ignore: set[str], smart_motion: set[str]) -> bool:
    """Whether to forward a notification (pure, tested). Ignored types (plain motion by default) are dropped,
    except motion from a camera chosen for smart motion when the camera says the target was a person or vehicle
    (Hikvision "Motion Detection 2.0" with human/vehicle filtering, on value-series cameras without smart events)."""
    if n.channel == 0:
        return False
    if n.raw_type not in ignore:
        return True
    return n.raw_type in MOTION and camera_id in smart_motion and n.object_class in ("human", "vehicle")


OBJECT_WORDS = {"human": "human", "person": "human", "people": "human", "vehicle": "vehicle", "car": "vehicle"}


def _strip(root: ET.Element) -> ET.Element:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return root


def _text(root: ET.Element, *tags: str) -> str:
    for t in tags:
        el = root.find(f".//{t}")
        if el is not None and el.text and el.text.strip():
            return el.text.strip()
    return ""


@dataclass
class Notification:
    raw_type: str
    state: str
    channel: int
    device_time: str
    description: str
    object_class: str | None
    xml: str
    image: bytes | None = None

    @property
    def platform(self) -> tuple[str, str]:
        if self.raw_type in MOTION and self.object_class:
            return ("motion", "warning")                 # smart motion: a person or vehicle, worth an alert
        return TYPE_MAP.get(self.raw_type, (f"other_{self.raw_type}"[:50], "info"))


def parse_notification(xml_text: str) -> Notification | None:
    try:
        root = _strip(ET.fromstring(xml_text))
    except ET.ParseError:
        return None
    if root.tag != "EventNotificationAlert":
        return None
    raw_type = _text(root, "eventType").lower()
    if not raw_type:
        return None
    ch = _text(root, "dynChannelID", "channelID", "inputIOPortID")
    obj = None
    for tag in ("targetType", "detectionTarget", "objectType", "TargetType"):
        word = _text(root, tag).lower()
        if word in OBJECT_WORDS:
            obj = OBJECT_WORDS[word]
            break
    return Notification(raw_type=raw_type, state=_text(root, "eventState").lower() or "active",
                        channel=int(ch) if ch.isdigit() else 0, device_time=_text(root, "dateTime"),
                        description=_text(root, "eventDescription"), object_class=obj, xml=xml_text)


class MultipartSplitter:
    """Feed bytes as they arrive; get back complete parts as (content_type, body).

    Hikvision sends multipart/mixed with a boundary from the Content-Type header; some firmware
    sends bare XML. Both are handled."""

    def __init__(self, boundary: str | None):
        self.marker = f"--{boundary}".encode() if boundary else None
        self.buf = b""

    def feed(self, chunk: bytes) -> list[tuple[str, bytes]]:
        self.buf += chunk
        out = []
        if not self.marker:
            while True:
                m = re.search(rb"<EventNotificationAlert.*?</EventNotificationAlert>", self.buf, re.S)
                if not m:
                    break
                out.append(("application/xml", m.group(0)))
                self.buf = self.buf[m.end():]
            if len(self.buf) > 1_000_000:
                self.buf = self.buf[-100_000:]
            return out
        while True:
            first = self.buf.find(self.marker)
            if first < 0:
                break
            nxt = self.buf.find(self.marker, first + len(self.marker))
            if nxt < 0:
                break
            part = self.buf[first + len(self.marker):nxt].strip(b"\r\n")
            self.buf = self.buf[nxt:]
            head, sep, body = part.partition(b"\r\n\r\n")
            if not sep:
                continue
            ctype = ""
            for line in head.split(b"\r\n"):
                if line.lower().startswith(b"content-type:"):
                    ctype = line.split(b":", 1)[1].strip().decode("latin-1").split(";")[0].lower()
            m = re.search(rb"content-length:\s*(\d+)", head, re.I)
            if m:
                body = body[:int(m.group(1))]
            out.append((ctype, body.rstrip(b"\r\n") if not ctype.startswith("image/") else body))
        if len(self.buf) > 20_000_000:          # a broken stream; don't grow without limit
            self.buf = self.buf[-1_000_000:]
        return out


def notifications(parts: list[tuple[str, bytes]]) -> list[Notification]:
    """Notifications in these parts; a picture part belongs to the notification just before it.
    Nothing is held back: a picture that arrives in a later read is fetched from the NVR instead."""
    out: list[Notification] = []
    for ctype, body in parts:
        if "xml" in ctype or body.lstrip().startswith(b"<"):
            n = parse_notification(body.decode("utf-8", "replace"))
            if n:
                out.append(n)
        elif ctype.startswith("image/") and out and out[-1].image is None and body[:2] == b"\xff\xd8":
            out[-1].image = body
    return out


@dataclass
class Debouncer:
    """Raise an event when an activity starts; ignore repeats until it has been quiet for `quiet_s`."""
    quiet_s: float = 10.0
    last_active: dict = field(default_factory=dict)

    def should_raise(self, n: Notification, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        key = (n.channel, n.raw_type)
        if n.state != "active":
            self.last_active.pop(key, None)
            return False
        prev = self.last_active.get(key)
        self.last_active[key] = now
        return prev is None or now - prev > self.quiet_s
