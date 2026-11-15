"""Plate suitability: can a camera's picture be used for number plate reading? (no plates are read)

For each camera it watches the main stream and, on vehicles (or in a fixed lane region), finds the plate's
line of characters with the text detector only. It measures, for every plate sighting:

- size: the plate's width in pixels (reading needs about 130 px or more), and its characters' height;
- sharpness: motion blur from a slow shutter (the most common failure on general cameras);
- glare: a white-washed plate, typical of infrared at night on reflective plates;
- contrast: characters that stand out from the plate.

Nothing is read or kept: the reading model is not loaded, and no images are written. It is the same
kind of check as the face suitability test and is not identification.

  python -m worker.plate_suitability --camera "Main gate entrance=10.1.3.4:22" --minutes 30
  python -m worker.plate_suitability --camera "Gate lane=10.1.3.4:23" --roi 0.2,0.45,0.8,0.95
Output: plate-suitability.md and .csv in --out. Run in daylight and again at night.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from .plate import TextDetector, warp_box
from .suitability import camera_url, run_source, stream_text

log = logging.getLogger("plate-suitability")
MIN_PLATE_PX, MIN_SHARP, MAX_GLARE, MIN_CONTRAST = 130, 0.8, 0.25, 28.0
MIN_SIGHTINGS = 5
PLATE_PER_LINE = 1.35        # a Nigerian plate is about this much wider than its main line of characters


def characters(g: np.ndarray) -> tuple[float, float]:
    """(character height, width of the line of characters) in pixels, from the dark characters themselves:
    the text detector's box carries a margin that is large for small text, so its size would mislead."""
    h, w = g.shape[:2]
    _, bw = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, _, stats, _ = cv2.connectedComponentsWithStats(bw, 8)
    chars = [s for s in stats[1:] if s[3] >= 0.25 * h and s[3] <= 0.98 * h and s[2] <= 1.2 * s[3] and s[4] >= 6
             and s[1] > 0 and s[1] + s[3] < h]           # character-shaped, not touching the box edge
    if len(chars) < 3:
        return h * 0.5, w / PLATE_PER_LINE * 0.9          # too few to measure: a cautious guess from the box
    heights = sorted(int(s[3]) for s in chars)
    x1 = min(int(s[0]) for s in chars)
    x2 = max(int(s[0] + s[2]) for s in chars)
    return float(heights[len(heights) // 2]), float(x2 - x1)


def measure(crop: np.ndarray) -> dict:
    """Size, sharpness, glare and contrast of one plate line (pure, tested)."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    h, w = g.shape[:2]
    char_px, line_w = characters(g)
    # Blur: how steep the characters' upright edges are (95th percentile of the horizontal gradient) relative to
    # the plate's light-to-dark range, on the crop scaled to a fixed height so plate size doesn't count. Sharp
    # plates score about 2; a vehicle moving across the view smears these edges first (0.5 or less).
    n = cv2.resize(g, (max(8, int(w * 48 / max(h, 1))), 48), interpolation=cv2.INTER_AREA).astype(np.float64)
    span = max(float(np.percentile(n, 95) - np.percentile(n, 5)), 1.0)
    sharp = float(np.percentile(np.abs(cv2.Sobel(n, cv2.CV_64F, 1, 0, ksize=3)), 95)) / span
    glare = float((g >= 250).mean())
    contrast = float(g.std())
    plate_px = line_w * PLATE_PER_LINE
    problems = []
    if plate_px < MIN_PLATE_PX:
        problems.append("too small")
    if sharp < MIN_SHARP:
        problems.append("blurred")
    if glare > MAX_GLARE:
        problems.append("glare")
    if contrast < MIN_CONTRAST:
        problems.append("low contrast")
    return {"char_px": round(char_px, 1), "plate_px": round(plate_px), "sharp": round(sharp, 2),
            "glare": round(glare, 3), "contrast": round(contrast, 1), "problems": problems}


def plate_lines(boxes: list[np.ndarray], region_h: int) -> list[np.ndarray]:
    """Text boxes shaped like a plate's main line, in the lower part of a vehicle (pure, tested)."""
    out = []
    for b in boxes:
        w = float(np.linalg.norm(b[1] - b[0]))
        h = float(np.linalg.norm(b[3] - b[0]))
        if h < 4 or not 2.0 <= w / h <= 9.0:
            continue
        if b[:, 1].mean() < region_h * 0.35:          # plates sit low on a vehicle, not on its roof sign
            continue
        out.append(b)
    return out


def verdict(sightings: int, usable: int, vehicles: int | None, reasons: Counter, brightness: float | None) -> tuple[str, str]:
    if sightings < MIN_SIGHTINGS:
        if vehicles is not None and vehicles >= MIN_SIGHTINGS:
            return "not suitable", "vehicles pass but no plate is found: plates too small, blurred or out of view; aim a narrower view at the lane, or use an ANPR camera"
        if brightness is not None and brightness < 40:
            return "not enough vehicles", "picture very dark: plates need light (IR or white light aimed at the lane)"
        return "not enough vehicles", "too few vehicles passed: run longer or at a busier time"
    share = usable / sightings
    if share >= 0.3:
        return "suitable", "plates are big, sharp and clear often enough"
    top = reasons.most_common(1)[0][0] if reasons else ""
    return "not suitable", {
        "too small": "plates too small: a narrower lens or zoom on one lane, or a camera closer to the barrier",
        "blurred": "plates blurred: a faster shutter (1/1000 s or faster) or a place where vehicles stop; a dedicated ANPR camera does both",
        "glare": "plates washed out: infrared on reflective plates; an ANPR camera (plate exposure) or lower IR and white light",
        "low contrast": "plates unclear: better light on the lane, or reduce the distance",
    }.get(top, "plates rarely usable")


class PlateTally:
    def __init__(self, text: TextDetector, vehicles=None, roi: tuple[float, float, float, float] | None = None):
        self.text, self.vehicles, self.roi = text, vehicles, roi
        self.frames = self.sightings = self.usable = 0
        self.vehicle_frames = 0
        self.char, self.plate_w, self.bright = [], [], []
        self.reasons: Counter = Counter()
        self.resolution = ""

    def regions(self, frame: np.ndarray) -> list[np.ndarray]:
        h, w = frame.shape[:2]
        if self.roi:
            x1, y1, x2, y2 = self.roi
            return [frame[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]]
        found = [d for d in self.vehicles.detect(frame) if d.object_class == "vehicle" and d.confidence >= 0.4]
        if found:
            self.vehicle_frames += 1
        return [frame[max(0, int(d.box[1])):int(d.box[3]), max(0, int(d.box[0])):int(d.box[2])] for d in found
                if d.box[2] - d.box[0] >= 60]

    def add(self, frame: np.ndarray) -> None:
        self.frames += 1
        self.resolution = f"{frame.shape[1]}x{frame.shape[0]}"
        if self.frames % 10 == 1:
            self.bright.append(float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))))
        for region in self.regions(frame):
            if region.size == 0:
                continue
            lines = plate_lines(self.text.detect_text(region), region.shape[0])
            if not lines:
                continue
            best = max(lines, key=lambda b: float(np.linalg.norm(b[1] - b[0])))
            m = measure(warp_box(region, best))         # measured, then dropped: never read, never saved
            self.sightings += 1
            self.char.append(m["char_px"])
            self.plate_w.append(m["plate_px"])
            if m["problems"]:
                for p in m["problems"]:
                    self.reasons[p] += 1
            else:
                self.usable += 1

    def result(self) -> dict:
        q = statistics.quantiles(self.char, n=10) if len(self.char) >= 10 else None
        brightness = statistics.mean(self.bright) if self.bright else None
        v, advice = verdict(self.sightings, self.usable, self.vehicle_frames if self.vehicles is not None else None,
                            self.reasons, brightness)
        return {"frames": self.frames, "resolution": self.resolution,
                "vehicle_frames": self.vehicle_frames if self.vehicles is not None else None,
                "sightings": self.sightings, "usable": self.usable,
                "usable_pct": round(100 * self.usable / self.sightings) if self.sightings else 0,
                "char_p10": round(q[0]) if q else None, "char_median": round(statistics.median(self.char)) if self.char else None,
                "plate_median": round(statistics.median(self.plate_w)) if self.plate_w else None,
                "reasons": dict(self.reasons.most_common()), "brightness": round(brightness) if brightness is not None else None,
                "verdict": v, "advice": advice}


def report(rows: list[dict], minutes: float) -> str:
    out = ["# Number plate suitability", "",
           f"{datetime.now():%Y-%m-%d %H:%M}. Each camera's main stream watched for up to {minutes:g} minutes. Plates were found "
           "and measured, then forgotten: no plate was read, nothing was kept. Counts are sightings (one vehicle is seen in "
           "several frames).", "",
           f"Usable means a plate at least {MIN_PLATE_PX} px wide, sharp, not washed out by glare, "
           "with clear contrast. A camera is suitable when at least 30% of sightings are usable.", "",
           "| Camera | Resolution | Vehicles in view | Plate sightings | Usable | Character height px (10th, median) | Plate width px (median) | Brightness | Stream | Verdict | Advice |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        st = stream_text(r)
        if r.get("error"):
            out.append(f"| {r['name']} | {r.get('resolution') or '-'} | - | {r.get('sightings', '-')} | - | - | - | - | {st} | error | {r['error']} |")
            continue
        veh = "-" if r.get("vehicle_frames") is None else f"{r['vehicle_frames']} frames"
        ch = f"{r['char_p10']}, {r['char_median']}" if r["char_p10"] is not None else (str(r["char_median"]) if r["char_median"] else "-")
        out.append(f"| {r['name']} | {r['resolution']} | {veh} | {r['sightings']} | {r['usable']} ({r['usable_pct']}%) | {ch} | "
                   f"{r['plate_median'] or '-'} | {r['brightness']} | {st} | **{r['verdict']}** | {r['advice']} |")
    out += ["", "Why plates were not usable:", ""]
    for r in rows:
        if not r.get("error") and r["reasons"]:
            out.append(f"- {r['name']}: " + ", ".join(f"{k} {v}" for k, v in r["reasons"].items()))
    out += ["", "Run once in daylight and once at night: infrared glare on reflective plates is the usual night failure.",
            "A dedicated ANPR camera (fast shutter, plate exposure, one lane) fixes size, blur and glare together.", ""]
    return "\n".join(out)


def parse_roi(text: str | None):
    if not text:
        return None
    x1, y1, x2, y2 = (float(v) for v in text.split(","))
    if not (0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1):
        raise SystemExit("--roi is x1,y1,x2,y2 as fractions of the frame, e.g. 0.2,0.45,0.8,0.95")
    return x1, y1, x2, y2


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(description="Which cameras suit number plate reading (no plates are read).")
    p.add_argument("--camera", action="append", default=[], help='"Name=NVR_IP:CHANNEL" or "Name=URL", repeatable')
    p.add_argument("--minutes", type=float, default=30, help="minutes per camera")
    p.add_argument("--fps", type=float, default=2, help="frames analysed per second")
    p.add_argument("--roi", help="fixed lane region x1,y1,x2,y2 (fractions); default: look on detected vehicles")
    p.add_argument("--models", default=os.environ.get("HSS_MODELS_DIR", "/models"))
    p.add_argument("--vehicle-model", default="yolox_s.onnx")
    p.add_argument("--out", default="/data/trial/plate-suitability")
    args = p.parse_args(argv)
    if not args.camera:
        p.error("give at least one --camera")
    roi = parse_roi(args.roi)
    text = TextDetector(str(Path(args.models) / "ch_PP-OCRv4_det_infer.onnx"))
    vehicles = None
    if not roi:
        from .detector import Detector
        vehicles = Detector(str(Path(args.models) / args.vehicle_model))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in args.camera:
        name, url, shown = camera_url(spec)
        log.info("watching %s (%s) for %g minutes", name, shown, args.minutes)
        r = {"name": name, "source": shown, **run_source(PlateTally(text, vehicles, roi), url, args.minutes, args.fps)}
        log.info("  %s", r.get("error") or f"{r['sightings']} plate sightings, {r['usable']} usable: {r['verdict']}")
        rows.append(r)
        (out / "plate-suitability.md").write_text(report(rows, args.minutes), encoding="utf-8")
    fields = ["name", "source", "resolution", "frames", "vehicle_frames", "sightings", "usable", "usable_pct", "char_p10",
              "char_median", "plate_median", "brightness", "reconnects", "lost_s", "verdict", "advice", "error"]
    with (out / "plate-suitability.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s", out / "plate-suitability.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
