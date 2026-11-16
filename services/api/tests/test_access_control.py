from datetime import datetime, timedelta, timezone

from app.access_control import classify, door_states, mask_card, remote_xml, repeated_denials

T = datetime(2026, 11, 16, 22, tzinfo=timezone.utc)


def test_event_codes():
    assert classify(5, 75) == "granted" and classify(5, 76) == "denied" and classify(5, 1) == "granted" and classify(5, 8) == "denied"
    assert classify(5, 27) == "forced" and classify(5, 28) == "held_open" and classify(5, 25) == "door_open"
    assert classify(5, 999) == "other" and classify(None, None) == "other"


def test_door_states_per_door():
    st = door_states({"doorLockStatus": [0, 1], "doorStatus": [4, 3], "magneticStatus": [1, 0]}, 2)
    assert st[0] == {"door_no": 1, "lock_state": "locked", "mode": "normal", "contact_state": "open"}
    assert st[1] == {"door_no": 2, "lock_state": "unlocked", "mode": "stay_locked", "contact_state": "closed"}
    assert door_states({}, 1)[0]["lock_state"] is None


def test_refusals_and_masking():
    assert repeated_denials([T - timedelta(seconds=s) for s in (100, 40, 0)], T)
    assert not repeated_denials([T - timedelta(seconds=s) for s in (300, 40, 0)], T)
    assert mask_card("1234567890") == "…7890" and mask_card("12") == "12" and mask_card("") == ""
    assert "<cmd>alwaysClose</cmd>" in remote_xml("stay_locked") and "<cmd>open</cmd>" in remote_xml("open")
