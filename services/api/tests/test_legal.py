from datetime import date, datetime, timedelta, timezone

from app.legal import AcceptIn, check_acceptance, document, recognition_scope

NOW = datetime(2026, 11, 20, 10, 0, tzinfo=timezone.utc)


def good(**kw):
    d = document()
    base = dict(read_id="x", version=d["version"], scopes=["plate"], conditions=[True] * len(d["conditions"]), read_to_end=True,
                full_name="Ada Obi", position="General Manager", reviewer_name="B. Musa", reviewer_firm="Musa & Co",
                opinion_ref="MC/2026/114", opinion_date=date(2026, 11, 18), dpia_ref="DPIA-2026-03")
    return AcceptIn(**{**base, **kw})


def check(body, opened=NOW - timedelta(minutes=10), two_factor=True):
    d = document()
    return check_acceptance(body, version=d["version"], n_conditions=len(d["conditions"]), opened_at=opened, now=NOW, two_factor=two_factor)


def test_document_has_the_ten_conditions():
    d = document()
    assert len(d["conditions"]) == 10 and d["conditions"][0].startswith("A qualified legal practitioner")
    assert len(d["version"]) == 16 and "not legal advice" in d["text"]


def test_a_complete_acceptance_passes():
    assert check(good()) == []
    assert check(good(scopes=["face", "plate"])) == []


def test_every_gate_is_enforced():
    n = len(document()["conditions"])
    assert any("two-factor" in p for p in check(good(), two_factor=False))
    assert any("at least 2 minutes" in p for p in check(good(), opened=NOW - timedelta(seconds=30)))
    assert any("Open the review" in p for p in check(good(), opened=None))
    assert any("to the end" in p for p in check(good(read_to_end=False)))
    assert any("Every condition" in p for p in check(good(conditions=[True] * (n - 1) + [False])))
    assert any("Every condition" in p for p in check(good(conditions=[True] * (n - 1))))
    assert any("document changed" in p for p in check(good(version="old")))
    assert any("Choose face" in p for p in check(good(scopes=["everything"])))
    assert any("future" in p for p in check(good(opinion_date=date(2026, 12, 1))))
    assert any("12 months old" in p for p in check(good(opinion_date=date(2025, 6, 1))))


def test_which_events_are_gated():
    assert recognition_scope("face_match") == "face" and recognition_scope("watchlist_face") == "face"
    assert recognition_scope("vehicle_plate") == "plate" and recognition_scope("plate_match") == "plate"
    for ordinary in ("face_detected", "line_crossing", "vehicle_detected", "intrusion", "camera_offline"):
        assert recognition_scope(ordinary) is None
