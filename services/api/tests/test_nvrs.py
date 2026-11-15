import httpx
import pytest
from pydantic import ValidationError

from app import vault
from app.isapi import DeviceError, read_nvr
from app.nvrs import NvrIn, default_alias, host, plan_sync

DEVICE = """<DeviceInfo xmlns="http://www.hikvision.com/ver20/XMLSchema"><deviceName>NVR Gate</deviceName>
<model>DS-7732NXI-K4</model><firmwareVersion>V4.62.210</firmwareVersion><serialNumber>X1</serialNumber></DeviceInfo>"""
CHANNELS = """<InputProxyChannelList><InputProxyChannel><id>1</id><name>Gate</name><sourceInputPortDescriptor>
<ipAddress>192.168.254.2</ipAddress></sourceInputPortDescriptor></InputProxyChannel><InputProxyChannel><id>2</id>
<name>Fence</name></InputProxyChannel></InputProxyChannelList>"""
STATUS = """<InputProxyChannelStatusList><InputProxyChannelStatus><id>1</id><online>true</online></InputProxyChannelStatus>
<InputProxyChannelStatus><id>2</id><online>false</online></InputProxyChannelStatus></InputProxyChannelStatusList>"""
ISAPI = {"/ISAPI/System/deviceInfo": DEVICE, "/ISAPI/ContentMgmt/InputProxy/channels": CHANNELS,
         "/ISAPI/ContentMgmt/InputProxy/channels/status": STATUS}


def test_aliases_and_hosts():
    assert default_alias("10.1.3.4") == "nvr4" and default_alias("10.1.3.4:8080") == "nvr4"
    assert default_alias("nvr-yard.local") == "nvrnvryardlocal"[:20]
    assert host("10.1.3.4:8080") == "10.1.3.4" and host("10.1.3.4") == "10.1.3.4"


def test_form_checks():
    ok = NvrIn(address=" http://10.1.3.4/ ", username="hss", password="x")
    assert ok.address == "10.1.3.4"
    for bad in ("10.1.3.4/ISAPI", "rtsp://10.1.3.4", "a b", ""):
        with pytest.raises(ValidationError):
            NvrIn(address=bad, username="hss")
    with pytest.raises(ValidationError):
        NvrIn(address="10.1.3.4", username="hss", alias="nvr-4")      # a hyphen would break camera ids
    assert NvrIn(address="10.1.3.4", username="hss", alias="Yard2").alias == "yard2"


def test_vault_round_trip_and_rotation(tmp_path, monkeypatch):
    monkeypatch.setenv("HSS_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("HSS_VAULT_KEY", raising=False)
    vault._fernet.cache_clear()
    token = vault.encrypt("p@ss:wörd")
    assert "p@ss" not in token and vault.decrypt(token) == "p@ss:wörd"
    key_file = tmp_path / "vault.key"
    assert key_file.exists() and oct(key_file.stat().st_mode & 0o777) == "0o600"
    old = key_file.read_text().strip()
    new = vault.Fernet.generate_key().decode()
    monkeypatch.setenv("HSS_VAULT_KEY", f"{new},{old}")
    vault._fernet.cache_clear()
    assert vault.decrypt(token) == "p@ss:wörd"                          # old secrets still readable
    monkeypatch.setenv("HSS_VAULT_KEY", new)
    vault._fernet.cache_clear()
    with pytest.raises(vault.VaultError):
        vault.decrypt(token)
    vault._fernet.cache_clear()


def test_read_nvr_and_plain_errors():
    t = httpx.MockTransport(lambda r: httpx.Response(200, text=ISAPI[r.url.path]) if r.url.path in ISAPI else httpx.Response(404))
    info = read_nvr("10.1.3.4", "u", "p", transport=t)
    assert info["model"] == "DS-7732NXI-K4" and info["name"] == "NVR Gate"
    assert info["channels"] == [{"id": 1, "name": "Gate", "ip": "192.168.254.2", "online": True},
                                {"id": 2, "name": "Fence", "ip": "", "online": False}]
    assert info["warnings"] == ["drive status unavailable"]
    with pytest.raises(DeviceError, match="refused the user name or password"):
        read_nvr("10.1.3.4", "u", "bad", transport=httpx.MockTransport(lambda r: httpx.Response(401)))

    def down(r):
        raise httpx.ConnectTimeout("timed out", request=r)
    with pytest.raises(DeviceError, match="No answer"):
        read_nvr("10.1.3.4", "u", "p", transport=httpx.MockTransport(down))
    with pytest.raises(DeviceError, match="not like a Hikvision"):
        read_nvr("10.1.3.4", "u", "p", transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html")))


def test_gateway_plan_never_touches_env_paths():
    desired = {"nvr4-ch01": "rtsp://a", "nvr4-ch02": "rtsp://b", "nvr5-ch01": "rtsp://c"}
    configured = {"nvr4-ch01": "rtsp://from-env", "nvr4-ch02": "rtsp://old", "nvr9-ch01": "rtsp://x", "all_others": ""}
    owned = {"nvr4-ch02", "nvr9-ch01"}
    plan = plan_sync(desired, configured, owned)
    assert plan == {"add": ["nvr5-ch01"], "change": ["nvr4-ch02"], "remove": ["nvr9-ch01"], "env": ["nvr4-ch01"]}
