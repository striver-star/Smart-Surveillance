"""Reads a camera stream from the gateway and always offers the newest frame.

Decoding runs in its own thread and keeps only the latest frame, so slow inference never
builds up a backlog: the analysed frame is at most one frame old.

Decoding uses OpenCV's bundled FFmpeg, an LGPL build. PyAV was dropped in task 23: its wheels
include the GPL encoders x264 and x265, which Section 19 does not allow inside our process.
"""
from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np

# Pull RTSP over TCP (no lost UDP packets) and give up on a dead camera after 5 s. OpenCV reads
# this when it opens the stream, so it must be set before the first VideoCapture.
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000")
import cv2  # noqa: E402

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

    def _open(self) -> "cv2.VideoCapture":
        cap = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG, [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,
                                                         cv2.CAP_PROP_READ_TIMEOUT_MSEC, 10000])
        if not cap.isOpened():
            cap.release()
            raise ConnectionError("could not open stream")
        return cap

    def _run(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            cap = None
            try:
                cap = self._open()
                self.connected, backoff = True, 1.0
                fourcc = int(cap.get(cv2.CAP_PROP_FOURCC))
                codec = "".join(chr((fourcc >> 8 * i) & 0xFF) for i in range(4)).strip("\x00 ") or "?"
                log.info("%s: connected (%s %dx%d)", self.name, codec,
                         int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
                while not self._stop.is_set():
                    ok, image = cap.read()
                    if not ok:
                        raise ConnectionError("stream ended or timed out")
                    with self._lock:
                        self._seq += 1
                        self._latest = Frame(image, datetime.now(timezone.utc), self._seq)
                    self.decoded_frames += 1
                return
            except Exception as exc:  # network drop, camera reboot, bad stream: reconnect
                log.warning("%s: stream error %s: %s; retrying in %.0fs", self.name,
                            exc.__class__.__name__, exc, backoff)
            finally:
                if cap is not None:
                    cap.release()
            self.connected = False
            self._stop.wait(backoff)
            backoff = min(backoff * 2, 30.0)
