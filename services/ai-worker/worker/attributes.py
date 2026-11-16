"""Attributes for smart search (release 2.0, third batch). Run: python -m worker.attributes

Looks at the snapshot of each stored event, finds the people and vehicles in it (the same YOLOX model as the
Tier S worker) and works out their colours: a person's top and bottom clothing, a vehicle's body. The result
goes back to the platform, where the Smart search page can find "a person in a red top and blue trousers at the
gate between 20:00 and 23:00". Nobody is identified: clothing and vehicle colours only. Face and plate
recognition snapshots are never analysed.

Works on any camera that sends a snapshot with its events (Hikvision AcuSense and DeepinView events, the
server AI, the edge service). Newest events first, then older ones in the background.

Environment: HSS_API_URL, HSS_WORKER_TOKEN, HSS_MODEL_PATH (default /models/yolox_s.onnx).
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time
from collections import Counter

import cv2
import httpx
import numpy as np

from .detector import Detector

log = logging.getLogger("attributes")
COLOURS = ("black", "white", "grey", "red", "orange", "yellow", "green", "blue", "purple", "pink", "brown")


# ------------------------------------------------------------------ pure helpers (tested)

def colour_names(hsv: np.ndarray) -> np.ndarray:
    """A colour name index (into COLOURS) for every pixel of an HSV image (OpenCV ranges: H 0-179, S and V 0-255)."""
    h, s, v = hsv[..., 0].astype(int), hsv[..., 1].astype(int), hsv[..., 2].astype(int)
    out = np.full(h.shape, COLOURS.index("grey"))
    chroma = (s >= 60) & (v >= 50)
    out[v < 50] = COLOURS.index("black")
    out[(s < 40) & (v >= 185)] = COLOURS.index("white")
    hue = [(0, 9, "red"), (9, 20, "orange"), (20, 34, "yellow"), (34, 85, "green"), (85, 130, "blue"), (130, 155, "purple"),
           (155, 172, "pink"), (172, 180, "red")]
    for lo, hi, name in hue:
        out[chroma & (h >= lo) & (h < hi)] = COLOURS.index(name)
    # Brown is a dark orange or red; pink is a light, less saturated red.
    out[chroma & (h < 20) & (v < 150) & (s >= 60)] = COLOURS.index("brown")
    out[chroma & ((h < 9) | (h >= 155)) & (s < 140) & (v >= 170)] = COLOURS.index("pink")
    return out


def dominant(region_bgr: np.ndarray, top: int = 2, min_share: float = 0.22) -> list[str]:
    """The main colours of a region: the commonest, and a second one if it covers min_share (pure, tested)."""
    if region_bgr.size == 0 or region_bgr.shape[0] < 4 or region_bgr.shape[1] < 4:
        return []
    small = cv2.resize(region_bgr, (min(48, region_bgr.shape[1]), min(48, region_bgr.shape[0])), interpolation=cv2.INTER_AREA)
    names = colour_names(cv2.cvtColor(cv2.GaussianBlur(small, (3, 3), 0), cv2.COLOR_BGR2HSV)).ravel()
    counts = Counter(names.tolist())
    total = sum(counts.values())
    ranked = [(COLOURS[i], n / total) for i, n in counts.most_common(top)]
    return [ranked[0][0]] + [c for c, share in ranked[1:] if share >= min_share]


def regions(box: tuple[float, float, float, float], kind: str, shape: tuple[int, int]) -> dict[str, tuple[int, int, int, int]]:
    """Where to read colours inside a box, shrunk away from its edges and any drawn outline (pure, tested).
    Person: top = 20-50 % of the height (below the head), bottom = 55-88 %; vehicle: body = the middle band."""
    h_img, w_img = shape
    x1, y1, x2, y2 = box
    w, h = x2 - x1, y2 - y1
    def band(t, b, side=0.22):
        return (int(max(0, x1 + w * side)), int(max(0, y1 + h * t)), int(min(w_img, x2 - w * side)), int(min(h_img, y1 + h * b)))
    if kind == "human":
        return {"upper": band(0.20, 0.50), "lower": band(0.55, 0.88, 0.28)}
    return {"body": band(0.30, 0.70, 0.12)}


def describe(image: np.ndarray, detections, min_px: int = 24) -> list[dict]:
    """People and vehicles in an image with their colours; tiny ones are skipped (pure apart from the detector)."""
    out = []
    for d in detections:
        x1, y1, x2, y2 = d.box
        if (y2 - y1) < min_px * 2 or (x2 - x1) < min_px:
            continue
        item = {"class": d.object_class, "confidence": round(d.confidence, 3), "box": [round(v) for v in d.box]}
        for part, (a, b, c, e) in regions(d.box, d.object_class, image.shape[:2]).items():
            item[part] = dominant(image[b:e, a:c])
        out.append(item)
    return out


# ------------------------------------------------------------------ the service

def main() -> None:
    logging.basicConfig(level=os.environ.get("HSS_LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    detector = Detector(os.environ.get("HSS_MODEL_PATH", "/models/yolox_s.onnx"), score_threshold=0.45)
    http = httpx.Client(base_url=os.environ.get("HSS_API_URL", "http://api:8000"), timeout=15,
                        headers={"Authorization": f"Bearer {os.environ['HSS_WORKER_TOKEN']}"})
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())
    done = 0
    while not stop.is_set():
        try:
            todo = http.get("/search/worker/next", params={"limit": 20}).raise_for_status().json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("platform not reachable (%s)", exc.__class__.__name__)
            stop.wait(30)
            continue
        if not todo:
            stop.wait(20)
            continue
        for ev in todo:
            if stop.is_set():
                break
            try:
                r = http.get(f"/search/worker/snapshot/{ev['id']}")
                img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR) if r.status_code == 200 else None
                objects = describe(img, detector.detect(img)) if img is not None else []
                http.put(f"/search/worker/attributes/{ev['id']}", json={"objects": objects, "ok": img is not None}).raise_for_status()
                done += 1
            except httpx.HTTPError as exc:
                log.warning("event %s: %s", ev["id"][:8], exc)
        log.info("%d event pictures analysed so far", done)
        stop.wait(0.5)


if __name__ == "__main__":
    main()
