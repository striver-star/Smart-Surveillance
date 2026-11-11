import re

import httpx
import pytest

from hss_probe import streams
from hss_probe.isapi import IsapiClient

NS = 'xmlns="http://www.hikvision.com/ver20/XMLSchema"'


def stream_xml(sid, codec):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<StreamingChannel version="2.0" {NS}><id>{sid}</id>'
            f'<channelName>cam</channelName><Video><enabled>true</enabled><videoCodecType>{codec}</videoCodecType>'
            f'<videoResolutionWidth>640</videoResolutionWidth><constantBitRate>512</constantBitRate></Video>'
            f'<Audio><audioCompressionType>G.711ulaw</audioCompressionType></Audio></StreamingChannel>')


class FakeNVR:
    """Channels: 1 sub H.265, 2 sub H.264 already, 3 sub H.265 but H.265-only camera, 4 offline."""

    def __init__(self):
        self.streams = {101: "H.264", 102: "H.265", 201: "H.265", 202: "H.264", 301: "H.264", 302: "H.265",
                        401: "H.265", 402: "H.265"}
        self.puts = []

    def __call__(self, req: httpx.Request) -> httpx.Response:
        p = req.url.path
        if p == "/ISAPI/ContentMgmt/InputProxy/channels/status":
            body = "".join(f"<InputProxyChannelStatus><id>{c}</id><online>{'false' if c == 4 else 'true'}</online>"
                           f"</InputProxyChannelStatus>" for c in range(1, 5))
            return httpx.Response(200, text=f"<InputProxyChannelStatusList {NS}>{body}</InputProxyChannelStatusList>")
        if p == "/ISAPI/ContentMgmt/InputProxy/channels":
            body = "".join(f"<InputProxyChannel><id>{c}</id><name>Cam {c}</name></InputProxyChannel>" for c in range(1, 5))
            return httpx.Response(200, text=f"<InputProxyChannelList {NS}>{body}</InputProxyChannelList>")
        if p == "/ISAPI/ContentMgmt/StreamingProxy/channels":
            body = "".join(stream_xml(s, c).split("?>\n", 1)[1] for s, c in self.streams.items())
            return httpx.Response(200, text=f"<StreamingChannelList {NS}>{body}</StreamingChannelList>")
        m = re.fullmatch(r"/ISAPI/ContentMgmt/StreamingProxy/channels/(\d+)(/capabilities)?", p)
        if m:
            sid = int(m.group(1))
            if m.group(2):
                opt = "H.265" if sid == 302 else "H.264,H.265"
                return httpx.Response(200, text=f'<StreamingChannel {NS}><Video><videoCodecType opt="{opt}">x</videoCodecType></Video></StreamingChannel>')
            if req.method == "PUT":
                body = req.content.decode()
                assert NS in body and "<Audio>" in body, "other settings must be sent back unchanged"
                self.puts.append(sid)
                self.streams[sid] = re.search(r"<videoCodecType>([^<]+)<", body).group(1)
                return httpx.Response(200, text="<ResponseStatus><statusCode>1</statusCode><subStatusCode>ok</subStatusCode></ResponseStatus>")
            return httpx.Response(200, text=stream_xml(sid, self.streams[sid]))
        return httpx.Response(404, text="")


@pytest.fixture
def nvr(monkeypatch):
    fake = FakeNVR()
    monkeypatch.setattr(streams, "IsapiClient",
                        lambda base, u, p, **kw: IsapiClient(base, u, p, transport=httpx.MockTransport(fake)))
    monkeypatch.setenv("HSS_NVR_USER", "u")
    monkeypatch.setenv("HSS_NVR_PASSWORD", "p")
    monkeypatch.setattr(streams.time, "sleep", lambda s: None)
    return fake


def test_with_codec_changes_only_the_codec():
    xml = stream_xml(102, "H.265")
    out = streams.with_codec(xml, "H.264")
    assert out == xml.replace("<videoCodecType>H.265<", "<videoCodecType>H.264<")


def test_dry_run_changes_nothing(nvr, tmp_path, capsys):
    assert streams.main(["--host", "nvr", "--sub-h264", "--backup-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert nvr.puts == [] and not any(tmp_path.iterdir())
    assert "1 stream(s) would change" in out
    assert "already H.264" in out and "does not offer H.264" in out and "camera offline" in out


def test_apply_changes_backs_up_and_restores(nvr, tmp_path, capsys):
    assert streams.main(["--host", "nvr", "--sub-h264", "--apply", "--backup-dir", str(tmp_path)]) == 0
    assert nvr.puts == [102] and nvr.streams[102] == "H.264"
    assert nvr.streams[101] == "H.264" and nvr.streams[201] == "H.265", "main streams untouched"
    run = next(tmp_path.iterdir())
    assert (run / "nvr" / "102.xml").read_text().count("H.265") == 1
    assert "changed" in (run / "report.csv").read_text()
    assert streams.main(["--restore", str(run), "--apply"]) == 0
    assert nvr.streams[102] == "H.265"


def test_main_h265_and_channel_filter(nvr, tmp_path):
    assert streams.main(["--host", "nvr", "--main-h265", "--channels", "1-3", "--apply", "--backup-dir", str(tmp_path)]) == 0
    assert sorted(nvr.puts) == [101, 301] and nvr.streams[401] == "H.265"


def test_parse_channels():
    assert streams.parse_channels("1-3,7") == {1, 2, 3, 7}
    assert streams.parse_channels(None) is None
