import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("sadp", Path(__file__).with_name("hss-sadp.py"))
sadp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sadp)

REPLY = b"""<?xml version="1.0" encoding="UTF-8" ?>
<ProbeMatch><Uuid>X</Uuid><Types>inquiry</Types><DeviceType>139715</DeviceType>
<DeviceDescription>DS-7632NXI-K2/16P</DeviceDescription><DeviceSN>DS-7632NXI-K2/16P1620211234CCRRJ12345678WCVU</DeviceSN>
<CommandPort>8000</CommandPort><HttpPort>80</HttpPort><MAC>44-19-b6-aa-bb-cc</MAC><IPv4Address>10.1.3.4</IPv4Address>
<IPv4SubnetMask>255.255.255.0</IPv4SubnetMask><IPv4Gateway>10.1.3.1</IPv4Gateway><DHCP>false</DHCP>
<AnalogChannelNum>0</AnalogChannelNum><DigitalChannelNum>32</DigitalChannelNum><SoftwareVersion>V4.83.005build 240101</SoftwareVersion>
<Activated>true</Activated></ProbeMatch>"""


def test_reply():
    d = sadp.parse_reply(REPLY)
    assert d["ip"] == "10.1.3.4" and d["kind"] == "nvr" and d["model"].startswith("DS-7632") and d["activated"] is True
    assert d["ip_channels"] == "32" and d["mac"] == "44-19-b6-aa-bb-cc"
    cam = sadp.parse_reply(REPLY.replace(b"DS-7632NXI-K2/16P</DeviceDescription>", b"DS-2CD2T43G2-2I</DeviceDescription>")
                           .replace(b"<DigitalChannelNum>32", b"<DigitalChannelNum>0").replace(b"true</Activated>", b"false</Activated>"))
    assert cam["kind"] == "camera" and cam["activated"] is False
    assert sadp.parse_reply(b"<Probe><Uuid>1</Uuid></Probe>") is None and sadp.parse_reply(b"garbage") is None
