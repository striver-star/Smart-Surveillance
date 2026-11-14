import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from worker.plate import PlateList, normalise_plate

ROOT = Path(__file__).resolve().parents[3]
MODELS, MEDIA = ROOT / "models", ROOT / "demo" / "media"
FACE_MODELS = [MODELS / "face_detection_yunet_2023mar.onnx", MODELS / "face_recognition_sface_2021dec.onnx"]
OCR_MODELS = [MODELS / "ch_PP-OCRv4_det_infer.onnx", MODELS / "ch_PP-OCRv4_rec_infer.onnx"]
need_faces = pytest.mark.skipif(not all(p.exists() for p in FACE_MODELS + [MEDIA / "lena.jpg", MEDIA / "messi5.jpg"]),
                                reason="run tools/fetch-models.sh --demo first")
need_ocr = pytest.mark.skipif(not all(p.exists() for p in OCR_MODELS), reason="run tools/fetch-models.sh first")


def test_normalise_plate_fixes_confusions_by_position():
    assert normalise_plate("KJA 123 AB") == ("KJA123AB", True)
    assert normalise_plate("LND1170S") == ("LND117OS", True)          # O read as 0 in a letter position
    assert normalise_plate("K1A-I23-A8") == ("KIA123AB", True)
    assert normalise_plate("AB 1234") == ("AB1234", False)            # older format kept, flagged


def test_plate_list(tmp_path):
    f = tmp_path / "plates.csv"
    f.write_text("plate,list,note\nkja 123 ab,block,stolen\nABJ-450-XY,allow,staff\n")
    pl = PlateList.load(f)
    assert pl.lookup("KJA123AB") == ("block", "stolen") and pl.lookup("ABJ450XY")[0] == "allow"
    assert pl.lookup("EPE908KL") is None


def synthetic_plate(text, scale=0.4):
    img = np.full((130, 520, 3), 245, np.uint8)
    cv2.putText(img, "FEDERAL REPUBLIC OF NIGERIA", (95, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (60, 140, 40), 2)
    cv2.putText(img, text, (55, 98), cv2.FONT_HERSHEY_DUPLEX, 2.2, (30, 30, 30), 5)
    bg = np.full((300, 500, 3), 90, np.uint8)
    small = cv2.resize(img, None, fx=scale, fy=scale)
    bg[100:100 + small.shape[0], 120:120 + small.shape[1]] = small
    return cv2.GaussianBlur(bg, (3, 3), 0)


@need_ocr
def test_reads_nigerian_plate():
    from worker.plate import PlateReader
    r = PlateReader(*(str(p) for p in OCR_MODELS))
    reads = r.read_plates(synthetic_plate("KJA 123 AB"))
    assert reads and reads[0].display == "KJA 123 AB" and reads[0].standard
    assert all("EDERAL" not in x.plate for x in reads), "header text is not a plate"


@need_faces
def test_face_watchlist_match_and_privacy(tmp_path):
    from worker.face import FaceEngine, Watchlist
    e = FaceEngine(*(str(p) for p in FACE_MODELS))
    lena, messi = cv2.imread(str(MEDIA / "lena.jpg")), cv2.imread(str(MEDIA / "messi5.jpg"))
    d = tmp_path / "faces" / "p001"
    d.mkdir(parents=True)
    cv2.imwrite(str(d / "a.jpg"), lena)
    (d / "person.json").write_text(json.dumps({"name": "A", "list": "blocked", "consent_ref": "TEST"}))
    nc = tmp_path / "faces" / "p002"
    nc.mkdir()
    cv2.imwrite(str(nc / "a.jpg"), lena)
    (nc / "person.json").write_text(json.dumps({"name": "B", "list": "vip"}))
    wl, problems = Watchlist.load(tmp_path, e)
    assert [p.person_id for p in wl.people] == ["p001"]
    assert any("p002" in p and "consent_ref" in p for p in problems), "no consent reference: not enrolled"

    # Same person: smaller, tilted, darker. Must match.
    m = cv2.getRotationMatrix2D((256, 256), 8, 0.7)
    variant = cv2.convertScaleAbs(cv2.warpAffine(lena, m, (512, 512), borderMode=cv2.BORDER_REFLECT), alpha=0.8, beta=-20)
    f = e.detect(variant)[0]
    assert f.quality_ok, f.quality                  # a tilted head is not "turned away"
    match, _ = wl.match(e.embed(variant, f))
    assert match and match.person_id == "p001" and match.score > 0.6

    # Someone else (upscaled so the detector finds a usable face): no match.
    big = cv2.resize(messi, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    g = e.detect(big)[0]
    match, best = wl.match(e.embed(big, g))
    assert match is None and best < 0.3

    # Faces too small to recognise are flagged, not matched.
    assert "too small" in e.detect(cv2.resize(lena, (96, 96)))[0].quality["problems"]
