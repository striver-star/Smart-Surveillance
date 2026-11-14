"""Number plate reading with PaddleOCR PP-OCRv4 models on ONNX Runtime (task 18, Section 5.10).

Pipeline: text detection (DB) on a vehicle crop or a fixed entrance region -> recognition (SVTR,
CTC) of each text line -> clean-up to the Nigerian plate format -> allow/block list lookup.

Models: ch_PP-OCRv4_det_infer.onnx and ch_PP-OCRv4_rec_infer.onnx (Apache 2.0, from the
RapidOCR wheel on PyPI; see tools/fetch-models.sh). The recognition model carries its own
character list in its metadata. Only OpenCV and NumPy are needed for the pre- and post-processing.

Nigerian plates since 2011: three letters (local government code), three digits, two letters,
for example "KJA 123 AB". Older or special plates are reported but flagged as non-standard.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .detector import choose_providers

PLATE_NG = re.compile(r"^[A-Z]{3}\d{3}[A-Z]{2}$")
TO_LETTER = {"0": "O", "1": "I", "2": "Z", "4": "A", "5": "S", "6": "G", "8": "B"}
TO_DIGIT = {"O": "0", "D": "0", "Q": "0", "U": "0", "I": "1", "L": "1", "T": "1", "Z": "2", "A": "4",
            "S": "5", "G": "6", "B": "8"}
NOISE_WORDS = ("FEDERAL", "REPUBLIC", "NIGERIA", "EXCELLENCE", "STATE", "CENTRE", "CENTER", "HOME", "OF")


@dataclass
class TextLine:
    box: np.ndarray              # 4 x 2 corner points
    text: str
    confidence: float


@dataclass
class PlateRead:
    plate: str                   # normalised, e.g. KJA123AB
    display: str                 # e.g. KJA 123 AB
    raw: str
    confidence: float
    standard: bool               # matches the current Nigerian format
    box: np.ndarray


def normalise_plate(raw: str) -> tuple[str, bool]:
    """Upper-case, keep letters and digits, and fix common OCR confusions by position."""
    s = re.sub(r"[^A-Z0-9]", "", raw.upper())
    if len(s) == 8:
        fixed = "".join(TO_LETTER.get(c, c) if i in (0, 1, 2, 6, 7) else TO_DIGIT.get(c, c) for i, c in enumerate(s))
        if PLATE_NG.match(fixed):
            return fixed, True
    return s, bool(PLATE_NG.match(s))


def display(plate: str) -> str:
    return f"{plate[:3]} {plate[3:6]} {plate[6:]}" if PLATE_NG.match(plate) else plate


class PlateReader:
    def __init__(self, det_path: str, rec_path: str, providers: list[str] | None = None):
        import onnxruntime as ort
        prov = choose_providers(providers)
        self.det = ort.InferenceSession(det_path, providers=prov)
        self.rec = ort.InferenceSession(rec_path, providers=prov)
        chars = self.rec.get_modelmeta().custom_metadata_map.get("character", "").splitlines()
        self.charset = ["<blank>"] + chars + [" "]

    # ------------------------------------------------------------- detection (DB)

    def detect_text(self, image: np.ndarray, max_side: int = 960, thresh: float = 0.3,
                    box_thresh: float = 0.5, unclip: float = 1.6) -> list[np.ndarray]:
        h, w = image.shape[:2]
        scale = min(1.0, max_side / max(h, w))
        nh, nw = max(32, int(round(h * scale / 32)) * 32), max(32, int(round(w * scale / 32)) * 32)
        x = cv2.resize(image, (nw, nh)).astype(np.float32) / 255.0
        x = (x - np.array([0.485, 0.456, 0.406], np.float32)) / np.array([0.229, 0.224, 0.225], np.float32)
        prob = self.det.run(None, {self.det.get_inputs()[0].name: x.transpose(2, 0, 1)[None]})[0][0, 0]
        mask = (prob > thresh).astype(np.uint8)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        for c in contours:
            if len(c) < 4:
                continue
            (cx, cy), (bw, bh), ang = cv2.minAreaRect(c)
            if min(bw, bh) < 3:
                continue
            m = np.zeros_like(mask)
            cv2.drawContours(m, [c], -1, 1, -1)
            if float(prob[m.astype(bool)].mean()) < box_thresh:
                continue
            d = bw * bh * unclip / (2 * (bw + bh))           # DB "unclip": grow the shrunk text kernel
            pts = cv2.boxPoints(((cx, cy), (bw + 2 * d, bh + 2 * d), ang))
            pts[:, 0] *= w / nw
            pts[:, 1] *= h / nh
            boxes.append(order_points(np.clip(pts, 0, [w - 1, h - 1])))
        return boxes

    # ------------------------------------------------------------- recognition (CTC)

    def recognize(self, crop: np.ndarray) -> tuple[str, float]:
        h, w = crop.shape[:2]
        tw = int(min(320, max(16, np.ceil(48 * w / max(h, 1)))))
        x = cv2.resize(crop, (tw, 48)).astype(np.float32) / 255.0
        x = (x - 0.5) / 0.5
        padded = np.zeros((48, max(tw, 320), 3), np.float32)
        padded[:, :tw] = x
        out = self.rec.run(None, {self.rec.get_inputs()[0].name: padded.transpose(2, 0, 1)[None]})[0][0]
        idx, probs = out.argmax(1), out.max(1)
        text, confs, prev = [], [], -1
        for i, p in zip(idx, probs):
            if i != prev and i != 0 and i < len(self.charset):
                text.append(self.charset[i])
                confs.append(float(p))
            prev = i
        return "".join(text), float(np.mean(confs)) if confs else 0.0

    def read_lines(self, image: np.ndarray) -> list[TextLine]:
        lines = []
        for box in self.detect_text(image):
            crop = warp_box(image, box)
            if crop.shape[0] > crop.shape[1] * 1.5:
                crop = cv2.rotate(crop, cv2.ROTATE_90_COUNTERCLOCKWISE)
            text, conf = self.recognize(crop)
            if text.strip():
                lines.append(TextLine(box, text, conf))
        return lines

    def read_plates(self, image: np.ndarray, min_confidence: float = 0.6) -> list[PlateRead]:
        """Plates in an image (a vehicle crop or an entrance region), best first."""
        lines = [ln for ln in self.read_lines(image)
                 if not any(w in ln.text.upper() for w in NOISE_WORDS)]
        candidates = [(ln.text, ln.confidence, ln.box) for ln in lines]
        # The recogniser sometimes splits "KJA" "123AB": also try neighbours on the same row joined.
        lines.sort(key=lambda ln: (round(ln.box[:, 1].mean() / max(1.0, np.ptp(ln.box[:, 1]))), ln.box[:, 0].min()))
        for a, b in zip(lines, lines[1:]):
            if abs(a.box[:, 1].mean() - b.box[:, 1].mean()) < 0.5 * np.ptp(a.box[:, 1]):
                candidates.append((a.text + b.text, min(a.confidence, b.confidence), np.vstack([a.box, b.box])))
        reads = []
        for raw, conf, box in candidates:
            plate, standard = normalise_plate(raw)
            if len(plate) < 5 or conf < min_confidence:
                continue
            if not standard and sum(c.isdigit() for c in plate) < 2:
                continue                       # every plate has digits; this is other text
            reads.append(PlateRead(plate, display(plate), raw, round(conf, 3), standard, box))
        reads.sort(key=lambda r: (r.standard, r.confidence), reverse=True)
        seen, unique = set(), []
        for r in reads:
            if r.plate not in seen:
                seen.add(r.plate)
                unique.append(r)
        return unique


def order_points(pts: np.ndarray) -> np.ndarray:
    """Top-left, top-right, bottom-right, bottom-left."""
    s, d = pts.sum(1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], np.float32)


def warp_box(image: np.ndarray, box: np.ndarray) -> np.ndarray:
    w = int(max(np.linalg.norm(box[0] - box[1]), np.linalg.norm(box[2] - box[3])))
    h = int(max(np.linalg.norm(box[0] - box[3]), np.linalg.norm(box[1] - box[2])))
    w, h = max(w, 1), max(h, 1)
    m = cv2.getPerspectiveTransform(box.astype(np.float32), np.float32([[0, 0], [w, 0], [w, h], [0, h]]))
    return cv2.warpPerspective(image, m, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)


class PlateList:
    """Allow and block lists from a CSV file: plate,list,note (list = allow or block)."""

    def __init__(self, entries: dict[str, tuple[str, str]]):
        self.entries = entries

    @classmethod
    def load(cls, path: str | Path) -> "PlateList":
        entries = {}
        p = Path(path)
        if p.exists():
            with p.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    plate, _ = normalise_plate(row.get("plate", ""))
                    if plate:
                        entries[plate] = (row.get("list", "watch").strip().lower(), row.get("note", "").strip())
        return cls(entries)

    def lookup(self, plate: str) -> tuple[str, str] | None:
        return self.entries.get(plate)
