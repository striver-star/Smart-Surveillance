"""Face and plate recognition trial on one camera or clip (task 18).

    python -m worker.recognition_trial --source rtsp://gateway:8554/nvr4-ch22 --name "Main gate" --minutes 30

What it measures:
  Faces   how many faces the camera sees, how many are good enough to recognise (size, turn, blur),
          and watchlist matches for an operator to confirm. Answers "is this camera suitable?".
  Plates  plate reads on vehicles (or in a fixed entrance region), how many follow the Nigerian
          format, and allow/block list hits.

Privacy: no face images are kept unless --save-matches is given, and then only of watchlist
matches. Unmatched faces are counted, never stored. Run it only where the legal gate for the
trial allows (see docs/task-18-face-plate.md).

Output in --out: trial.csv (one row per face or plate seen) and trial-summary.md.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import statistics
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import cv2

from .face import FaceEngine, Watchlist
from .plate import PlateList, PlateReader

log = logging.getLogger("trial")

FIELDS = ["time", "kind", "detail", "eye_px", "yaw", "sharpness", "quality", "decision", "best_score",
          "person_or_plate", "list", "margin_or_confidence"]


def parse_roi(text: str | None):
    if not text:
        return None
    x1, y1, x2, y2 = (float(v) for v in text.split(","))
    return x1, y1, x2, y2


def crop_roi(image, roi):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi
    return image[int(y1 * h):int(y2 * h), int(x1 * w):int(x2 * w)]


def run(args) -> int:
    if not os.path.exists(args.source) and not args.approval:
        log.error("This is the full recognition trial (stages 2 and 3: face templates and plate reading). "
                  "On a live camera it needs --approval with the legal approval reference for that stage. "
                  "For stage 1 (camera suitability, no identification) use: python -m worker.suitability")
        return 3
    models = Path(args.models)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    evidence = out / "matches"
    face_engine = watchlist = plate_reader = plate_list = vehicle_detector = None
    notes = []
    if not args.no_faces:
        face_engine = FaceEngine(str(models / "face_detection_yunet_2023mar.onnx"),
                                 str(models / "face_recognition_sface_2021dec.onnx"))
        watchlist, problems = Watchlist.load(args.watchlist, face_engine, match_threshold=args.match_threshold)
        notes += problems
        log.info("watchlist: %d people enrolled", len(watchlist.people))
    if not args.no_plates:
        plate_reader = PlateReader(str(models / "ch_PP-OCRv4_det_infer.onnx"), str(models / "ch_PP-OCRv4_rec_infer.onnx"))
        plate_list = PlateList.load(Path(args.watchlist) / "plates.csv")
        if not args.plate_roi:
            from .detector import Detector
            vehicle_detector = Detector(str(models / args.vehicle_model))

    cap = cv2.VideoCapture(args.source, cv2.CAP_FFMPEG)
    if not cap.isOpened():
        log.error("can't open %s", args.source)
        return 2
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    is_file = os.path.exists(args.source)
    every = max(1, round(src_fps / args.fps)) if is_file else 1
    deadline = time.monotonic() + args.minutes * 60
    roi = parse_roi(args.plate_roi)

    stats = Counter()
    eye_sizes, nonmatch_best, timings = [], [], {"faces": [], "plates": []}
    face_reasons = Counter()
    matches, plate_reads = [], {}
    last_seen: dict[str, float] = {}
    frame_no = 0
    with (out / "trial.csv").open("w", newline="", encoding="utf-8") as fcsv:
        w = csv.DictWriter(fcsv, fieldnames=FIELDS)
        w.writeheader()
        last_t = 0.0
        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if not ok:
                break
            frame_no += 1
            if is_file and frame_no % every:
                continue
            now = time.monotonic()
            if not is_file and now - last_t < 1.0 / args.fps:
                continue
            last_t = now
            stats["frames"] += 1
            stamp = (f"{frame_no / src_fps:.1f}s" if is_file else datetime.now().strftime("%H:%M:%S"))

            if face_engine:
                t = time.perf_counter()
                faces = face_engine.detect(frame)
                for f in faces:
                    stats["faces"] += 1
                    eye_sizes.append(f.quality["eye_px"])
                    for p in f.quality["problems"]:
                        face_reasons[p] += 1
                    row = {"time": stamp, "kind": "face", "eye_px": f.quality["eye_px"], "yaw": f.quality["yaw"],
                           "sharpness": f.quality["sharpness"],
                           "quality": "ok" if f.quality_ok else "; ".join(f.quality["problems"])}
                    if not f.quality_ok:
                        w.writerow({**row, "decision": "not usable"})
                        continue
                    stats["faces_usable"] += 1
                    match, best = watchlist.match(face_engine.embed(frame, f)) if watchlist else (None, 0.0)
                    if match is None:
                        nonmatch_best.append(best)
                        w.writerow({**row, "decision": "no match (discarded)", "best_score": round(best, 3)})
                        continue
                    key = f"face:{match.person_id}"
                    repeat = now - last_seen.get(key, -1e9) < args.dedupe_s
                    last_seen[key] = now
                    w.writerow({**row, "decision": "repeat" if repeat else "MATCH", "best_score": match.score,
                                "person_or_plate": match.name, "list": match.list_name, "margin_or_confidence": match.margin})
                    if not repeat:
                        stats["face_matches"] += 1
                        matches.append((stamp, match))
                        if args.save_matches:
                            evidence.mkdir(exist_ok=True)
                            x, y, bw, bh = f.box
                            pad = int(0.4 * max(bw, bh))
                            crop = frame[max(0, y - pad):y + bh + pad, max(0, x - pad):x + bw + pad]
                            cv2.imwrite(str(evidence / f"{stamp.replace(':', '')}-{match.person_id}.jpg"), crop)
                timings["faces"].append((time.perf_counter() - t) * 1000)

            if plate_reader:
                t = time.perf_counter()
                regions = []
                if roi:
                    regions.append(("entrance region", crop_roi(frame, roi)))
                elif vehicle_detector:
                    for d in vehicle_detector.detect(frame):
                        if d.object_class != "vehicle" or d.confidence < 0.5:
                            continue
                        x1, y1, x2, y2 = (int(v) for v in d.box)
                        if (x2 - x1) < args.min_vehicle_px:
                            continue
                        regions.append(("vehicle", frame[max(0, y1):y2, max(0, x1):x2]))
                for detail, img in regions:
                    if img.size == 0:
                        continue
                    stats["plate_regions"] += 1
                    for r in plate_reader.read_plates(img)[:1]:
                        hit = plate_list.lookup(r.plate) if plate_list else None
                        key = f"plate:{r.plate}"
                        repeat = now - last_seen.get(key, -1e9) < args.dedupe_s
                        last_seen[key] = now
                        w.writerow({"time": stamp, "kind": "plate", "detail": detail,
                                    "quality": "standard format" if r.standard else "non-standard",
                                    "decision": ("repeat" if repeat else (f"LIST {hit[0].upper()}" if hit else "read")),
                                    "person_or_plate": r.display, "list": hit[0] if hit else "",
                                    "margin_or_confidence": r.confidence})
                        if not repeat:
                            stats["plates"] += 1
                            stats["plates_standard"] += r.standard
                            plate_reads.setdefault(r.plate, [stamp, r.display, r.confidence, hit])
                            if hit:
                                stats[f"plates_{hit[0]}"] += 1
                timings["plates"].append((time.perf_counter() - t) * 1000)
    cap.release()
    (out / "trial-summary.md").write_text(summary(args, stats, eye_sizes, face_reasons, nonmatch_best, matches,
                                                  plate_reads, timings, notes, watchlist), encoding="utf-8")
    log.info("wrote %s", out / "trial-summary.md")
    return 0


def pct(n, d):
    return f"{100 * n / d:.0f}%" if d else "-"


def summary(args, stats, eye_sizes, reasons, nonmatch_best, matches, plates, timings, notes, watchlist) -> str:
    q = statistics.quantiles(eye_sizes, n=10) if len(eye_sizes) >= 10 else None
    lines = [f"# Recognition trial: {args.name}", "",
             *( [f"Approval reference: {args.approval}", ""] if args.approval else [] ),
             f"{datetime.now():%Y-%m-%d %H:%M}, source `{args.source}`, {stats['frames']} frames analysed "
             f"at up to {args.fps} per second.", ""]
    if not args.no_faces:
        usable = stats["faces_usable"]
        suitable = stats["faces"] >= 20 and usable / max(stats["faces"], 1) >= 0.3 and q and q[4] >= 28
        lines += ["## Faces", "",
                  f"- Faces seen: {stats['faces']}; good enough to recognise: {usable} ({pct(usable, stats['faces'])})",
                  "- Not usable because: " + (", ".join(f"{k} {v}" for k, v in reasons.most_common()) or "-"),
                  ("- Eye distance in pixels (10th, 50th, 90th percentile): "
                   f"{q[0]:.0f}, {q[4]:.0f}, {q[8]:.0f} (recognition needs about 28 or more)" if q else
                   "- Too few faces to judge face size"),
                  f"- **Camera suitable for face recognition: {'yes' if suitable else 'no' if stats['faces'] >= 20 else 'not enough faces seen'}**",
                  f"- Watchlist: {len(watchlist.people) if watchlist else 0} people; matches: {stats['face_matches']}",
                  ""]
        if nonmatch_best:
            top = sorted(nonmatch_best, reverse=True)[:5]
            lines += [f"Highest scores among people who did not match (threshold {args.match_threshold}): "
                      + ", ".join(f"{s:.2f}" for s in top) + ". If these come close to the threshold, "
                      "raise it to avoid false matches.", ""]
        if matches:
            lines += ["Matches to confirm (a match is a lead, not proof):", "",
                      "| Time | Person | List | Score | Margin to next |", "| --- | --- | --- | --- | --- |"]
            lines += [f"| {t} | {m.name} | {m.list_name} | {m.score} | {m.margin} |" for t, m in matches] + [""]
    if not args.no_plates:
        lines += ["## Plates", "",
                  f"- Regions checked ({'entrance region' if args.plate_roi else 'vehicles'}): {stats['plate_regions']}",
                  f"- Plates read: {stats['plates']}; in the standard Nigerian format: {stats['plates_standard']} "
                  f"({pct(stats['plates_standard'], stats['plates'])})",
                  f"- List hits: allow {stats['plates_allow']}, block {stats['plates_block']}", ""]
        if plates:
            lines += ["| First seen | Plate | Confidence | List |", "| --- | --- | --- | --- |"]
            lines += [f"| {v[0]} | {v[1]} | {v[2]} | {v[3][0] if v[3] else ''} |" for v in list(plates.values())[:200]]
            lines += ["", "Check each read against the real plate (from the recording) to get the read accuracy.", ""]
    lines += ["## Processing time per analysed frame (CPU unless a GPU is configured)", ""]
    for k, v in timings.items():
        if v:
            lines.append(f"- {k}: median {statistics.median(v):.0f} ms, slowest {max(v):.0f} ms")
    if notes:
        lines += ["", "## Watchlist notes", ""] + [f"- {n}" for n in notes]
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--source", required=True, help="RTSP URL or video file")
    p.add_argument("--name", default="camera", help="camera name for the report")
    p.add_argument("--minutes", type=float, default=30)
    p.add_argument("--fps", type=float, default=4, help="frames analysed per second")
    p.add_argument("--models", default=os.environ.get("HSS_MODELS_DIR", "/models"))
    p.add_argument("--watchlist", default="/config/watchlist")
    p.add_argument("--match-threshold", type=float, default=0.40)
    p.add_argument("--plate-roi", help="x1,y1,x2,y2 as fractions of the frame (entrance lane); default: find vehicles")
    p.add_argument("--vehicle-model", default="yolox_s.onnx")
    p.add_argument("--min-vehicle-px", type=int, default=120, help="ignore vehicles narrower than this")
    p.add_argument("--dedupe-s", type=float, default=30, help="count the same person or plate once in this window")
    p.add_argument("--no-faces", action="store_true")
    p.add_argument("--no-plates", action="store_true")
    p.add_argument("--save-matches", action="store_true", help="save a crop of each watchlist match (evidence)")
    p.add_argument("--approval", default="", help="legal approval reference for this trial stage (needed for live cameras)")
    p.add_argument("--out", default="/data/trial")
    return run(p.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
