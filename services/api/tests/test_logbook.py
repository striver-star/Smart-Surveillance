from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.logbook import DEFAULT_SHIFTS, may_edit, shift_at

L = ZoneInfo("Africa/Lagos")


def at(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=L)


def test_day_and_overnight_shifts():
    assert shift_at(DEFAULT_SHIFTS, at(15, 9)) == ("Day", at(15, 6), at(15, 18))
    assert shift_at(DEFAULT_SHIFTS, at(15, 18)) == ("Night", at(15, 18), at(16, 6))
    assert shift_at(DEFAULT_SHIFTS, at(16, 2, 30)) == ("Night", at(15, 18), at(16, 6))      # after midnight: last night's shift
    assert shift_at(DEFAULT_SHIFTS, at(16, 6)) == ("Day", at(16, 6), at(16, 18))
    three = [["Morning", "06:00", "14:00"], ["Afternoon", "14:00", "22:00"], ["Night", "22:00", "06:00"]]
    assert shift_at(three, at(15, 23))[0] == "Night" and shift_at(three, at(16, 5, 59))[1] == at(15, 22)
    assert shift_at([["Day", "08:00", "17:00"]], at(15, 20))[0] == "Outside shifts"


def test_only_the_author_for_15_minutes():
    now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    assert may_edit("ada", now - timedelta(minutes=10), "ada", now)
    assert not may_edit("ada", now - timedelta(minutes=16), "ada", now)
    assert not may_edit("ada", now - timedelta(minutes=1), "bayo", now)
