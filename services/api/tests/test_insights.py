from datetime import datetime, timedelta, timezone

from app.insights import breakdown, rate, suggest

T0 = datetime(2026, 11, 10, 18, 0, tzinfo=timezone.utc)


def a(i, reason, *, hour=18, minutes=0, obj=None, typ="intrusion", zone="Fence", cam="nvr4-ch22", rule="Perimeter"):
    return {"id": f"a{i}", "reason": reason, "hour": hour, "created_at": T0 + timedelta(minutes=minutes), "object_class": obj,
            "type": typ, "zone": zone, "camera_id": cam, "rule": rule}


def test_rate():
    assert rate(3, 1) == 0.75 and rate(0, 0) is None


def test_suggestions_from_patterns():
    burst_dusk_noobj = [a(i, "false_alarm", minutes=i * 3) for i in range(6)]
    tips = " ".join(suggest(burst_dusk_noobj, {"armed": [], "cooldown_s": 60}))
    assert "human and vehicle filter" in tips and "dusk and dawn" in tips and "cool-down (now 60 s)" in tips and "'Fence'" in tips
    daytime = [a(i, "false_alarm", hour=11, minutes=i * 90, obj="human", zone=f"Z{i}") for i in range(5)]
    tips = " ".join(suggest(daytime, {"armed": [], "cooldown_s": 120}))
    assert "night only" in tips and "filter" not in tips
    assert "night only" not in " ".join(suggest(daytime, {"armed": [["18:00", "06:00"]]}))
    motion = [a(i, "false_alarm", typ="motion", obj="human", hour=12, minutes=i * 200, zone=None) for i in range(4)]
    assert "Plain motion" in " ".join(suggest(motion, None))
    assert suggest([a(1, "real_incident")], None) == []


def test_breakdown_flags_noisy_only_with_enough_reviews():
    rows = [a(i, "false_alarm", minutes=i * 30) for i in range(5)] + [a(9, "real_incident")] + \
           [a(20 + i, "false_alarm", cam="nvr5-ch01") for i in range(2)]
    out = {b["key"]: b for b in breakdown(rows, "camera_id", {}, lambda k: k)}
    assert out["nvr4-ch22"]["noisy"] and out["nvr4-ch22"]["rate"] == round(5 / 6, 3) and out["nvr4-ch22"]["tips"]
    assert len(out["nvr4-ch22"]["recent_false"]) == 3
    assert not out["nvr5-ch01"]["noisy"]                      # only 2 reviewed: not judged yet


def test_heat_counts_places_and_hours():
    from app.insights import heat
    rows = [{"camera_id": "nvr1-ch01", "zone": "East fence", "reason": "real_incident", "severity": "critical", "weekday": 0, "hour": 2},
            {"camera_id": "nvr1-ch01", "zone": "East fence", "reason": "false_alarm", "severity": "warning", "weekday": 0, "hour": 2},
            {"camera_id": "nvr1-ch02", "zone": None, "reason": None, "severity": "warning", "weekday": 6, "hour": 23}]
    h = heat(rows)
    assert h["total"] == 3 and h["grid"][0][2] == 2 and h["grid"][6][23] == 1
    top = h["cameras"][0]
    assert top["key"] == "nvr1-ch01" and top["alerts"] == 2 and top["real"] == 1 and top["false"] == 1 and top["critical"] == 1
    assert top["peak_hour"] == 2
    assert [z["key"] for z in h["zones"]] == ["East fence"]                  # alerts without a zone aren't a zone
