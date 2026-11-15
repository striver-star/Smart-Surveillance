from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pytest

from worker import suitability
from worker.suitability import camera_url, verdict

ROOT = Path(__file__).resolve().parents[3]
MODELS, MEDIA = ROOT / "models", ROOT / "demo" / "media"


def test_camera_url_keeps_the_password_out_of_the_report(monkeypatch):
    monkeypatch.setenv("HSS_NVR_USER", "admin")
    monkeypatch.setenv("HSS_NVR_PASSWORD", "p@ss:w/rd")
    name, url, shown = camera_url("Main gate entrance=10.1.3.4:22")
    assert name == "Main gate entrance"
    assert url == "rtsp://admin:p%40ss%3Aw%2Frd@10.1.3.4:554/Streaming/Channels/2201"
    assert shown == "rtsp://10.1.3.4:554/Streaming/Channels/2201"
    assert camera_url("Clip=rtsp://u:secret@cam/x")[2] == "rtsp://cam/x"


def test_verdicts():
    assert verdict(100, 50, 40, Counter(), 120)[0] == "suitable"
    v, advice = verdict(100, 10, 18, Counter({"too small": 80}), 120)
    assert v == "not suitable" and "too small" in advice
    v, advice = verdict(100, 10, 40, Counter({"turned away": 70}), 120)
    assert "facing the walking direction" in advice
    assert verdict(3, 3, 40, Counter(), 20)[1].startswith("picture very dark")
    assert verdict(3, 0, None, Counter(), 120, people_frames=0)[0] == "not enough faces"
    v, advice = verdict(3, 0, None, Counter(), 120, people_frames=50)
    assert v == "not suitable" and "people pass" in advice


@pytest.mark.skipif(not (MODELS / "face_detection_yunet_2023mar.onnx").exists() or not (MEDIA / "lena.jpg").exists(),
                    reason="run tools/fetch-models.sh --demo first")
def test_no_face_template_is_ever_computed(tmp_path, monkeypatch):
    from worker.face import FaceEngine
    lena = cv2.imread(str(MEDIA / "lena.jpg"))
    clip = tmp_path / "door.mp4"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 10, (512, 512))
    for _ in range(40):
        w.write(lena)
    w.release()

    def forbidden(*a, **k):
        raise AssertionError("stage 1 must not compute face templates")
    monkeypatch.setattr(FaceEngine, "embed", forbidden)
    monkeypatch.setenv("HSS_MODELS_DIR", str(MODELS))
    assert suitability.main(["--camera", f"Door={clip}", "--minutes", "1", "--person-model", "",
                             "--out", str(tmp_path / "out")]) == 0
    text = (tmp_path / "out" / "suitability.md").read_text()
    assert "| Door | 512x512 |" in text and "**suitable**" in text
    assert not list((tmp_path / "out").glob("*.jpg")), "no images are written"


def test_full_trial_refuses_live_cameras_without_approval():
    from worker import recognition_trial
    assert recognition_trial.main(["--source", "rtsp://10.1.3.4:554/Streaming/Channels/2201", "--out", "/tmp/x"]) == 3


def test_legal_gate_answers():
    import httpx
    from worker import legal_gate

    def api(state):
        return httpx.MockTransport(lambda r: httpx.Response(200, json=state) if r.headers.get("authorization") == "Bearer t"
                                   else httpx.Response(401))
    locked = {"face": False, "plate": False, "locked_reason": "The legal review has not been accepted."}
    ok, msg = legal_gate.check(["face"], api_url="http://api", token="t", transport=api(locked))
    assert not ok and "not been accepted" in msg
    plate_only = {"face": False, "plate": True, "locked_reason": None, "expires_at": "2027-11-20T10:00:00Z"}
    assert legal_gate.check(["plate"], api_url="http://api", token="t", transport=api(plate_only))[0]
    assert not legal_gate.check(["face", "plate"], api_url="http://api", token="t", transport=api(plate_only))[0]
    assert not legal_gate.check(["plate"], api_url="http://api", token="wrong", transport=api(plate_only))[0]
    assert not legal_gate.check(["plate"], api_url="http://api", token="")[0]


def test_live_stream_survives_drops(monkeypatch):
    """A gap in the picture is counted and reconnected, not the end of the camera's test."""
    import time as _t
    import numpy as np
    from worker import source, suitability

    class FakeReader:
        def __init__(self, url, name):
            self.t0, self.seq, self.reconnects = _t.monotonic(), 0, 0

        def start(self):
            return self

        def stop(self):
            pass

        def latest(self, newer_than=-1):
            el = _t.monotonic() - self.t0
            if 0.6 < el < 3.2:                      # a 2.6 s drop in the middle
                self.reconnects = 1
                return None
            self.seq += 1
            return source.Frame(np.zeros((90, 160, 3), np.uint8), None, self.seq) if self.seq > newer_than else None

    class NoFaces:
        def detect(self, frame):
            return []

    monkeypatch.setattr(source, "LatestFrameReader", FakeReader)
    r = suitability.watch_live(NoFaces(), "rtsp://nvr/1", minutes=4.5 / 60, fps=10, people=None)
    assert "error" not in r and r["frames"] > 10
    assert r["reconnects"] == 1 and 2 <= r["lost_s"] <= 4
    assert suitability.stream_text(r).startswith("1 drop")


# ---- number plate suitability (measures plates, never reads them)
def _plate_scene(scale=0.45, blur=0, motion=0, brighten=1.0, text="KJA 123 AB"):
    plate = np.full((130, 520, 3), 245, np.uint8)
    cv2.rectangle(plate, (2, 2), (517, 127), (40, 40, 40), 3)
    (tw, _), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_DUPLEX, 2.2, 5)
    cv2.putText(plate, text, ((520 - tw) // 2, 98), cv2.FONT_HERSHEY_DUPLEX, 2.2, (30, 30, 30), 5)
    img = np.full((720, 1280, 3), 90, np.uint8)
    cv2.rectangle(img, (300, 250), (1000, 700), (60, 70, 80), -1)          # a "vehicle"
    p = cv2.resize(plate, (int(520 * scale), int(130 * scale)), interpolation=cv2.INTER_AREA)
    y, x = 520, 640 - p.shape[1] // 2
    img[y:y + p.shape[0], x:x + p.shape[1]] = p
    if blur:
        img = cv2.GaussianBlur(img, (blur, blur), 0)
    if motion:
        k = np.zeros((motion, motion)); k[motion // 2, :] = 1.0 / motion
        img = cv2.filter2D(img, -1, k)
    return np.clip(img.astype(float) * brighten, 0, 255).astype(np.uint8)


DET = Path(__file__).resolve().parents[3] / "models" / "ch_PP-OCRv4_det_infer.onnx"


@pytest.mark.skipif(not DET.exists(), reason="run tools/fetch-models.sh first")
def test_plate_measurements():
    from worker.plate import TextDetector, warp_box
    from worker.plate_suitability import measure, plate_lines
    td = TextDetector(str(DET))

    def m(img):
        lines = plate_lines(td.detect_text(img), img.shape[0])
        assert lines, "the plate line should be found"
        return measure(warp_box(img, max(lines, key=lambda b: float(np.linalg.norm(b[1] - b[0])))))
    assert m(_plate_scene(0.45))["problems"] == []
    assert "too small" in m(_plate_scene(0.2))["problems"] and m(_plate_scene(0.3))["problems"] == []
    assert "blurred" in m(_plate_scene(0.45, motion=9))["problems"]
    assert "glare" in m(_plate_scene(0.45, brighten=2.6))["problems"]


@pytest.mark.skipif(not DET.exists(), reason="run tools/fetch-models.sh first")
def test_plate_suitability_never_reads(tmp_path, monkeypatch):
    from worker import plate, plate_suitability

    def forbidden(*a, **k):
        raise AssertionError("the plate suitability test must not read plates")
    monkeypatch.setattr(plate.PlateReader, "__init__", forbidden)         # the reading model is never even loaded
    monkeypatch.setattr(plate.PlateReader, "recognize", forbidden)
    clip = tmp_path / "gate.mp4"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"mp4v"), 10, (1280, 720))
    for i in range(60):
        w.write(_plate_scene(0.45 if i < 40 else 0.17))
    w.release()
    assert plate_suitability.main(["--camera", f"Gate lane={clip}", "--minutes", "1", "--fps", "10", "--roi", "0,0,1,1",
                                   "--models", str(DET.parent), "--out", str(tmp_path / "out")]) == 0
    text = (tmp_path / "out" / "plate-suitability.md").read_text()
    assert "| Gate lane | 1280x720 |" in text and "**suitable**" in text and "too small" in text
    assert "KJA" not in text and not list((tmp_path / "out").glob("*.jpg")), "no plate text or images are written"
