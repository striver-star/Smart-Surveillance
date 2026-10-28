from datetime import datetime

from worker.detector import Detection
from worker.rules import Zone, ZoneRules

FRAME = (360, 640)   # height, width
LEFT_HALF = [[0, 0], [0.5, 0], [0.5, 1], [0, 1]]


def person(x, y, conf=0.9):
    return Detection("human", conf, (x - 20, y - 80, x + 20, y))


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_needs_confirmation_then_cooldown():
    clock = FakeClock()
    rules = ZoneRules([Zone("Fence", LEFT_HALF, classes=["human"], confirm_frames=3, cooldown_s=30)], clock)
    now = datetime(2026, 10, 28, 22, 0)
    results = [rules.update([person(100, 300)], FRAME, now) for _ in range(5)]
    assert [len(r) for r in results] == [0, 0, 1, 0, 0]
    clock.t = 31
    assert len(rules.update([person(100, 300)], FRAME, now)) == 1


def test_object_outside_zone_or_low_confidence_is_ignored():
    rules = ZoneRules([Zone("Fence", LEFT_HALF, classes=["human"], confirm_frames=1)])
    now = datetime(2026, 10, 28, 22, 0)
    assert rules.update([person(500, 300)], FRAME, now) == []          # right half
    assert rules.update([person(100, 300, conf=0.3)], FRAME, now) == []


def test_foot_point_decides_zone_membership():
    # Box straddles the zone edge, but the feet are inside the left half.
    rules = ZoneRules([Zone("Fence", LEFT_HALF, classes=["human"], confirm_frames=1)])
    d = Detection("human", 0.9, (250, 100, 380, 300))   # foot point x = 315 < 320
    assert len(rules.update([d], FRAME, datetime(2026, 10, 28, 22, 0))) == 1


def test_overnight_schedule():
    z = Zone("Yard", LEFT_HALF, armed=[["18:00", "06:00"]])
    assert z.is_armed(datetime(2026, 10, 28, 23, 0))
    assert z.is_armed(datetime(2026, 10, 29, 5, 59))
    assert not z.is_armed(datetime(2026, 10, 29, 12, 0))


def test_disarmed_zone_does_not_fire():
    rules = ZoneRules([Zone("Yard", LEFT_HALF, classes=["human"], armed=[["18:00", "06:00"]], confirm_frames=1)])
    assert rules.update([person(100, 300)], FRAME, datetime(2026, 10, 28, 12, 0)) == []
