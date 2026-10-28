"""YOLOX object detector on ONNX Runtime (Apache 2.0 model, MIT runtime).

Runs on TensorRT or CUDA when an NVIDIA GPU is present, on OpenVINO for Intel, otherwise on the CPU.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

import cv2
import numpy as np
import onnxruntime as ort

# COCO class ids that matter for security, mapped to the platform's object classes.
COCO_TO_CLASS = {0: "human", 2: "vehicle", 3: "vehicle", 5: "vehicle", 7: "vehicle"}
DEFAULT_PROVIDERS = ["TensorrtExecutionProvider", "CUDAExecutionProvider",
                     "OpenVINOExecutionProvider", "CPUExecutionProvider"]


@dataclass
class Detection:
    object_class: str
    confidence: float
    box: tuple[float, float, float, float]   # x1, y1, x2, y2 in frame pixels

    def foot_point(self) -> tuple[float, float]:
        """Bottom centre of the box: where a person or vehicle touches the ground."""
        x1, _, x2, y2 = self.box
        return (x1 + x2) / 2, y2


def choose_providers(wanted: list[str] | None = None) -> list[str]:
    available = set(ort.get_available_providers())
    wanted = wanted or [p.strip() for p in os.environ.get("HSS_AI_PROVIDERS", "").split(",") if p.strip()] \
        or DEFAULT_PROVIDERS
    chosen = [p for p in wanted if p in available]
    return chosen or ["CPUExecutionProvider"]


def letterbox(frame: np.ndarray, size: tuple[int, int]) -> tuple[np.ndarray, float]:
    """Resize keeping aspect ratio into a grey canvas, as YOLOX was trained (no mean/std normalisation)."""
    h, w = size
    ratio = min(h / frame.shape[0], w / frame.shape[1])
    resized = cv2.resize(frame, (int(frame.shape[1] * ratio), int(frame.shape[0] * ratio)),
                         interpolation=cv2.INTER_LINEAR)
    canvas = np.full((h, w, 3), 114, dtype=np.uint8)
    canvas[:resized.shape[0], :resized.shape[1]] = resized
    return np.ascontiguousarray(canvas.transpose(2, 0, 1), dtype=np.float32)[None], ratio


def decode_outputs(raw: np.ndarray, size: tuple[int, int], strides=(8, 16, 32)) -> np.ndarray:
    """Turn raw YOLOX head outputs (1, N, 5 + classes) into centre-x, centre-y, w, h in input pixels."""
    grids, expanded = [], []
    for s in strides:
        gh, gw = size[0] // s, size[1] // s
        xv, yv = np.meshgrid(np.arange(gw), np.arange(gh))
        grid = np.stack((xv, yv), 2).reshape(1, -1, 2)
        grids.append(grid)
        expanded.append(np.full((*grid.shape[:2], 1), s))
    grids = np.concatenate(grids, 1)
    expanded = np.concatenate(expanded, 1)
    out = raw.copy()
    out[..., :2] = (out[..., :2] + grids) * expanded
    out[..., 2:4] = np.exp(out[..., 2:4]) * expanded
    return out[0]


def nms(boxes: np.ndarray, scores: np.ndarray, iou_threshold: float) -> list[int]:
    order = scores.argsort()[::-1]
    keep = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(boxes[i, 0], boxes[order[1:], 0])
        yy1 = np.maximum(boxes[i, 1], boxes[order[1:], 1])
        xx2 = np.minimum(boxes[i, 2], boxes[order[1:], 2])
        yy2 = np.minimum(boxes[i, 3], boxes[order[1:], 3])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-9)
        order = order[1:][iou <= iou_threshold]
    return keep


def postprocess(decoded: np.ndarray, ratio: float, score_threshold: float, iou_threshold: float = 0.45
                ) -> list[Detection]:
    class_scores = decoded[:, 5:] * decoded[:, 4:5]
    class_ids = class_scores.argmax(1)
    scores = class_scores[np.arange(len(class_ids)), class_ids]
    wanted = np.isin(class_ids, list(COCO_TO_CLASS)) & (scores >= score_threshold)
    if not wanted.any():
        return []
    cxcywh, scores, class_ids = decoded[wanted, :4], scores[wanted], class_ids[wanted]
    boxes = np.empty_like(cxcywh)
    boxes[:, 0] = cxcywh[:, 0] - cxcywh[:, 2] / 2
    boxes[:, 1] = cxcywh[:, 1] - cxcywh[:, 3] / 2
    boxes[:, 2] = cxcywh[:, 0] + cxcywh[:, 2] / 2
    boxes[:, 3] = cxcywh[:, 1] + cxcywh[:, 3] / 2
    boxes /= ratio
    result = []
    for cls in np.unique(class_ids):
        idx = np.where(class_ids == cls)[0]
        for k in nms(boxes[idx], scores[idx], iou_threshold):
            j = idx[k]
            result.append(Detection(COCO_TO_CLASS[int(cls)], float(scores[j]), tuple(float(v) for v in boxes[j])))
    return result


class Detector:
    def __init__(self, model_path: str, score_threshold: float = 0.4, providers: list[str] | None = None):
        self.providers = choose_providers(providers)
        self.session = ort.InferenceSession(model_path, providers=self.providers)
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = (int(inp.shape[2]), int(inp.shape[3]))
        self.score_threshold = score_threshold

    @property
    def active_provider(self) -> str:
        return self.session.get_providers()[0]

    def detect(self, frame_bgr: np.ndarray) -> list[Detection]:
        blob, ratio = letterbox(frame_bgr, self.size)
        raw = self.session.run(None, {self.input_name: blob})[0]
        return postprocess(decode_outputs(raw, self.size), ratio, self.score_threshold)
