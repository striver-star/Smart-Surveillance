import httpx
import pytest
from fastapi import HTTPException

from app.ptz import Control, continuous_xml, parse_presets, parse_target, preset_xml, supports_ptz

PRESETS = """<PTZPresetList xmlns="http://www.hikvision.com/ver20/XMLSchema">
<PTZPreset><id>1</id><presetName>Main gate</presetName><enabled>true</enabled></PTZPreset>
<PTZPreset><id>2</id><presetName>Preset 2</presetName></PTZPreset>
<PTZPreset><id>3</id><presetName>Fence east</presetName></PTZPreset>
<PTZPreset><id>4</id><presetName>Old</presetName><enabled>false</enabled></PTZPreset></PTZPresetList>"""


def test_xml_and_parsing():
    assert "<pan>-50</pan><tilt>20</tilt><zoom>0</zoom>" in continuous_xml(-50, 20, 0)
    assert "<presetName>Gate &amp;</presetName>" not in preset_xml(3, "Gate <&>") and "<id>3</id>" in preset_xml(3, "Gate")
    assert parse_presets(PRESETS) == [{"id": 1, "name": "Main gate"}, {"id": 3, "name": "Fence east"}]
    assert parse_target("nvr4-ch05:3") == ("nvr4-ch05", 3) and parse_target("nvr4-ch05") is None
    assert parse_target("NVR4-ch05:3") is None


def test_capabilities():
    assert supports_ptz("<PTZChanelCap><ContinuousPanTiltSpace><XRange/></ContinuousPanTiltSpace></PTZChanelCap>")
    assert not supports_ptz("<PTZChanelCap></PTZChanelCap>")                       # fixed camera
    assert not supports_ptz("<ResponseStatus><statusString>Invalid Operation</statusString></ResponseStatus>")


def test_one_person_steers_and_override():
    c = Control()
    op1, op2, cso = {"username": "ada", "role": "operator"}, {"username": "bayo", "role": "operator"}, {"username": "cso", "role": "cso"}
    c.claim("nvr4-ch05", op1, now=100)
    with pytest.raises(HTTPException) as e:
        c.claim("nvr4-ch05", op2, now=110)
    assert e.value.status_code == 409 and "ada is steering" in e.value.detail
    c.claim("nvr4-ch05", op2, now=131)                                              # 30 s after the last command
    c.claim("nvr4-ch05", cso, now=132)                                              # CSO takes over at once
    c.claim("nvr4-ch06", op1, now=132)                                              # other cameras are free


def test_deadman_stop():
    import time
    c, stopped = Control(), []
    c.arm_stop("nvr4-ch05", lambda: stopped.append(1))
    time.sleep(0.5)
    c.arm_stop("nvr4-ch05", lambda: stopped.append(2))                             # a repeat resets the timer
    time.sleep(1.2)
    assert stopped == []
    time.sleep(0.5)
    assert stopped == [2]
    c.arm_stop("nvr4-ch05", lambda: stopped.append(3))
    c.disarm("nvr4-ch05")                                                          # released: no extra stop
    time.sleep(1.7)
    assert stopped == [2]
