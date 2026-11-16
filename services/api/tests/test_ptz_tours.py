from datetime import datetime, time, timezone

from app import ptz
from app.ptz import Control
from app.ptz_tours import Runner, held_by_other, in_window, next_step, overlaps

FRI_19 = datetime(2026, 11, 20, 19, 0)      # a Friday
SAT_05 = datetime(2026, 11, 21, 5, 0)
SAT_07 = datetime(2026, 11, 21, 7, 0)
SUN_05 = datetime(2026, 11, 22, 5, 0)
ALL = [1, 2, 3, 4, 5, 6, 7]


def test_windows():
    assert in_window(ALL, None, None, FRI_19)
    assert not in_window([1, 2], None, None, FRI_19)
    assert in_window(ALL, time(8), time(20), FRI_19) and not in_window(ALL, time(8), time(18), FRI_19)
    night_fri = ([5], time(18), time(6))                   # Friday night only, into Saturday morning
    assert in_window(*night_fri, FRI_19) and in_window(*night_fri, SAT_05)
    assert not in_window(*night_fri, SAT_07) and not in_window(*night_fri, SUN_05)


def test_overlaps():
    day = {"days": ALL, "start_local": time(6), "end_local": time(18)}
    night = {"days": ALL, "start_local": time(18), "end_local": time(6)}
    allday_sun = {"days": [7], "start_local": None, "end_local": None}
    assert not overlaps(day, night)
    assert overlaps(day, allday_sun) and overlaps(night, allday_sun)
    assert not overlaps({"days": [1], "start_local": None, "end_local": None}, {"days": [3], "start_local": None, "end_local": None})


def test_who_has_the_camera():
    assert held_by_other(None, 100, 120, 300) is None
    assert held_by_other(("tour:Fence", 99), 100, 120, 300) is None          # tours don't hold off tours
    assert held_by_other(("ada", 50), 100, 120, 300) == "ada"
    assert held_by_other(("ada", 50), 200, 120, 300) is None
    assert held_by_other(("alert rule", 0), 200, 120, 300) == "alert rule"
    assert next_step(-1, 3) == 0 and next_step(2, 3) == 0 and next_step(0, 3) == 1


def test_runner_goes_round_and_gives_way(monkeypatch):
    c = Control()
    monkeypatch.setattr(ptz, "control", c)
    moves = []
    tour = {"id": 1, "camera_id": "nvr4-ch05", "name": "Fence", "enabled": True, "days": ALL, "start_local": None, "end_local": None,
            "paused_until": None, "paused_by": "", "steps": [{"preset": 1, "dwell_s": 20}, {"preset": 3, "dwell_s": 30}]}
    r = Runner()
    now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    go = lambda cam, pid: moves.append(pid)
    r.tick([tour], now, 1000, go)
    r.tick([tour], now, 1010, go)                           # still dwelling
    r.tick([tour], now, 1020, go)
    assert moves == [1, 3] and r.status(1)["status"] == "running"
    c.claim("nvr4-ch05", {"username": "ada", "role": "operator"}, now=1030)   # a person takes it: allowed, the tour waits
    r.tick([tour], now, 1060, go)
    assert moves == [1, 3] and "ada" in r.status(1)["status"]
    r.tick([tour], now, 1030 + 121, go)                    # nobody touched it for 2 minutes: carries on
    assert moves == [1, 3, 1]
    r.tick([{**tour, "enabled": False}], now, 1300, go)
    assert r.status(1)["status"] == "off" and moves == [1, 3, 1]


def test_failures_retry_later(monkeypatch):
    monkeypatch.setattr(ptz, "control", Control())
    tour = {"id": 2, "camera_id": "nvr4-ch05", "name": "Gate", "enabled": True, "days": ALL, "start_local": None, "end_local": None,
            "paused_until": None, "paused_by": "", "steps": [{"preset": 1, "dwell_s": 20}, {"preset": 2, "dwell_s": 20}]}

    def bad(cam, pid):
        raise RuntimeError("NVR down")
    r = Runner()
    now = datetime(2026, 11, 20, 12, tzinfo=timezone.utc)
    r.tick([tour], now, 0, bad)
    st = r.status(2)
    assert st["status"] == "can't reach the camera" and st["error"] == "NVR down" and st["due"] == 10
