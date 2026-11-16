import numpy as np

from worker.recognition import Repeats, context_crop, plate_decision, roi_crop

LISTS = {"block": "critical", "watch": "warning", "allow": None}
ENTRIES = {"KJA123AB": {"id": "1", "plate": "KJA123AB", "list": "block"}, "LND555XY": {"id": "2", "plate": "LND555XY", "list": "allow"}}


def test_only_listed_plates_with_a_severity_are_reported():
    assert plate_decision("KJA123AB", 0.93, ENTRIES, 0.8, LISTS)["id"] == "1"
    assert plate_decision("KJA123AB", 0.70, ENTRIES, 0.8, LISTS) is None          # unsure read
    assert plate_decision("LND555XY", 0.99, ENTRIES, 0.8, LISTS) is None          # allow list: nothing to report
    assert plate_decision("ABC999ZZ", 0.99, ENTRIES, 0.8, LISTS) is None          # unknown plate: discarded


def test_repeats_fold_within_the_window():
    r = Repeats(60)
    assert r.fresh(("cam", "face", "p1"), 0) and not r.fresh(("cam", "face", "p1"), 59)
    assert r.fresh(("cam", "face", "p1"), 61) and r.fresh(("cam2", "face", "p1"), 62) and r.fresh(("cam", "face", "p2"), 62)


def test_crops():
    img = np.zeros((1080, 1920, 3), np.uint8)
    c = context_crop(img, (900, 400, 60, 70))
    assert c.shape[1] >= 320 and c.shape[0] >= 180 and c[..., 2].max() == 255      # box drawn in red
    edge = context_crop(img, (0, 0, 40, 40))
    assert edge.shape[0] > 0 and edge.shape[1] > 0
    sub, ox, oy = roi_crop(img, [0.25, 0.5, 0.75, 1.0])
    assert sub.shape[:2] == (540, 960) and (ox, oy) == (480, 540)
    assert roi_crop(img, None)[0] is img
