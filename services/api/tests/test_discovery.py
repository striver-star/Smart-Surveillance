import pytest
from fastapi import HTTPException

from app.discovery import fingerprint, parse_targets


def test_targets():
    assert len(parse_targets("10.1.3.0/24")) == 254
    assert parse_targets("10.1.4.10-12, 10.1.5.7") == ["10.1.4.10", "10.1.4.11", "10.1.4.12", "10.1.5.7"]
    assert parse_targets("192.168.1.5-192.168.1.6") == ["192.168.1.5", "192.168.1.6"]
    assert parse_targets("10.0.0.1 10.0.0.1") == ["10.0.0.1"]
    for bad in ("8.8.8.0/24", "10.0.0.0/16", "10.1.1.20-10", "nonsense", "", "10.1.1.1-10.1.30.1"):
        with pytest.raises(HTTPException):
            parse_targets(bad)


def test_fingerprints():
    nvr = fingerprint([80, 554, 8000], server="DNVRS-Webs", realm="DS-7632NXI-K2", activated=True, has_activate_page=True)
    assert nvr["vendor"] == "hikvision" and nvr["kind"] == "nvr" and nvr["model_hint"] == "DS-7632NXI-K2" and not nvr["notes"]
    cam = fingerprint([80, 554, 8000], server="App-webs/", activated=False, has_activate_page=True)
    assert cam["kind"] == "camera" and "Not activated" in cam["notes"][0]
    sdk_only = fingerprint([8000], realm="")
    assert sdk_only["vendor"] is None and sdk_only["kind"] == "other"
    login_page = fingerprint([80, 8000], server="webserver", body='<a href="doc/page/login.asp">')
    assert login_page["vendor"] == "hikvision" and login_page["kind"] == "hikvision"
    other = fingerprint([554], server="")
    assert other["kind"] == "other_camera" and other["vendor"] is None
    assert fingerprint([443, 8000], server="DNVRS-Webs")["notes"] == []
