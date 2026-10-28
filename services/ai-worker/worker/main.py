"""Tier S AI worker: detects people and vehicles on non-AI cameras and posts normalized events.

Configuration comes from a JSON file (HSS_WORKER_CONFIG) and environment variables:
  HSS_API_URL        platform API, e.g. http://api:8000
  HSS_WORKER_TOKEN   shared secret for POST /events
  HSS_MODEL_PATH     ONNX model file (default /models/yolox_s.onnx)
  HSS_AI_PROVIDERS   optional comma-separated ONNX Runtime providers in order of preference
  HSS_TZ             timezone for zone schedules (default Africa/Lagos)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import signal
import socket
import threading
import time
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo

import cv2
import httpx

from .detector import Detector
from .rules import Zone, ZoneRules, Trigger
from .source import Frame, LatestFrameReader

log = logging.getLogger("worker")
WORKER_ID = os.environ.get("HSS_WORKER_ID") or socket.gethostname()


def build_event(camera_id: str, trigger: Trigger, frame: Frame, provider: str, inference_ms: float) -> dict:
    image = frame.image.copy()
    for d in trigger.detections:
        x1, y1, x2, y2 = (int(v) for v in d.box)
        cv2.rectangle(image, (x1, y1), (x2, y2), (0, 0, 255), 2)
        cv2.putText(image, f"{d.object_class} {d.confidence:.2f}", (x1, max(12, y1 - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 255), 1)
    ok, jpeg = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return {
        "camera_id": camera_id,
        "source_kind": "server_ai",
        "source_ref": WORKER_ID,
        "tier": "S",
        "type": "intrusion",
        "object_class": trigger.object_class,
        "zone": trigger.zone.name,
        "severity": trigger.zone.severity,
        "confidence": round(trigger.confidence, 3),
        "occurred_at": frame.captured_at.isoformat(),
        "snapshot_jpeg_b64": base64.b64encode(jpeg.tobytes()).decode() if ok else None,
        "raw": {
            "objects": [{"class": d.object_class, "confidence": round(d.confidence, 3),
                         "box": [round(v, 1) for v in d.box]} for d in trigger.detections],
            "frame_size": list(frame.image.shape[1::-1]),
            "provider": provider,
            "inference_ms": round(inference_ms, 1),
        },
    }


class EventSender:
    """Posts events; keeps up to 1000 in memory while the API is unreachable and resends them in order."""

    def __init__(self, api_url: str, token: str):
        self._http = httpx.Client(base_url=api_url, timeout=5.0, headers={"Authorization": f"Bearer {token}"})
        self._queue: deque[dict] = deque(maxlen=1000)
        self._lock = threading.Lock()

    def send(self, event: dict) -> None:
        with self._lock:
            self._queue.append(event)
        self.flush()

    def flush(self) -> None:
        with self._lock:
            while self._queue:
                try:
                    r = self._http.post("/events", json=self._queue[0])
                except httpx.HTTPError as exc:
                    log.warning("API unreachable (%s); %d event(s) queued", exc.__class__.__name__, len(self._queue))
                    return
                if r.status_code >= 500:
                    log.warning("API error %s; %d event(s) queued", r.status_code, len(self._queue))
                    return
                sent = self._queue.popleft()
                if r.status_code != 201:
                    log.error("event rejected (%s): %s", r.status_code, r.text[:300])
                else:
                    log.info("event %s %s in %s on %s: latency %s ms", sent["object_class"], sent["type"],
                             sent["zone"], sent["camera_id"], r.json().get("latency_ms"))


def run_camera(cam: dict, detector: Detector, sender: EventSender, stop: threading.Event, tz: ZoneInfo,
               detector_lock: threading.Lock) -> None:
    camera_id = cam["camera_id"]
    fps = float(cam.get("analysis_fps", 5))
    rules = ZoneRules([Zone(**z) for z in cam["zones"]])
    reader = LatestFrameReader(cam["source"], camera_id).start()
    last_seq, analysed, total_ms, last_report = -1, 0, 0.0, time.monotonic()
    while not stop.is_set():
        started = time.monotonic()
        frame = reader.latest(newer_than=last_seq)
        if frame is not None:
            last_seq = frame.seq
            with detector_lock:
                t0 = time.perf_counter()
                detections = detector.detect(frame.image)
                ms = (time.perf_counter() - t0) * 1000
            analysed, total_ms = analysed + 1, total_ms + ms
            for trig in rules.update(detections, frame.image.shape[:2], datetime.now(tz)):
                sender.send(build_event(camera_id, trig, frame, detector.active_provider, ms))
        if time.monotonic() - last_report >= 30:
            sender.flush()   # resend anything queued while the API was down
            elapsed = time.monotonic() - last_report
            log.info("%s: connected=%s analysed %.1f fps, inference %.0f ms avg, decoded %d frames",
                     camera_id, reader.connected, analysed / elapsed, total_ms / max(analysed, 1),
                     reader.decoded_frames)
            analysed, total_ms, last_report = 0, 0.0, time.monotonic()
        stop.wait(max(0.0, 1.0 / fps - (time.monotonic() - started)))
    reader.stop()


def main() -> None:
    logging.basicConfig(level=os.environ.get("HSS_LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    with open(os.environ.get("HSS_WORKER_CONFIG", "/config/worker.json"), encoding="utf-8") as f:
        config = json.load(f)
    detector = Detector(os.environ.get("HSS_MODEL_PATH", "/models/yolox_s.onnx"),
                        score_threshold=float(config.get("score_threshold", 0.4)))
    log.info("model %s input %s on %s (available: %s)", os.environ.get("HSS_MODEL_PATH"), detector.size,
             detector.active_provider, ",".join(detector.providers))
    sender = EventSender(os.environ.get("HSS_API_URL", "http://api:8000"), os.environ["HSS_WORKER_TOKEN"])
    tz = ZoneInfo(os.environ.get("HSS_TZ", "Africa/Lagos"))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    lock = threading.Lock()   # one inference at a time per worker; scale out with more workers or GPUs
    threads = [threading.Thread(target=run_camera, args=(cam, detector, sender, stop, tz, lock),
                                name=cam["camera_id"], daemon=True) for cam in config["cameras"]]
    for t in threads:
        t.start()
    for t in threads:
        t.join()


if __name__ == "__main__":
    main()
