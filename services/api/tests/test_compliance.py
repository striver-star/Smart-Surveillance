from datetime import date

from app.reports.compliance import ACTION, ATTENTION, OK, date_check, out_of_hours, recording_check

TODAY = date(2026, 11, 16)


def test_review_dates():
    f = lambda due: date_check("DPIA", due, TODAY, missing="not recorded", soon_days=60, what="The DPIA review", fix="x")  # noqa: E731
    assert f(None).status == ATTENTION and f(None).text == "not recorded"
    assert f(date(2027, 6, 1)).status == OK
    assert f(date(2026, 12, 20)).status == ATTENTION and "in 34 days" in f(date(2026, 12, 20)).text
    assert f(date(2026, 11, 1)).status == ACTION and "15 days ago" in f(date(2026, 11, 1)).text


def test_recording_days_against_the_dpia():
    assert recording_check({}, 30).status == ATTENTION
    assert recording_check({"nvr1-ch01": 31, "nvr1-ch02": 45}, 30).status == OK
    short = recording_check({"nvr1-ch01": 31, "nvr4-ch22": 12}, 30)
    assert short.status == ATTENTION and "nvr4-ch22" in short.text
    assert recording_check({"nvr1-ch01": 75}, 30).status == ATTENTION       # kept longer than the DPIA allows


def test_out_of_hours():
    assert out_of_hours(23) and out_of_hours(0) and out_of_hours(5)
    assert not out_of_hours(6) and not out_of_hours(14) and not out_of_hours(21)
