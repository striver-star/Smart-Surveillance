import os
from pathlib import Path

import numpy as np
import pytest

from worker.detector import Detector, decode_outputs, postprocess

ROOT = Path(__file__).resolve().parents[3]
MODEL = Path(os.environ.get("HSS_TEST_MODEL", ROOT / "models" / "yolox_s.onnx"))
VIDEO = ROOT / "demo" / "media" / "vtest.avi"


def test_postprocess_decodes_one_person():
    size = (64, 64)
    n = sum((64 // s) ** 2 for s in (8, 16, 32))       # 64 + 16 + 4 anchors
    raw = np.zeros((1, n, 85), dtype=np.float32)
    raw[..., 2:4] = -10                                  # tiny boxes everywhere
    # Anchor 9 on the stride-8 grid is cell (x=1, y=1): put a 16x32 person centred there.
    raw[0, 9, :4] = [0.5, 0.5, np.log(2), np.log(4)]
    raw[0, 9, 4] = 0.9                                   # objectness
    raw[0, 9, 5 + 0] = 0.9                               # class 0 = person
    dets = postprocess(decode_outputs(raw, size), ratio=0.5, score_threshold=0.5)
    assert len(dets) == 1
    d = dets[0]
    assert d.object_class == "human" and d.confidence == pytest.approx(0.81)
    assert d.box == pytest.approx((8.0, -8.0, 40.0, 56.0))   # centre (12,12)/0.5, size (16,32)/0.5


def test_ignores_classes_we_do_not_track():
    size = (64, 64)
    raw = np.zeros((1, 84, 85), dtype=np.float32)
    raw[0, 9, 4] = 0.9
    raw[0, 9, 5 + 16] = 0.9                              # class 16 = dog
    assert postprocess(decode_outputs(raw, size), 1.0, 0.5) == []


@pytest.mark.skipif(not (MODEL.exists() and VIDEO.exists()), reason="run tools/fetch-models.sh first")
def test_real_model_finds_people_in_sample_video():
    import av
    detector = Detector(str(MODEL))
    with av.open(str(VIDEO)) as c:
        frame = next(c.decode(video=0)).to_ndarray(format="bgr24")
    people = [d for d in detector.detect(frame) if d.object_class == "human"]
    assert len(people) >= 3
