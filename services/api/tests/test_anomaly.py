from datetime import date, timedelta

from app.anomaly import baseline, explain, poisson_sf, quiet, unusual


def test_poisson_tail():
    assert poisson_sf(0, 2.0) == 1.0
    assert abs(poisson_sf(1, 2.0) - (1 - 0.1353352832)) < 1e-6
    assert poisson_sf(5, 0.1) < 1e-6 and poisson_sf(3, 3.0) > 0.5


def test_baseline_counts_empty_days_as_zero():
    today = date(2026, 11, 16)                                      # a Monday
    first = today - timedelta(days=21)                              # 3 weeks: 15 weekdays, 6 weekend days
    counts = {(today - timedelta(days=7), 2): 3}                    # one Monday night with 3 events at 02:00
    for i in range(1, 22):
        d = today - timedelta(days=i)
        counts[(d, 8)] = counts.get((d, 8), 0) + 10                 # 10 events at 08:00 every day
    b = baseline(counts, first, today)
    assert abs(b[("weekday", 2)] - 3 / 15) < 1e-9 and b[("weekend", 2)] == 0
    assert b[("weekday", 8)] == 10 and b[("weekend", 8)] == 10
    assert (today, 8) not in counts and b[("weekday", 9)] == 0     # today itself is never part of the baseline


def test_unusual_and_quiet():
    assert unusual(4, 0.2, 1e-3)[0]                                 # 4 at a camera usually silent at that hour
    assert not unusual(2, 0.2, 1e-3)[0]                             # fewer than 3 is never flagged
    assert not unusual(14, 10.0, 1e-3)[0]                           # a busy camera being a bit busier
    assert unusual(30, 10.0, 1e-3)[0]
    assert unusual(4, 0.5, 1e-2)[0] and not unusual(4, 0.5, 1e-4)[0]  # sensitivity matters
    assert quiet(0, 20.0) and not quiet(1, 20.0) and not quiet(0, 5.0)
    assert "usually almost none around 02:00 on weekdays" in explain("unusual_activity", 4, 0.2, 2, "weekday", "East fence")
