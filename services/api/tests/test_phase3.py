from datetime import date, datetime, timezone

from app.evidence import GENESIS, check_chain, entry_hash, expired
from app.eventsetup import summarise
from app.isapi import parse_triggers

TRIGGERS = """<EventTriggerList xmlns="http://www.isapi.org/ver20/XMLSchema">
<EventTrigger><id>linedetection-D22</id><eventType>linedetection</eventType><dynVideoInputChannelID>22</dynVideoInputChannelID>
 <EventTriggerNotificationList><EventTriggerNotification><notificationMethod>center</notificationMethod></EventTriggerNotification>
 <EventTriggerNotification><notificationMethod>record</notificationMethod></EventTriggerNotification></EventTriggerNotificationList></EventTrigger>
<EventTrigger><id>fielddetection-D22</id><eventType>fielddetection</eventType><dynVideoInputChannelID>22</dynVideoInputChannelID>
 <EventTriggerNotificationList><EventTriggerNotification><notificationMethod>beep</notificationMethod></EventTriggerNotification></EventTriggerNotificationList></EventTrigger>
<EventTrigger><id>VMD-D23</id><eventType>VMD</eventType><dynVideoInputChannelID>23</dynVideoInputChannelID><EventTriggerNotificationList/></EventTrigger>
<EventTrigger><id>tamperdetection-1</id><eventType>tamperdetection</eventType><videoInputChannelID>1</videoInputChannelID>
 <EventTriggerNotificationList><EventTriggerNotification><notificationMethod>center</notificationMethod></EventTriggerNotification></EventTriggerNotificationList></EventTrigger>
<EventTrigger><id>diskerror</id><eventType>diskerror</eventType><EventTriggerNotificationList>
 <EventTriggerNotification><notificationMethod>beep</notificationMethod></EventTriggerNotification></EventTriggerNotificationList></EventTrigger>
<EventTrigger><id>facedetection-D5</id><eventType>facedetection</eventType><dynVideoInputChannelID>5</dynVideoInputChannelID></EventTrigger>
</EventTriggerList>"""


def test_parse_triggers_reads_center_linkage():
    t = parse_triggers(TRIGGERS)
    line = next(x for x in t if x["event"] == "linedetection")
    assert line["channel"] == 22 and line["center"] and line["methods"] == ["center", "record"]
    assert not next(x for x in t if x["event"] == "fielddetection")["center"]
    disk = next(x for x in t if x["event"] == "diskerror")
    assert disk["channel"] is None and not disk["center"]
    assert not any(x["event"] == "facedetection" for x in t)                 # not an event HSS alerts on
    s = summarise(t)
    assert s[22] == {"sent": ["Line crossing"], "not_sent": ["Intrusion"]}
    assert s[1]["sent"] == ["Video tampering"] and 23 not in s               # plain motion is ignored


def test_custody_chain_detects_changes():
    rows, prev = [], GENESIS
    for i, (who, action) in enumerate([("cso", "sealed"), ("admin", "downloaded"), ("admin", "hold_on")], 1):
        at = f"2026-11-15T10:0{i}:00.000000+00:00"
        h = entry_hash(prev, "e1", at, who, action, "")
        rows.append((i, "e1", at, who, action, "", prev, h))
        prev = h
    assert check_chain(rows) == (True, "3 entries intact")
    tampered = list(rows)
    tampered[1] = (2, "e1", rows[1][2], "someone-else", "downloaded", "", rows[1][6], rows[1][7])
    assert check_chain(tampered)[0] is False
    assert check_chain([rows[0], rows[2]])[0] is False                       # a removed entry breaks it too


def test_retention_skips_holds():
    rows = [{"id": 1, "retain_until": date(2026, 1, 1), "legal_hold": False, "deleted_at": None},
            {"id": 2, "retain_until": date(2026, 1, 1), "legal_hold": True, "deleted_at": None},
            {"id": 3, "retain_until": date(2027, 1, 1), "legal_hold": False, "deleted_at": None},
            {"id": 4, "retain_until": date(2026, 1, 1), "legal_hold": False, "deleted_at": datetime(2026, 2, 1, tzinfo=timezone.utc)}]
    assert [r["id"] for r in expired(rows, date(2026, 11, 15))] == [1]
