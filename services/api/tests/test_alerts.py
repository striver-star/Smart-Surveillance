from datetime import datetime
from zoneinfo import ZoneInfo

from app.alerts import DEFAULT_RULES, Rule, armed_now, match_rule

TZ = ZoneInfo("Africa/Lagos")
EV = {"camera_id": "nvr4-ch23", "zone": "Perimeter fence", "type": "intrusion", "object_class": "human", "severity": "critical"}


def at(h, m=0):
    return datetime(2026, 11, 15, h, m, tzinfo=TZ)


def test_armed_windows():
    night = [("18:00", "06:00")]
    assert armed_now(night, at(23)) and armed_now(night, at(2)) and armed_now(night, at(18))
    assert not armed_now(night, at(6)) and not armed_now(night, at(12))
    assert armed_now([], at(12)), "no window = always armed"
    assert armed_now([("08:00", "12:00"), ("14:00", "17:00")], at(15)) and not armed_now([("08:00", "12:00")], at(13))


def test_defaults_critical_and_warning_but_not_info():
    assert match_rule(DEFAULT_RULES, EV, at(12))["name"] == "Critical events"
    assert match_rule(DEFAULT_RULES, {**EV, "severity": "warning"}, at(12))["name"] == "Warnings"
    assert match_rule(DEFAULT_RULES, {**EV, "severity": "info"}, at(12)) is None


def test_first_match_wins_with_filters_and_schedule():
    fence_night = Rule(name="Fence at night", min_severity="info", zones=["*fence*"], objects=["human"],
                       armed=[("18:00", "06:00")], raise_to="critical", channels=["screen", "sound", "whatsapp"]).model_dump()
    rules = [fence_night] + DEFAULT_RULES
    info_ev = {**EV, "severity": "info"}
    assert match_rule(rules, info_ev, at(22))["name"] == "Fence at night"      # info at the fence at night: alert
    assert match_rule(rules, info_ev, at(12)) is None                          # same event at noon: nothing
    assert match_rule(rules, {**info_ev, "object_class": "vehicle"}, at(22)) is None
    assert match_rule(rules, {**EV, "zone": "Main gate"}, at(22))["name"] == "Critical events"
    off = [dict(fence_night, enabled=False)] + DEFAULT_RULES
    assert match_rule(off, info_ev, at(22)) is None


def test_camera_patterns_are_case_insensitive():
    r = Rule(name="NVR4 only", min_severity="warning", cameras=["NVR4-*"]).model_dump()
    assert match_rule([r], {**EV, "severity": "warning"}, at(9))["name"] == "NVR4 only"
    assert match_rule([r], {**EV, "camera_id": "nvr5-ch01", "severity": "warning"}, at(9)) is None


from app.devices import alias, transitions  # noqa: E402

BASE = {"reachable": True, "name": "NVR4", "channels": [{"id": 1, "name": "GATE", "online": True}, {"id": 2, "name": "FENCE", "online": False}],
        "disks": [{"name": "hdd1", "status": "ok"}]}


def test_device_transitions():
    assert alias("10.1.3.4") == "nvr4"
    assert transitions(None, BASE, "nvr4") == [], "first report sets the baseline"
    assert transitions(BASE, BASE, "nvr4") == [], "no change, no event"
    cam_off = {**BASE, "channels": [{"id": 1, "name": "GATE", "online": False}, {"id": 2, "name": "FENCE", "online": True}]}
    assert [(e["type"], e["camera_id"]) for e in transitions(BASE, cam_off, "nvr4")] == [("camera_offline", "nvr4-ch01"), ("camera_online", "nvr4-ch02")]
    bad = {**BASE, "disks": [{"name": "hdd1", "status": "error"}]}
    assert [(e["type"], e["severity"]) for e in transitions(BASE, bad, "nvr4")] == [("drive_fault", "critical")]
    assert [e["type"] for e in transitions(bad, BASE, "nvr4")] == ["drive_ok"]
    down = {"reachable": False, "channels": [], "disks": []}
    assert [e["type"] for e in transitions(BASE, down, "nvr4")] == ["nvr_offline"]
    stored_down = {**BASE, "reachable": False}                    # last good data is kept while down
    back = {**cam_off}
    assert [e["type"] for e in transitions(stored_down, back, "nvr4")] == ["nvr_online", "camera_offline", "camera_online"]
    assert transitions(stored_down, down, "nvr4") == [], "still down: no repeat"


def test_lockdown_arms_every_enabled_rule():
    from datetime import datetime
    from app.alerts import match_rule
    night_only = [{"name": "Fence at night", "enabled": True, "min_severity": "info", "cameras": [], "zones": [], "types": [],
                   "objects": [], "armed": [["18:00", "06:00"]]},
                  {"name": "Off", "enabled": False, "min_severity": "info", "cameras": [], "zones": [], "types": [], "objects": [], "armed": []}]
    ev = {"severity": "warning", "camera_id": "nvr1-ch01", "zone": None, "type": "linedetection", "object_class": None}
    noon = datetime(2026, 11, 16, 12, 0)
    assert match_rule(night_only, ev, noon) is None
    assert match_rule(night_only, ev, noon, always_armed=True)["name"] == "Fence at night"
    assert match_rule(night_only[1:], ev, noon, always_armed=True) is None          # disabled rules stay off
