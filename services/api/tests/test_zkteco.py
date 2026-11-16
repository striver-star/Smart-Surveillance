from datetime import datetime, timedelta, timezone

from app.access_control import hik_event
from app.zkteco import attlog_event, clock_offset, control_commands, kv, local_time, options_reply, rtlog_event, rtstate_doors, stable_serial


def test_kv_lines():
    assert kv("time=2026-11-16 08:00:00\tpin=1001\tevent=0") == {"time": "2026-11-16 08:00:00", "pin": "1001", "event": "0"}
    assert kv("user uid=1\tpin=1001\tname=Ada Obi")["name"] == "Ada Obi"
    assert kv("PIN=7\tName=Musa")["pin"] == "7"


def test_device_time_is_local():
    t = local_time("2026-11-16 08:00:00", "Africa/Lagos")
    assert t.tzinfo == timezone.utc and t.hour == 7


def test_rtlog_events():
    base = {"time": "2026-11-16 08:00:00", "pin": "1001", "cardno": "0012345678", "eventaddr": "2", "verifytype": "4", "index": "55"}
    e = rtlog_event({**base, "event": "0"}, "UTC")
    assert e["kind"] == "granted" and e["door_no"] == 2 and e["employee_no"] == "1001" and e["serial_no"] == 55 and e["verify"] == "card"
    assert rtlog_event({**base, "event": "27"}, "UTC")["kind"] == "denied"
    assert rtlog_event({**base, "event": "102"}, "UTC")["kind"] == "forced"
    assert rtlog_event({**base, "event": "28"}, "UTC")["kind"] == "held_open"
    assert rtlog_event({**base, "event": "101"}, "UTC")["kind"] == "duress"
    assert rtlog_event({**base, "event": "200"}, "UTC")["kind"] == "door_open"
    assert rtlog_event({**base, "event": "777"}, "UTC")["kind"] == "other"
    no_pin = rtlog_event({**base, "pin": "0", "cardno": "0", "event": "102"}, "UTC")
    assert no_pin["employee_no"] == "" and no_pin["card"] == "" and no_pin["verify"] == ""


def test_attlog_terminal():
    e = attlog_event("1001\t2026-11-16 08:00:00\t0\t15\t0\t0", "UTC")
    assert e["kind"] == "granted" and e["verify"] == "face" and e["employee_no"] == "1001" and e["door_no"] == 1
    assert e["serial_no"] == attlog_event("1001\t2026-11-16 08:00:00\t0\t15", "UTC")["serial_no"]   # re-sends don't duplicate
    assert attlog_event("", "UTC") is None and attlog_event("1001\tnot a time", "UTC") is None
    assert 0 < stable_serial("a") < 2 ** 63


def test_door_states():
    st = rtstate_doors({"sensor": "0102", "relay": "02"}, 2)
    assert st[0] == {"door_no": 1, "contact_state": "closed", "lock_state": "locked"}
    assert st[1] == {"door_no": 2, "contact_state": "open", "lock_state": "unlocked"}
    assert rtstate_doors({}, 1)[0] == {"door_no": 1, "contact_state": None, "lock_state": None}


def test_commands_and_options():
    assert control_commands("open", 1) == ["CONTROL DEVICE 0101010500"]
    assert control_commands("stay_open", 2) == ["CONTROL DEVICE 010201FF00"]
    assert control_commands("normal", 3)[-1] == "CONTROL DEVICE 0103010000"
    assert options_reply("ZK1").startswith("GET OPTION FROM: ZK1\n") and "Realtime=1" in options_reply("ZK1")


def test_hikvision_common_form():
    e = hik_event({"major": 5, "minor": 75, "time": "2026-11-16T08:00:00+01:00", "doorNo": 1, "name": "Ada", "cardNo": "1234567890", "serialNo": 9})
    assert e["kind"] == "granted" and e["door_no"] == 1 and e["person"] == "Ada" and e["serial_no"] == 9


def test_clock_offset():
    now = datetime(2026, 11, 16, 20, tzinfo=timezone.utc)
    assert clock_offset([now - timedelta(hours=1, seconds=2), now - timedelta(hours=2)], now) == timedelta(hours=1, seconds=2)
    assert clock_offset([now - timedelta(seconds=20)], now) == timedelta(0)
    assert clock_offset([now + timedelta(minutes=5)], now) == -timedelta(minutes=5)
    assert clock_offset([], now) == timedelta(0)
