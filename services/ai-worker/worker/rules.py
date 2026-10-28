"""Zone and schedule rules that turn detections into normalized events.

Zones are polygons in normalized frame coordinates (0 to 1), so they survive a change of
sub-stream resolution. An object is in a zone when its foot point is inside the polygon.
"""
from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, time as dtime

import cv2
import numpy as np

from .detector import Detection


@dataclass
class Zone:
    name: str
    polygon: list[list[float]]
    classes: list[str] = field(default_factory=lambda: ["human", "vehicle"])
    severity: str = "warning"
    armed: list[list[str]] | None = None      # e.g. [["18:00", "06:00"]]; None means always armed
    min_confidence: float = 0.5
    confirm_frames: int = 3                   # object seen in this many ...
    window_frames: int = 5                    # ... of the last N analysed frames
    cooldown_s: float = 30.0

    def is_armed(self, now: datetime) -> bool:
        if not self.armed:
            return True
        t = now.time()
        for start, end in self.armed:
            a, b = dtime.fromisoformat(start), dtime.fromisoformat(end)
            if (a <= t < b) if a <= b else (t >= a or t < b):
                return True
        return False

    def contains(self, point: tuple[float, float], frame_size: tuple[int, int]) -> bool:
        h, w = frame_size
        poly = np.array([[x * w, y * h] for x, y in self.polygon], dtype=np.float32)
        return cv2.pointPolygonTest(poly, (float(point[0]), float(point[1])), False) >= 0


@dataclass
class Trigger:
    zone: Zone
    object_class: str
    detections: list[Detection]

    @property
    def confidence(self) -> float:
        return max(d.confidence for d in self.detections)


class ZoneRules:
    """Confirms an intrusion over several frames and then holds off for the cooldown."""

    def __init__(self, zones: list[Zone], clock=time.monotonic):
        self.zones = zones
        self.clock = clock
        self._seen: dict[tuple[str, str], deque] = {}
        self._last_fired: dict[tuple[str, str], float] = {}

    def update(self, detections: list[Detection], frame_size: tuple[int, int], now: datetime) -> list[Trigger]:
        triggers = []
        for zone in self.zones:
            armed = zone.is_armed(now)
            for cls in zone.classes:
                key = (zone.name, cls)
                hits = [d for d in detections if d.object_class == cls and d.confidence >= zone.min_confidence
                        and zone.contains(d.foot_point(), frame_size)] if armed else []
                seen = self._seen.setdefault(key, deque(maxlen=zone.window_frames))
                seen.append(bool(hits))
                if not hits or sum(seen) < zone.confirm_frames:
                    continue
                last = self._last_fired.get(key)
                if last is not None and self.clock() - last < zone.cooldown_s:
                    continue
                self._last_fired[key] = self.clock()
                triggers.append(Trigger(zone, cls, hits))
        return triggers
