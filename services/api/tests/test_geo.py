import math
from datetime import datetime, timezone

import pytest

from app.geo import Georef, parse_traccar, polygon_wkt, zone_changes

# Two points of a site plan 1000 px wide, about 400 m across (Lagos-ish latitude).
REFS = [{"x": 100, "y": 800, "lat": 6.5000, "lon": 3.3500}, {"x": 900, "y": 200, "lat": 6.5030, "lon": 3.3530}]


def test_georef_round_trip_and_scale():
    g = Georef(REFS)
    for p in REFS:
        lat, lon = g.to_latlon(p["x"], p["y"])
        assert abs(lat - p["lat"]) < 1e-9 and abs(lon - p["lon"]) < 1e-9
    lat, lon = g.to_latlon(500, 500)
    x, y = g.to_px(lat, lon)
    assert abs(x - 500) < 1e-6 and abs(y - 500) < 1e-6
    ground = math.hypot(0.003 * 111_320 * math.cos(math.radians(6.5015)), 0.003 * 111_195)
    assert abs(g.metres_per_px * 1000 - ground) < 2                 # 1000 px between the points on the plan
    assert "POLYGON((" in polygon_wkt([[0, 0], [10, 0], [10, 10]], g)


def test_georef_rejects_bad_points():
    with pytest.raises(ValueError):
        Georef([REFS[0], {**REFS[1], "x": 105, "y": 805}])           # too close on the plan
    with pytest.raises(ValueError):
        Georef([REFS[0], {**REFS[1], "lat": 6.50001, "lon": 3.35001}])  # too close on the ground


ZONES = {1: {"kind": "restricted", "applies_to": "all", "alert_on": "enter", "severity": "critical"},
         2: {"kind": "perimeter", "applies_to": "guard", "alert_on": "exit", "severity": "warning"},
         3: {"kind": "checkpoint", "applies_to": "guard", "alert_on": "enter", "severity": "info"},
         4: {"kind": "area", "applies_to": "vehicle", "alert_on": "both", "severity": "warning"}}


def test_zone_changes():
    assert zone_changes({2}, {1, 2}, ZONES, "guard", {1: True}) == [{"zone_id": 1, "type": "zone_enter", "severity": "critical"}]
    assert zone_changes({1, 2}, {1, 2}, ZONES, "guard", {}) == []                                         # no move, no event
    assert zone_changes({2}, {1, 2}, ZONES, "guard", {1: False}) == []                                    # not armed now
    assert zone_changes({2}, set(), ZONES, "guard", {}) == [{"zone_id": 2, "type": "zone_exit", "severity": "warning"}]
    assert zone_changes({2}, set(), ZONES, "vehicle", {}) == []                                           # guards only
    assert zone_changes(set(), {3}, ZONES, "guard", {}) == [{"zone_id": 3, "type": "checkpoint_visit", "severity": "info"}]
    assert [e["type"] for e in zone_changes({4}, set(), ZONES, "vehicle", {})] == ["zone_exit"]


def test_parse_traccar_forward():
    body = {"position": {"deviceId": 7, "latitude": 6.5012, "longitude": 3.3514, "fixTime": "2026-11-15T19:00:05.000+00:00",
                         "speed": 2.7, "accuracy": 8.0, "valid": True, "attributes": {"batteryLevel": 41.0, "alarm": "sos"}},
            "device": {"id": 7, "uniqueId": "hss-guard-patrol1", "name": "Patrol 1"}}
    p = parse_traccar(body)
    assert p["device_id"] == "hss-guard-patrol1" and p["lat"] == 6.5012 and p["battery"] == 41.0 and p["alarm"] == "sos"
    assert p["speed_kmh"] == 5.0 and p["at"] == datetime(2026, 11, 15, 19, 0, 5, tzinfo=timezone.utc)
    assert parse_traccar({"position": {**body["position"], "valid": False}, "device": body["device"]}) is None
    assert parse_traccar({"device": body["device"]}) is None


def test_missed_patrol_timing():
    from datetime import timedelta
    from app.geo import missed_due
    t0 = datetime(2026, 11, 15, 18, 0, tzinfo=timezone.utc)
    assert missed_due(None, t0, 30, None) == t0 + timedelta(minutes=30)                    # new checkpoint: 30 min grace
    assert missed_due(t0 + timedelta(minutes=50), t0, 30, None) == t0 + timedelta(minutes=80)
    assert missed_due(t0, t0 - timedelta(days=3), 30, t0 + timedelta(hours=2)) == t0 + timedelta(hours=2, minutes=30)  # armed later
