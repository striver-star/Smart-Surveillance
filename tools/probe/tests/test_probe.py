import csv
import json
from pathlib import Path

import httpx
import pytest

from hss_probe import cli
from hss_probe.collect import ENDPOINTS, collect
from hss_probe.isapi import IsapiClient
from hss_probe.report import nvr_numbers

FIXTURES = Path(__file__).parent / "fixtures"
ROUTES = {path: f"{key}.xml" for key, path in ENDPOINTS.items()}
ROUTES.update({f"/ISAPI/Event/channels/{n}/capabilities": f"channel_{n}_event_caps.xml" for n in range(1, 5)})
ROUTES["/ISAPI/Event/notification/alertStream"] = "alert_stream.txt"


def fake_nvr(request: httpx.Request) -> httpx.Response:
    assert request.method == "GET", "the probe must never change a device"
    name = ROUTES.get(request.url.path)
    if name is None:
        return httpx.Response(404, text="<ResponseStatus><statusCode>4</statusCode></ResponseStatus>")
    return httpx.Response(200, text=(FIXTURES / name).read_text())


def make_client(*args, **kwargs):
    return IsapiClient(*args, transport=httpx.MockTransport(fake_nvr), **kwargs)


@pytest.fixture
def inventory():
    client = make_client("http://nvr", "user", "pw")
    inv, raw = collect(client, "nvr", listen_seconds=1)
    return inv, raw


def test_device_and_storage(inventory):
    inv, _ = inventory
    assert inv["device"]["model"] == "DS-7632NXI-K2/16P"
    assert inv["device"]["firmware"] == "V4.62.210"
    assert [d["capacity_gb"] for d in inv["storage"]] == [7452.0, 7452.0]
    assert inv["time"]["mode"] == "NTP"


def test_streams_and_tiers(inventory):
    inv, _ = inventory
    ch = {c["id"]: c for c in inv["channels"]}
    assert ch[1]["streams"]["main"]["codec"] == "H.265"
    assert ch[1]["streams"]["main"]["fps"] == 25
    assert ch[2]["streams"]["main"]["bitrate_kbps"] == 2048          # CBR uses constantBitRate
    assert ch[3]["streams"]["sub"]["bitrate_kbps"] == 768            # VBR uses the upper cap
    assert ch[1]["tier"] == "E/N" and ch[1]["recognition_events"] == ["facesnap"]
    assert ch[3]["tier"] == "S"
    assert ch[4]["tier"] == "unknown" and "camera offline" in ch[4]["flags"]
    assert any("sub-stream is H.265" in f for f in ch[2]["flags"])
    assert any("platform image checks" in f for f in ch[3]["flags"])


def test_events_heard(inventory):
    inv, raw = inventory
    assert inv["events_heard"]["counts"] == {"linedetection @ ch1": 1, "videoloss @ ch0": 1}
    assert "event_0000.xml" in raw


def test_retention_numbers(inventory):
    inv, _ = inventory
    n = nvr_numbers(inv, target_days=30)
    assert n["main_mbps"] == 11.3
    assert n["retention_days"] == pytest.approx(122.5, abs=0.2)
    assert n["tiers"]["E/N"] == 2


def test_cli_writes_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(cli, "IsapiClient", make_client)
    monkeypatch.setenv("HSS_NVR_USER", "user")
    monkeypatch.setenv("HSS_NVR_PASSWORD", "pw")
    assert cli.main(["--host", "10.0.0.10", "--out", str(tmp_path)]) == 0
    rows = list(csv.DictReader((tmp_path / "compatibility-matrix.csv").open()))
    assert len(rows) == 4 and rows[0]["nvr_model"] == "DS-7632NXI-K2/16P"
    assert json.loads((tmp_path / "inventory.json").read_text())[0]["address"] == "10.0.0.10"
    summary = (tmp_path / "summary.md").read_text()
    assert "meets the 30 day target" in summary
    assert (tmp_path / "raw" / "10.0.0.10" / "device_info.xml").exists()


def test_unreachable_nvr_does_not_crash():
    def down(request):
        raise httpx.ConnectError("refused")
    client = IsapiClient("http://nvr", "u", "p", transport=httpx.MockTransport(down))
    inv, _ = collect(client, "nvr")
    assert inv["channels"] == [] and inv["device"]["model"] == ""
