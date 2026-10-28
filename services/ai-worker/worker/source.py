"""Reads a camera stream from the gateway and always offers the newest frame.

Decoding runs in its own thread and keeps only the latest frame, so slow inference never
builds up a backlog: the analysed frame is at most one frame old.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import av
import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Frame:
    image: np.ndarray            # BGR
    captured_at: datetime        # wall clock time the frame was decoded (UTC)
    seq: int


class LatestFrameReader:
    def __init__(self, url: str, name: str):
        self.url, self.name = url, name
        self._lock = threading.Lock()
        self._latest: Frame | None = None
        self._stop = threading.Event()
        self._seq = 0
        self.connected = False
        self.decoded_frames = 0
        self._thread = threading.Thread(target=self._run, name=f"reader-{name}", daemon=True)

    def start(self) -> "LatestFrameReader":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def latest(self, newer_than: int = -1) -> Frame | None:
        with self._lock:
            f = self._latest
        return f if f is not None and f.seq > newer_than else None

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                options = {"rtsp_transport": "tcp", "timeout": "5000000"} if self.url.startswith("rtsp") else {}
                with av.open(self.url, options=options, timeout=10) as container:
                    stream = container.streams.video[0]
                    stream.thread_type = "AUTO"
                    self.connected, backoff = True, 1.0
                    log.info("%s: connected (%s %sx%s)", self.name, stream.codec_context.name,
                             stream.codec_context.width, stream.codec_context.height)
                    for frame in container.decode(stream):
                        if self._stop.is_set():
                            return
                        image = frame.to_ndarray(format="bgr24")
                        with self._lock:
                            self._seq += 1
                            self._latest = Frame(image, datetime.now(timezone.utc), self._seq)
                        self.decoded_frames += 1
            except Exception as exc:  # network drop, camera reboot, bad stream: reconnect
                log.warning("%s: stream error %s: %s; retrying in %.0fs", self.name,
                            exc.__class__.__name__, exc, backoff)
            self.connected = False
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)
