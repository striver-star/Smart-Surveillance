"""Face and plate recognition service, stage 4 (go-live). Run: python -m worker.recognition

Everything comes from the platform (no local watchlist files): every minute the service asks
/recognition/worker/state for what the legal review has unlocked, the approved cameras, the thresholds and
the watchlists (face embeddings and plates of active, unexpired entries). If recognition is locked, or the
platform can't be asked, it stops every camera and forgets the watchlists.

Privacy by design:
- Faces and plates are compared with the watchlists in memory. Only matches are sent to the platform;
  everything else is discarded at once. Status reports carry counts only.
- New enrolment photos are turned into face data here (detection, quality check, embedding) and the result
  goes back to the platform; photos are not kept by this service.
- One match per person (or plate) per camera every `repeat_s` seconds.

Cameras are read at their main stream straight from the NVR (the platform sends the address); the gateway
carries sub-streams only, which are too small for faces and plates.

Environment: HSS_API_URL, HSS_WORKER_TOKEN, HSS_MODELS_DIR (default /models), HSS_RTSP_BASE
(default rtsp://gateway:8554: only for cameras not on an NVR added in Devices),
HSS_RECOGNITION_FPS (default 3).
"""
from __future__ import annotations

import base64
import logging
import os
import signal
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import httpx
import numpy as np

from .face import FaceEngine, Person, Watchlist
from .main import EventSender
from .source import LatestFrameReader

log = logging.getLogger("recognition")
WORKER_ID = os.environ.get("HSS_WORKER_ID") or socket.gethostname()


# ------------------------------------------------------------------ pure helpers (tested)

class Repeats:
    """Suppresses the same match on the same camera within `window` seconds."""

    def __init__(self, window: float):
        self.window, self.last = window, {}

    def fresh(self, key: tuple, now: float) -> bool:
        if now - self.last.get(key, -1e18) < self.window:
            return False
        self.last[key] = now
        if len(self.last) > 5000:
            cutoff = now - self.window
            self.last = {k: v for k, v in self.last.items() if v >= cutoff}
        return True


def plate_decision(plate: str, confidence: float, entries: dict[str, dict], min_confidence: float,
                   lists: dict[str, str | None]) -> dict | None:
    """The watchlist entry a plate read should be reported for, or None (pure, tested). Unknown plates,
    reads below the confidence floor and plates on a list with no severity (allow) are not reported."""
    if confidence < min_confidence:
        return None
    e = entries.get(plate)
    if not e or not lists.get(e["list"]):
        return None
    return e


def context_crop(image: np.ndarray, box: tuple[int, int, int, int], scale: float = 2.6, min_w: int = 320) -> np.ndarray:
    """The area around a face or plate, with the box drawn, for the operator to compare (pure, tested)."""
    h, w = image.shape[:2]
    x, y, bw, bh = box
    cx, cy = x + bw / 2, y + bh / 2
    half_w = max(bw * scale, min_w) / 2
    half_h = max(bh * scale, half_w * 0.75)
    x1, y1 = int(max(0, cx - half_w)), int(max(0, cy - half_h))
    x2, y2 = int(min(w, cx + half_w)), int(min(h, cy + half_h))
    crop = image[y1:y2, x1:x2].copy()
    cv2.rectangle(crop, (x - x1, y - y1), (x - x1 + bw, y - y1 + bh), (0, 0, 255), 2)
    return crop


def roi_crop(image: np.ndarray, roi: list[float] | None) -> tuple[np.ndarray, int, int]:
    if not roi:
        return image, 0, 0
    h, w = image.shape[:2]
    x1, y1, x2, y2 = int(roi[0] * w), int(roi[1] * h), int(roi[2] * w), int(roi[3] * h)
    return image[y1:y2, x1:x2], x1, y1


def jpeg_b64(image: np.ndarray) -> str | None:
    ok, buf = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buf.tobytes()).decode() if ok else None


# ------------------------------------------------------------------ the service

@dataclass
class State:
    unlocked: dict = field(default_factory=lambda: {"face": False, "plate": False})
    cameras: dict = field(default_factory=dict)
    watchlist: Watchlist | None = None
    plates: dict = field(default_factory=dict)
    face_lists: dict = field(default_factory=dict)
    plate_lists: dict = field(default_factory=dict)
    plate_min_confidence: float = 0.8
    repeat_s: float = 60


class Recognition:
    def __init__(self, api_url: str, token: str, models: Path, rtsp_base: str, fps: float):
        self.http = httpx.Client(base_url=api_url, timeout=10, headers={"Authorization": f"Bearer {token}"})
        self.sender = EventSender(api_url, token)
        self.rtsp_base, self.fps = rtsp_base.rstrip("/"), fps
        self.face = FaceEngine(str(models / "face_detection_yunet_2023mar.onnx"), str(models / "face_recognition_sface_2021dec.onnx"))
        self.plates = None
        self._plate_paths = (models / "ch_PP-OCRv4_det_infer.onnx", models / "ch_PP-OCRv4_rec_infer.onnx")
        self.state = State()
        self.lock = threading.Lock()              # one model call at a time
        self.threads: dict[str, tuple[threading.Thread, threading.Event]] = {}
        self.sources: dict[str, str | None] = {}
        self.counts: dict[str, dict] = {}
        self.repeats = Repeats(60)

    def plate_reader(self):
        if self.plates is None:
            from .plate import PlateReader
            self.plates = PlateReader(str(self._plate_paths[0]), str(self._plate_paths[1]))
        return self.plates

    # --- state from the platform
    def refresh(self) -> None:
        try:
            r = self.http.get("/recognition/worker/state")
            r.raise_for_status()
            st = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("platform not reachable (%s): recognition paused", exc.__class__.__name__)
            st = {"unlocked": {"face": False, "plate": False}, "cameras": []}
        people = [Person(p["id"], p["name"], p["list"], "platform",
                         np.stack([np.frombuffer(base64.b64decode(e), dtype=np.float32) for e in p["embeddings"]]))
                  for p in st.get("people", []) if p.get("embeddings")]
        new = State(unlocked=st["unlocked"], cameras={c["camera_id"]: c for c in st.get("cameras", [])},
                    watchlist=Watchlist(people, st.get("face_threshold", 0.40), st.get("face_margin", 0.06)) if st["unlocked"].get("face") else None,
                    plates={p["plate"]: p for p in st.get("plates", [])} if st["unlocked"].get("plate") else {},
                    face_lists=st.get("face_lists", {}), plate_lists=st.get("plate_lists", {}),
                    plate_min_confidence=st.get("plate_min_confidence", 0.8), repeat_s=st.get("repeat_s", 60))
        with self.lock:
            self.state = new
            self.repeats.window = new.repeat_s
        if st["unlocked"].get("face"):
            for fid in st.get("pending_faces", []):
                self.enrol(fid)
        self.sync_cameras()

    def enrol(self, fid: str) -> None:
        """Turn a new enrolment photo into face data: exactly one good face, or rejected with the reason."""
        try:
            r = self.http.get(f"/recognition/worker/faces/{fid}/photo")
            r.raise_for_status()
            img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                raise ValueError("unreadable image")
            with self.lock:
                faces = self.face.detect(img)
                good = [f for f in faces if f.quality_ok]
                if len(faces) == 1 and good:
                    vec = self.face.embed(img, good[0])
                    body = {"status": "ok", "embedding_b64": base64.b64encode(vec.astype(np.float32).tobytes()).decode(),
                            "quality": good[0].quality}
                else:
                    why = ("no face found" if not faces else f"{len(faces)} faces in the photo; use a photo of one person"
                           if len(faces) > 1 else "face " + ", ".join(faces[0].quality["problems"]))
                    body = {"status": "rejected", "problem": why, "quality": faces[0].quality if len(faces) == 1 else {}}
            self.http.put(f"/recognition/worker/faces/{fid}", json=body).raise_for_status()
            log.info("enrolment photo %s: %s", fid[:8], body["status"] if body["status"] == "ok" else body["problem"])
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("enrolment photo %s: %s", fid[:8], exc)

    def sync_cameras(self) -> None:
        wanted = set(self.state.cameras)
        for cam in list(self.threads):
            src = (self.state.cameras.get(cam) or {}).get("source")
            if cam not in wanted or self.sources.get(cam) != src:      # removed, or its address changed (new NVR password)
                self.sources.pop(cam, None)
                self.threads.pop(cam)[1].set()
                log.info("%s: recognition stopped", cam)
        for cam in wanted - set(self.threads):
            stop = threading.Event()
            t = threading.Thread(target=self.run_camera, args=(cam, stop), name=f"rec-{cam}", daemon=True)
            self.threads[cam] = (t, stop)
            self.sources[cam] = (self.state.cameras.get(cam) or {}).get("source")
            t.start()
            log.info("%s: recognition started", cam)

    # --- one camera
    def run_camera(self, cam: str, stop: threading.Event) -> None:
        cfg0 = self.state.cameras.get(cam) or {}
        source = cfg0.get("source") or f"{self.rtsp_base}/{cam}"      # main stream from the NVR; gateway path only as a fallback
        if not cfg0.get("source"):
            log.warning("%s: not on an NVR added in Devices; reading %s/%s (a sub-stream is too small for recognition)", cam, self.rtsp_base, cam)
        reader = LatestFrameReader(source, cam).start()
        c = self.counts.setdefault(cam, {"frames": 0, "faces": 0, "good_faces": 0, "face_matches": 0, "plate_reads": 0, "plate_matches": 0})
        last = -1
        while not stop.is_set():
            t0 = time.monotonic()
            frame = reader.latest(newer_than=last)
            cfg = self.state.cameras.get(cam)
            if frame is not None and cfg:
                last = frame.seq
                c["frames"] += 1
                c["connected"] = reader.connected
                try:
                    if cfg.get("face") and self.state.watchlist and self.state.watchlist.people:
                        self.faces(cam, frame, c)
                    if cfg.get("plate") and self.state.plates:
                        self.read_plates(cam, cfg, frame, c)
                except Exception:
                    log.exception("%s: analysis failed", cam)
            c["connected"] = reader.connected
            stop.wait(max(0.0, 1.0 / self.fps - (time.monotonic() - t0)))
        reader.stop()

    def faces(self, cam: str, frame, c: dict) -> None:
        with self.lock:
            wl = self.state.watchlist
            faces = self.face.detect(frame.image)
            c["faces"] += len(faces)
            results = []
            for f in faces:
                if not f.quality_ok:
                    continue
                c["good_faces"] += 1
                m, _best = wl.match(self.face.embed(frame.image, f))
                if m:
                    results.append((f, m))
        for f, m in results:                              # unmatched faces were never kept
            if not self.repeats.fresh((cam, "face", m.person_id), time.monotonic()):
                continue
            severity = self.state.face_lists.get(m.list_name) or "warning"
            c["face_matches"] += 1
            self.sender.send({
                "camera_id": cam, "source_kind": "server_ai", "source_ref": WORKER_ID, "tier": "S", "type": "face_match",
                "object_class": "person", "zone": None, "severity": severity, "confidence": m.score,
                "occurred_at": frame.captured_at.isoformat(), "snapshot_jpeg_b64": jpeg_b64(context_crop(frame.image, f.box)),
                "raw": {"kind": "face", "person_id": m.person_id, "name": m.name, "list": m.list_name, "score": m.score,
                        "margin": m.margin, "quality": f.quality}})

    def read_plates(self, cam: str, cfg: dict, frame, c: dict) -> None:
        img, ox, oy = roi_crop(frame.image, cfg.get("roi"))
        with self.lock:
            reads = self.plate_reader().read_plates(img, min_confidence=0.5)
        for rd in reads:
            c["plate_reads"] += 1
            e = plate_decision(rd.plate, rd.confidence, self.state.plates, self.state.plate_min_confidence, self.state.plate_lists)
            if not e or not self.repeats.fresh((cam, "plate", rd.plate), time.monotonic()):
                continue
            xs, ys = rd.box[:, 0] + ox, rd.box[:, 1] + oy
            box = (int(xs.min()), int(ys.min()), int(np.ptp(xs)), int(np.ptp(ys)))
            c["plate_matches"] += 1
            self.sender.send({
                "camera_id": cam, "source_kind": "server_ai", "source_ref": WORKER_ID, "tier": "S", "type": "plate_match",
                "object_class": "vehicle", "zone": None, "severity": self.state.plate_lists.get(e["list"]) or "warning",
                "confidence": rd.confidence, "occurred_at": frame.captured_at.isoformat(),
                "snapshot_jpeg_b64": jpeg_b64(context_crop(frame.image, box, scale=4.0, min_w=480)),
                "raw": {"kind": "plate", "plate": rd.plate, "display": rd.display, "list": e["list"], "entry_id": e["id"],
                        "name": e.get("name", ""), "confidence": rd.confidence}})

    def report(self) -> None:
        try:
            self.http.post("/recognition/worker/status", json={"cameras": self.counts, "note": WORKER_ID})
        except httpx.HTTPError:
            pass
        self.sender.flush()


def main() -> None:
    logging.basicConfig(level=os.environ.get("HSS_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    svc = Recognition(os.environ.get("HSS_API_URL", "http://api:8000"), os.environ["HSS_WORKER_TOKEN"],
                      Path(os.environ.get("HSS_MODELS_DIR", "/models")), os.environ.get("HSS_RTSP_BASE", "rtsp://gateway:8554"),
                      float(os.environ.get("HSS_RECOGNITION_FPS", "3")))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    while not stop.is_set():
        svc.refresh()
        svc.report()
        stop.wait(60 if svc.threads else 30)
    for _t, s in svc.threads.values():
        s.set()


if __name__ == "__main__":
    main()
