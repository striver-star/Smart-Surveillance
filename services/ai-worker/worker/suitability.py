"""Stage 1 of the face trial: which cameras are suitable for face recognition? (task 18)

    python -m worker.suitability --camera "Main gate entrance=10.1.3.4:22" --camera "Security check 1=10.1.3.4:23" --minutes 30

Each camera's main stream is watched in turn (one at a time, so the network carries one stream).
Faces are found and measured (size, turn, blur, brightness) and then forgotten.

Nobody is identified: no face template (embedding) is computed, no watchlist is used, no plates are
read and no images are saved. Only counts and measurements are written.

--camera takes "Name=NVR_IP:CHANNEL" (main stream through the NVR; login from HSS_NVR_USER and
HSS_NVR_PASSWORD) or "Name=URL_or_file".

Output in --out: suitability.md (all cameras) and suitability.csv (one row per camera).
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

from .face import FaceEngine

log = logging.getLogger("suitability")
MIN_FACES = 20


def camera_url(spec: str) -> tuple[str, str, str]:
    """'Name=10.1.3.4:22' -> (name, rtsp URL with login, URL without login for the report)."""
    name, _, target = spec.partition("=")
    name, target = name.strip(), target.strip()
    if not target:
        raise SystemExit(f"--camera needs Name=NVR_IP:CHANNEL or Name=URL: {spec!r}")
    m = re.fullmatch(r"(\d{1,3}(?:\.\d{1,3}){3}):(\d{1,3})", target)
    if not m:
        return name, target, re.sub(r"//[^@/]*@", "//", target)
    ip, ch = m.group(1), int(m.group(2))
    user = os.environ.get("HSS_NVR_USER", "")
    password = os.environ.get("HSS_NVR_PASSWORD", "")
    if not user:
        raise SystemExit("set HSS_NVR_USER and HSS_NVR_PASSWORD for NVR channels")
    path = f"{ip}:554/Streaming/Channels/{ch}01"
    return name, f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}@{path}", f"rtsp://{path}"


def verdict(n: int, usable: int, median_eye: float | None, reasons: Counter, brightness: float | None,
            people_frames: int | None = None) -> tuple[str, str]:
    """(verdict, advice). people_frames: frames in which the person detector saw someone (None = not checked)."""
    if n < MIN_FACES and people_frames is not None and people_frames >= MIN_FACES:
        return "not suitable", ("people pass but their faces are too small or turned away to detect: "
                                "a narrower view, or a camera facing the walking direction closer to the door")
    if n < MIN_FACES:
        if brightness is not None and brightness < 40:
            return "not enough faces", "picture very dark: try again in daylight, or check the camera's light"
        return "not enough faces", "too few people passed: run longer or at a busier time"
    share = usable / n
    if share >= 0.3 and median_eye is not None and median_eye >= 28:
        return "suitable", "faces are big, front-on and sharp often enough"
    top = reasons.most_common(1)[0][0] if reasons else ""
    advice = {
        "too small": "faces too small: a narrower view, a zoom lens, or a camera closer to the door",
        "turned away": "faces turned away: mount the camera facing the walking direction, at about head height",
        "blurred": "faces blurred: faster shutter, more light, or WDR at bright doorways",
        "low detector confidence": "faces unclear: improve lighting or reduce the distance",
    }.get(top, "faces rarely usable")
    return "not suitable", advice


def watch(engine: FaceEngine, url: str, minutes: float, fps: float, people=None) -> dict:
    cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        return {"error": "could not open the stream"}
    is_file = os.path.exists(url)
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    every = max(1, round(src_fps / fps)) if is_file else 1
    deadline = time.monotonic() + minutes * 60
    n = usable = frames = frame_no = 0
    eyes, reasons, bright, ms = [], Counter(), [], []
    people_frames = people_checks = 0
    resolution = ""
    last = 0.0
    while time.monotonic() < deadline:
        ok, frame = cap.read()
        if not ok:
            if is_file:
                break
            return {"error": "stream stopped", "frames": frames}
        frame_no += 1
        if is_file and frame_no % every:
            continue
        now = time.monotonic()
        if not is_file and now - last < 1.0 / fps:
            continue
        last = now
        frames += 1
        resolution = f"{frame.shape[1]}x{frame.shape[0]}"
        if frames % 10 == 1:
            bright.append(float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))))
        if people is not None and frames % 4 == 1:     # person count, about once a second
            people_checks += 1
            people_frames += any(d.object_class == "human" and d.confidence >= 0.5 for d in people.detect(frame))
        t = time.perf_counter()
        faces = engine.detect(frame)            # measures quality; no embedding is computed
        ms.append((time.perf_counter() - t) * 1000)
        for f in faces:
            n += 1
            eyes.append(f.quality["eye_px"])
            if f.quality_ok:
                usable += 1
            for p in f.quality["problems"]:
                reasons[p] += 1
        del faces, frame
    cap.release()
    q = statistics.quantiles(eyes, n=10) if len(eyes) >= 10 else None
    median_eye = statistics.median(eyes) if eyes else None
    brightness = statistics.mean(bright) if bright else None
    pct_people = round(100 * people_frames / people_checks) if people_checks else None
    # "people passed" means someone was in view in at least 20 of the checks (about 20 seconds in total)
    v, advice = verdict(n, usable, median_eye, reasons, brightness, people_frames if people is not None else None)
    return {"frames": frames, "people_pct": pct_people, "resolution": resolution, "faces": n, "usable": usable,
            "usable_pct": round(100 * usable / n) if n else 0,
            "eye_p10": round(q[0]) if q else None, "eye_median": round(median_eye) if median_eye else None,
            "eye_p90": round(q[8]) if q else None, "reasons": dict(reasons.most_common()),
            "brightness": round(brightness) if brightness is not None else None,
            "ms_median": round(statistics.median(ms)) if ms else None, "verdict": v, "advice": advice}


def report(rows: list[dict], minutes: float) -> str:
    out = ["# Face recognition suitability (stage 1)", "",
           f"{datetime.now():%Y-%m-%d %H:%M}. Each camera's main stream watched for up to {minutes:g} minutes. "
           "Faces were found and measured, then forgotten: nobody was identified, no face templates were "
           "made, no images were kept. Counts are face detections, not people (one person walking past is "
           "seen in several frames).", "",
           "Usable means eyes at least 28 pixels apart, turned less than about 30 degrees, sharp, and a "
           "confident detection. A camera is suitable when at least 30% of faces are usable and the median "
           "eye distance is 28 pixels or more.", "",
           "| Camera | Resolution | People in view | Faces seen | Usable | Eye distance px (10th, median, 90th) | Brightness | Verdict | Advice |",
           "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        if r.get("error"):
            out.append(f"| {r['name']} | - | - | - | - | - | - | error | {r['error']} |")
            continue
        eye = f"{r['eye_p10']}, {r['eye_median']}, {r['eye_p90']}" if r["eye_p10"] is not None else (
            str(r["eye_median"]) if r["eye_median"] else "-")
        fp = "-" if r.get("people_pct") is None else f"{r['people_pct']}% of the time"
        out.append(f"| {r['name']} | {r['resolution']} | {fp} | {r['faces']} | {r['usable']} ({r['usable_pct']}%) | {eye} | "
                   f"{r['brightness']} | **{r['verdict']}** | {r['advice']} |")
    out += ["", "Why faces were not usable:", ""]
    for r in rows:
        if not r.get("error") and r["reasons"]:
            out.append(f"- {r['name']}: " + ", ".join(f"{k} {v}" for k, v in r["reasons"].items()))
    out += ["", "Brightness is the average grey level (0 black, 255 white); under about 40 is too dark for faces.",
            "Run once in daylight and once at night: ColorVu and infrared cameras behave differently after dark.", ""]
    return "\n".join(out)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(description="Stage 1: which cameras suit face recognition (no identification).")
    p.add_argument("--camera", action="append", default=[], help='"Name=NVR_IP:CHANNEL" or "Name=URL", repeatable')
    p.add_argument("--minutes", type=float, default=30, help="minutes per camera")
    p.add_argument("--fps", type=float, default=4, help="frames analysed per second")
    p.add_argument("--models", default=os.environ.get("HSS_MODELS_DIR", "/models"))
    p.add_argument("--person-model", default="yolox_s.onnx",
                   help="person detector in --models, to tell 'nobody passed' from 'faces too small' ('' to skip)")
    p.add_argument("--out", default="/data/trial/suitability")
    args = p.parse_args(argv)
    if not args.camera:
        p.error("give at least one --camera")
    engine = FaceEngine(str(Path(args.models) / "face_detection_yunet_2023mar.onnx"),
                        str(Path(args.models) / "face_recognition_sface_2021dec.onnx"))
    people = None
    if args.person_model and (Path(args.models) / args.person_model).exists():
        from .detector import Detector
        people = Detector(str(Path(args.models) / args.person_model))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for spec in args.camera:
        name, url, shown = camera_url(spec)
        log.info("watching %s (%s) for %g minutes", name, shown, args.minutes)
        r = {"name": name, "source": shown, **watch(engine, url, args.minutes, args.fps, people)}
        log.info("  %s", r.get("error") or f"{r['faces']} faces, {r['usable']} usable: {r['verdict']}")
        rows.append(r)
        (out / "suitability.md").write_text(report(rows, args.minutes), encoding="utf-8")   # partial results survive
    fields = ["name", "source", "resolution", "frames", "people_pct", "faces", "usable", "usable_pct", "eye_p10", "eye_median",
              "eye_p90", "brightness", "ms_median", "verdict", "advice", "error"]
    with (out / "suitability.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log.info("wrote %s", out / "suitability.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
