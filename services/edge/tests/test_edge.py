import base64
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx

from edge.hikvision import Debouncer, MultipartSplitter, notifications, parse_notification
from edge.nvr import Nvr, alias
from edge.platform import Platform

JPEG = b"\xff\xd8\xff\xe0" + b"x" * 200 + b"\xff\xd9"


def alert_xml(etype, state="active", ch=3, target=None):
    t = f"<DetectionRegionList><DetectionRegionEntry><targetType>{target}</targetType></DetectionRegionEntry></DetectionRegionList>" if target else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><EventNotificationAlert version="2.0" xmlns="http://www.hikvision.com/ver20/XMLSchema">'
            f"<ipAddress>10.1.3.4</ipAddress><channelID>{ch}</channelID><dateTime>2026-11-15T07:00:00+01:00</dateTime>"
            f"<activePostCount>1</activePostCount><eventType>{etype}</eventType><eventState>{state}</eventState>"
            f"<eventDescription>{etype} alarm</eventDescription>{t}</EventNotificationAlert>")


def part(ctype, body: bytes) -> bytes:
    return b"--boundary\r\nContent-Type: " + ctype.encode() + b"\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body + b"\r\n"


def test_multipart_split_across_chunks_with_picture():
    stream = (part("application/xml; charset=\"UTF-8\"", alert_xml("videoloss", "inactive", 0).encode())
              + part("application/xml", alert_xml("linedetection", target="human").encode()) + part("image/jpeg", JPEG)
              + part("application/xml", alert_xml("fielddetection", ch=5).encode()) + b"--boundary\r\n")
    s = MultipartSplitter("boundary")
    found = []
    for i in range(0, len(stream), 37):                 # arrive in awkward pieces
        found += notifications(s.feed(stream[i:i + 37]))
    assert [(n.raw_type, n.state, n.channel) for n in found] == [("videoloss", "inactive", 0), ("linedetection", "active", 3),
                                                                 ("fielddetection", "active", 5)]
    line = found[1]
    assert line.object_class == "human" and line.platform == ("line_crossing", "warning")
    whole = notifications(MultipartSplitter("boundary").feed(stream))
    assert whole[1].image == JPEG and whole[2].image is None    # picture stays with the notification it followed


def test_bare_xml_stream_without_boundary():
    s = MultipartSplitter(None)
    out = notifications(s.feed(alert_xml("shelteralarm").encode() + b"\r\n" + alert_xml("vmd").encode()))
    assert [n.platform[0] for n in out] == ["tamper", "motion"]


def test_unknown_and_device_types():
    assert parse_notification(alert_xml("hdError")).platform == ("drive_fault", "critical")
    assert parse_notification(alert_xml("somethingNew")).platform == ("other_somethingnew", "info")
    assert parse_notification("<notxml") is None


def test_debounce_raises_once_per_activity():
    d, n = Debouncer(10), parse_notification(alert_xml("linedetection"))
    assert d.should_raise(n, now=0) and not d.should_raise(n, now=1) and not d.should_raise(n, now=9)
    assert d.should_raise(n, now=25)                                  # quiet for >10 s: a new activity
    assert not d.should_raise(parse_notification(alert_xml("linedetection", "inactive")), now=26)
    assert d.should_raise(n, now=27)                                  # after inactive, the next active is new
    assert d.should_raise(parse_notification(alert_xml("linedetection", ch=4)), now=27), "other channel is separate"


def test_offline_queue_keeps_order_and_replays(tmp_path):
    state = {"up": False, "got": []}

    def api(req):
        if not state["up"]:
            raise httpx.ConnectError("down")
        state["got"].append(req.read().decode())
        return httpx.Response(201, json={})
    p = Platform("http://api", "t", tmp_path, transport=httpx.MockTransport(api))
    assert p.post_event({"n": 1}) == "queued" and p.post_event({"n": 2}) == "queued" and p.queued_count() == 2
    state["up"] = True
    assert p.post_event({"n": 3}) == "queued", "while a queue exists, new events join it (order kept)"
    assert p.flush() == 3 and p.queued_count() == 0
    assert [eval(x)["n"] for x in state["got"]] == [1, 2, 3]


ISAPI = {
    "/ISAPI/System/deviceInfo": "<DeviceInfo><deviceName>NVR4</deviceName><model>DS-7632NXI-K2/16P</model><firmwareVersion>V4.83.005</firmwareVersion></DeviceInfo>",
    "/ISAPI/ContentMgmt/InputProxy/channels": "<InputProxyChannelList><InputProxyChannel><id>1</id><name>GATE</name><sourceInputPortDescriptor><ipAddress>10.1.3.168</ipAddress></sourceInputPortDescriptor></InputProxyChannel><InputProxyChannel><id>2</id><name>FENCE</name></InputProxyChannel></InputProxyChannelList>",
    "/ISAPI/ContentMgmt/InputProxy/channels/status": "<L><InputProxyChannelStatus><id>1</id><online>true</online></InputProxyChannelStatus><InputProxyChannelStatus><id>2</id><online>false</online></InputProxyChannelStatus></L>",
    "/ISAPI/ContentMgmt/Storage": "<storage><hddList><hdd><id>1</id><hddName>hdd1</hddName><status>notexist</status></hdd><hdd><id>2</id><hddName>hdd2</hddName><capacity>3815447</capacity><freeSpace>0</freeSpace><status>error</status></hdd></hddList></storage>",
    "/ISAPI/System/time": "<Time><timeMode>manual</timeMode></Time>",
}


def test_health_check_reads_channels_and_drives():
    nvr = Nvr("10.1.3.4", "u", "p", transport=httpx.MockTransport(lambda r: httpx.Response(200, text=ISAPI[r.url.path]) if r.url.path in ISAPI else httpx.Response(404)))
    h = nvr.health()
    assert h["reachable"] and h["name"] == "NVR4" and h["time_mode"] == "manual"
    assert h["channels"] == [{"id": 1, "name": "GATE", "ip": "10.1.3.168", "online": True}, {"id": 2, "name": "FENCE", "ip": "", "online": False}]
    assert h["disks"][1] == {"name": "hdd2", "status": "error", "capacity_gb": 3726.0, "free_gb": 0.0}
    refused = Nvr("10.1.3.5", "u", "p", transport=httpx.MockTransport(lambda r: httpx.Response(401))).health()
    assert refused == {"nvr": "10.1.3.5", "reachable": False, "detail": "login refused (HTTP 401)"}

    def down(r):
        raise httpx.ConnectTimeout("t")
    assert Nvr("10.1.3.6", "u", "p", transport=httpx.MockTransport(down)).health()["detail"].startswith("no answer")


def test_playback_url_uses_local_time_and_hides_nothing_unencoded():
    nvr = Nvr("10.1.3.4", "admin", "p@ss:1", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    url = nvr.playback_url(22, datetime(2026, 11, 15, 6, 0, 0, tzinfo=timezone.utc), datetime(2026, 11, 15, 6, 0, 30, tzinfo=timezone.utc), ZoneInfo("Africa/Lagos"))
    assert url == "rtsp://admin:p%40ss%3A1@10.1.3.4:554/Streaming/tracks/2201?starttime=20261115T070000Z&endtime=20261115T070030Z"
    assert alias("10.1.3.4") == "nvr4" and alias("10.1.3.4:8080") == "nvr4"


def test_event_shape():
    nvr = Nvr("10.1.3.4", "u", "p", transport=httpx.MockTransport(lambda r: httpx.Response(404)))
    n = parse_notification(alert_xml("fielddetection", ch=23, target="vehicle"))
    n.image = JPEG
    ev = nvr.to_event(n)
    assert ev["camera_id"] == "nvr4-ch23" and ev["type"] == "intrusion" and ev["object_class"] == "vehicle"
    assert ev["source_kind"] == "edge" and base64.b64decode(ev["snapshot_jpeg_b64"]) == JPEG
    assert ev["raw"]["device_time"] == "2026-11-15T07:00:00+01:00"
