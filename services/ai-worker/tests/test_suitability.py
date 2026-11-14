from collections import Counter
from pathlib import Path

import cv2
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
