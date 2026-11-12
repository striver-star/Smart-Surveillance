import csv
import json
from datetime import datetime, timedelta, timezone

import httpx

from hss_probe import cameras
from hss_probe.cameras import camera_class, clock_drift_seconds, model_hints
from hss_probe.isapi import IsapiClient

NOW = datetime.now(timezone.utc)


def dev(model, fw="V5.7.15", serial="S1"):
    return (f"<DeviceInfo><deviceName>cam</deviceName><model>{model}</model><serialNumber>{serial}</serialNumber>"
            f"<macAddress>aa</macAddress><firmwareVersion>{fw}</firmwareVersion>"
            f"<firmwareReleasedDate>build 230101</firmwareReleasedDate></DeviceInfo>")


def time_xml(offset_s=0, mode="NTP"):
    t = (NOW + timedelta(seconds=offset_s)).astimezone(timezone(timedelta(hours=1)))
    return f"<Time><timeMode>{mode}</timeMode><localTime>{t.isoformat(timespec='seconds')}</localTime></Time>"


def net(ip):
    return f"<NetworkInterfaceList><NetworkInterface><IPAddress><ipAddress>{ip}</ipAddress></IPAddress></NetworkInterface></NetworkInterfaceList>"


def events(*types):
    return f"<ChannelEventCap><eventType opt=\"{','.join(types)}\"/></ChannelEventCap>"


COLORVU_ACUSENSE = {
    "/ISAPI/System/deviceInfo": dev("DS-2CD2047G2-LU", "V5.7.15"),
    "/ISAPI/System/time": time_xml(0),
    "/ISAPI/System/Network/interfaces": net("10.1.3.168"),
    "/ISAPI/Event/capabilities": events("VMD", "linedetection", "fielddetection", "shelteralarm"),
    "/ISAPI/Smart/FieldDetection/1/capabilities": "<FieldDetection><detectionTarget opt=\"all,human,vehicle\"/></FieldDetection>",
    "/ISAPI/Image/channels/1/supplementLight": "<SupplementLight><supplementLightMode opt=\"colorVuWhiteLight,close\"/></SupplementLight>",
}
BASIC = {
    "/ISAPI/System/deviceInfo": dev("DS-2CD1023G0-I", "V5.5.0"),
    "/ISAPI/System/time": time_xml(-900, "manual"),
    "/ISAPI/System/Network/interfaces": net("192.168.254.3"),
    "/ISAPI/Event/capabilities": events("VMD", "videoloss", "shelteralarm"),
    "/ISAPI/Image/channels/1/supplementLight": "<SupplementLight><supplementLightMode opt=\"irLight\"/></SupplementLight>",
}
NVR = {
    "/ISAPI/System/deviceInfo": dev("DS-7732NI-K4/16P", "V4.1.70", "NVRSERIAL"),
    "/ISAPI/ContentMgmt/InputProxy/channels": """<InputProxyChannelList>
      <InputProxyChannel><id>1</id><name>GATE</name><sourceInputPortDescriptor><ipAddress>10.1.3.168</ipAddress></sourceInputPortDescriptor></InputProxyChannel>
      <InputProxyChannel><id>2</id><name>STORE</name><sourceInputPortDescriptor><ipAddress>192.168.254.3</ipAddress></sourceInputPortDescriptor></InputProxyChannel>
      <InputProxyChannel><id>3</id><name>Camera 01</name><sourceInputPortDescriptor><ipAddress>192.168.254.4</ipAddress></sourceInputPortDescriptor></InputProxyChannel>
      <InputProxyChannel><id>4</id><name>OTHER PASSWORD</name><sourceInputPortDescriptor><ipAddress>10.1.3.170</ipAddress></sourceInputPortDescriptor></InputProxyChannel>
    </InputProxyChannelList>""",
    "/ISAPI/ContentMgmt/InputProxy/channels/status": """<InputProxyChannelStatusList>
      <InputProxyChannelStatus><id>1</id><online>true</online></InputProxyChannelStatus>
      <InputProxyChannelStatus><id>2</id><online>true</online></InputProxyChannelStatus>
      <InputProxyChannelStatus><id>3</id><online>false</online></InputProxyChannelStatus>
      <InputProxyChannelStatus><id>4</id><online>true</online></InputProxyChannelStatus>
    </InputProxyChannelStatusList>""",
    "/ISAPI/Event/channels/1/capabilities": events("VMD", "linedetection", "fielddetection"),
    "/ISAPI/Event/channels/2/capabilities": events("VMD", "linedetection", "fielddetection"),
    "/ISAPI/Event/channels/4/capabilities": events("VMD"),
    "/ISAPI/Smart/FieldDetection/1": "<FieldDetection/>",
    "/ISAPI/Smart/FieldDetection/2": "<FieldDetection/>",
}
HOSTS = {"10.1.3.6": NVR, "10.1.3.168": COLORVU_ACUSENSE, "10.1.3.6:65002": BASIC}
seen = []


def handler(req: httpx.Request) -> httpx.Response:
    assert req.method == "GET", "hss-cameras must never change a device"
    host = req.url.host + (f":{req.url.port}" if req.url.port not in (None, 80) else "")
    seen.append(f"{host}{req.url.path}")
    if host == "10.1.3.170":
        return httpx.Response(401)
    routes = HOSTS.get(host)
    if routes is None:
        raise httpx.ConnectError("unreachable")
    body = routes.get(req.url.path)
    return httpx.Response(200, text=body) if body else httpx.Response(404)


class FakeClient(IsapiClient):
    def __init__(self, base, user, password, **kw):
        kw.pop("transport", None)
        super().__init__(base, user, password, transport=httpx.MockTransport(handler), **kw)


def test_model_hints():
    assert "colorvu" in model_hints("DS-2CD2047G2-LU")
    assert "acusense" in model_hints("DS-2CD2143G2-IS")
    assert "hybrid_light" in model_hints("DS-2CD2387G2H-LIU")
    assert model_hints("DS-2CD1023G0-I") == {}            # G0 entry level: no AcuSense
    assert "deepinview" in model_hints("iDS-2CD7A46G0-IZHS")


def test_class_prefers_capabilities_over_model():
    cam = {"model": "DS-2CD2043G2-I", "event_types": ["vmd"], "_caps_text": "", "_light_text": "irLight"}
    cls, _ = camera_class(cam)
    assert cls == "Basic (no AI)", "AcuSense model code alone is not enough without smart events"


def test_clock_drift():
    assert abs(clock_drift_seconds((NOW + timedelta(seconds=120)).isoformat(), NOW) - 120) <= 1
    assert clock_drift_seconds("2026-11-12T10:00:00", NOW) is None     # no time zone: can't tell


def test_survey_end_to_end(tmp_path, monkeypatch):
    monkeypatch.setenv("HSS_NVR_USER", "admin")
    monkeypatch.setenv("HSS_NVR_PASSWORD", "pw")
    assert cameras.main(["--host", "10.1.3.6", "--out", str(tmp_path)], client_class=FakeClient) == 0
    rows = {int(r["channel"]): r for r in csv.DictReader((tmp_path / "cameras.csv").open())}

    assert rows[1]["reached_via"] == "direct" and rows[1]["class"] == "ColorVu + AcuSense" and rows[1]["tier"] == "E"
    assert rows[2]["reached_via"] == "virtual host :65002", "PoE camera matched to its channel by IP"
    assert rows[2]["class"] == "Basic (no AI)" and rows[2]["tier"] == "N", "NVR offers AI for it"
    assert rows[2]["time_mode"] == "manual" and abs(int(rows[2]["clock_drift_s"]) + 900) <= 2
    assert rows[3]["class"] == "offline"
    assert rows[4]["class"] == "not reached" and rows[4]["tier"] == "?"
    assert rows[1]["nvr_reads_field_detection"] == "200" and rows[4]["nvr_reads_field_detection"] == "404"

    text = (tmp_path / "cameras-summary.md").read_text()
    assert "| DS-2CD2047G2-LU | V5.7.15 build 230101 (1) |" in text
    assert "**ColorVu:** GATE" in text and "**Non-AI:** STORE" in text
    assert "1 cameras are more than 30 seconds off" in text
    assert "OTHER PASSWORD" in text                       # listed under online but not reached
    data = json.loads((tmp_path / "cameras.json").read_text())
    assert "_caps_text" not in json.dumps(data), "internal fields stay out of the output"
    assert (tmp_path / "raw" / "10.1.3.6" / "ch01_device_info.xml").exists()
