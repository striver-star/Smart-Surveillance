"""Face detection, quality checks and watchlist matching (task 18, Section 5.10).

Models: OpenCV Zoo YuNet (detection, MIT) and SFace (128-d embeddings, Apache 2.0), run by
OpenCV's DNN module. Privacy by design:

  - Watchlist only. A face is compared with the enrolled people and nothing else. There is no
    open-ended "who is this" search.
  - Unmatched faces are discarded. Only counts and quality figures are kept.
  - A match is a lead for an operator to confirm, never proof. Every match carries its score and
    the margin to the next-best person.
  - Every enrolled person must have a consent or authority reference (person.json).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger(__name__)

# SFace cosine similarity: OpenCV's published threshold for "same person" is 0.363. We start
# stricter for the trial; tune it on the site's own walk-test results (true and false match rates).
DEFAULT_MATCH = 0.40
DEFAULT_MARGIN = 0.06       # best minus second-best person; a near tie is not a match


@dataclass
class Face:
    box: tuple[int, int, int, int]          # x, y, w, h in image pixels
    landmarks: np.ndarray                   # 5 x 2: right eye, left eye, nose, right and left mouth corners
    score: float
    raw: np.ndarray                         # YuNet row (needed for alignment)
    quality_ok: bool = False
    quality: dict = field(default_factory=dict)


@dataclass
class Match:
    person_id: str
    name: str
    list_name: str                          # e.g. "blocked", "vip", "staff"
    score: float
    margin: float


@dataclass
class QualityRules:
    min_eye_px: float = 28.0                # distance between the eyes; below this recognition is unreliable
    max_yaw: float = 0.45                   # nose offset from the eye midpoint (tilt removed), as a share of eye distance; 0.45 is about a 30-degree turn
    min_sharpness: float = 40.0             # variance of the Laplacian on the face crop
    min_score: float = 0.80                 # detector confidence


class FaceEngine:
    def __init__(self, detector_path: str, recognizer_path: str, *, score_threshold: float = 0.7,
                 rules: QualityRules | None = None):
        self.detector = cv2.FaceDetectorYN.create(detector_path, "", (320, 320), score_threshold, 0.3, 5000)
        self.recognizer = cv2.FaceRecognizerSF.create(recognizer_path, "")
        self.rules = rules or QualityRules()

    def detect(self, image: np.ndarray) -> list[Face]:
        h, w = image.shape[:2]
        self.detector.setInputSize((w, h))
        _, rows = self.detector.detect(image)
        faces = []
        for row in rows if rows is not None else []:
            x, y, bw, bh = (int(round(v)) for v in row[:4])
            faces.append(Face((x, y, bw, bh), row[4:14].reshape(5, 2).astype(np.float32), float(row[14]), row))
        for f in faces:
            self.check_quality(image, f)
        return faces

    def check_quality(self, image: np.ndarray, face: Face) -> None:
        r = self.rules
        right_eye, left_eye, nose = face.landmarks[0], face.landmarks[1], face.landmarks[2]
        eye_vec = left_eye - right_eye
        eye_dist = float(np.linalg.norm(eye_vec))
        mid = (left_eye + right_eye) / 2
        # Remove head tilt (roll) first, so only turning (yaw) moves the nose sideways.
        ang = -np.arctan2(eye_vec[1], eye_vec[0])
        dx, dy = nose - mid
        nose_x = dx * np.cos(ang) - dy * np.sin(ang)
        yaw = float(abs(nose_x) / eye_dist) if eye_dist else 1.0
        x, y, bw, bh = face.box
        crop = image[max(y, 0):max(y + bh, 0), max(x, 0):max(x + bw, 0)]
        sharp = float(cv2.Laplacian(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()) if crop.size else 0.0
        face.quality = {"eye_px": round(eye_dist, 1), "yaw": round(yaw, 2), "sharpness": round(sharp, 1),
                        "score": round(face.score, 2)}
        problems = []
        if eye_dist < r.min_eye_px:
            problems.append("too small")
        if yaw > r.max_yaw:
            problems.append("turned away")
        if sharp < r.min_sharpness:
            problems.append("blurred")
        if face.score < r.min_score:
            problems.append("low detector confidence")
        face.quality["problems"] = problems
        face.quality_ok = not problems

    def embed(self, image: np.ndarray, face: Face) -> np.ndarray:
        aligned = self.recognizer.alignCrop(image, face.raw)
        vec = self.recognizer.feature(aligned).flatten().astype(np.float32)
        return vec / (np.linalg.norm(vec) or 1.0)


@dataclass
class Person:
    person_id: str
    name: str
    list_name: str
    consent_ref: str
    embeddings: np.ndarray                  # n x 128, unit length


class Watchlist:
    """Enrolled people, from a folder:

        watchlist/faces/<person_id>/person.json   {"name": ..., "list": "blocked|vip|staff", "consent_ref": ...}
        watchlist/faces/<person_id>/*.jpg         2 to 5 clear photos, one face each

    Embeddings are computed at load; the photos stay where they are. Keep this folder out of git.
    """

    def __init__(self, people: list[Person], match_threshold: float = DEFAULT_MATCH, margin: float = DEFAULT_MARGIN):
        self.people, self.match_threshold, self.margin = people, match_threshold, margin

    @classmethod
    def load(cls, folder: str | Path, engine: FaceEngine, **kw) -> tuple["Watchlist", list[str]]:
        people, problems = [], []
        root = Path(folder) / "faces"
        for d in sorted(p for p in root.iterdir() if p.is_dir()) if root.exists() else []:
            meta_file = d / "person.json"
            if not meta_file.exists():
                problems.append(f"{d.name}: no person.json, skipped")
                continue
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            if not str(meta.get("consent_ref", "")).strip():
                problems.append(f"{d.name}: no consent_ref (consent or legal authority reference), skipped")
                continue
            vecs = []
            for img_path in sorted(d.glob("*.jp*g")) + sorted(d.glob("*.png")):
                img = cv2.imread(str(img_path))
                if img is None:
                    problems.append(f"{d.name}/{img_path.name}: can't read")
                    continue
                faces = engine.detect(img)
                good = [f for f in faces if f.quality_ok]
                if len(faces) != 1 or not good:
                    why = "no face" if not faces else f"{len(faces)} faces" if len(faces) > 1 else ", ".join(faces[0].quality["problems"])
                    problems.append(f"{d.name}/{img_path.name}: not used ({why})")
                    continue
                vecs.append(engine.embed(img, good[0]))
            if not vecs:
                problems.append(f"{d.name}: no usable photo, skipped")
                continue
            people.append(Person(d.name, meta.get("name", d.name), meta.get("list", "watch"),
                                 str(meta["consent_ref"]), np.stack(vecs)))
        return cls(people, **kw), problems

    def match(self, embedding: np.ndarray) -> tuple[Match | None, float]:
        """(match or None, best score). The best score is kept even without a match, for tuning."""
        if not self.people:
            return None, 0.0
        scores = sorted(((float(np.max(p.embeddings @ embedding)), p) for p in self.people),
                        key=lambda t: t[0], reverse=True)
        best, person = scores[0]
        second = scores[1][0] if len(scores) > 1 else 0.0          # unrelated faces score about 0
        if best >= self.match_threshold and best - second >= self.margin:
            return Match(person.person_id, person.name, person.list_name, round(best, 3), round(best - second, 3)), best
        return None, best
