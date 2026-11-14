import threading
import time

from hss_probe import nvrload
from hss_probe.rtsp import RtspError, digest_header


class FakePull:
    """Delivers `rate` bytes per second; refuses or slows down by URL."""
    refuse_from = 10**6        # pulls with index >= this get "453 Not Enough Bandwidth"
    slow_after = None          # (pull count, factor) once that many pulls are open
    opened = 0
    lock = threading.Lock()

    def __init__(self, url, user, password, timeout=10):
        self.url, self.bytes = url, 0

    def open(self):
        with FakePull.lock:
            idx = FakePull.opened
            FakePull.opened += 1
        if idx >= FakePull.refuse_from:
            raise RtspError("DESCRIBE refused: 453 Not Enough Bandwidth", 453)

    def receive_until(self, deadline, stop):
        while not stop.is_set():
            factor = 1.0
            if FakePull.slow_after and FakePull.opened >= FakePull.slow_after[0]:
                factor = FakePull.slow_after[1]
            self.bytes += int(1000 * factor)
            time.sleep(0.01)

    def close(self):
        pass


def run(**kw):
    FakePull.opened = 0
    urls = nvrload.plan_urls("nvr", [1, 2, 3, 4], "sub", 12)
    return nvrload.ramp("nvr", "u", "p", urls, step=4, hold=0.3, warmup=0.05, factory=FakePull, log=lambda *a: None, **kw)


def test_plan_repeats_channels_beyond_one_each():
    urls = nvrload.plan_urls("10.1.3.5", [1, 2], "sub", 3, port=8554)
    assert urls == [("rtsp://10.1.3.5:8554/Streaming/Channels/102", "ch01"),
                    ("rtsp://10.1.3.5:8554/Streaming/Channels/202", "ch02"),
                    ("rtsp://10.1.3.5:8554/Streaming/Channels/102", "ch01#2")]


def test_no_limit():
    FakePull.refuse_from, FakePull.slow_after = 10**6, None
    r = run()
    assert r["verdict"].startswith("no limit reached") and r["max_ok_pulls"] == 12


def test_refusal_stops_the_ramp():
    FakePull.refuse_from, FakePull.slow_after = 6, None
    r = run()
    assert r["verdict"] == "first trouble at 8 pulls (DESCRIBE refused: 453 Not Enough Bandwidth)"
    assert r["max_ok_pulls"] == 4 and len(r["steps"]) == 2


def test_slowdown_counts_as_trouble():
    FakePull.refuse_from, FakePull.slow_after = 10**6, (9, 0.3)
    r = run()
    assert "first trouble at 12 pulls" in r["verdict"] and r["steps"][-1]["slowed"]


def test_digest_header_matches_rfc2617_example():
    challenge = 'Digest realm="testrealm@host.com", qop="auth", nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", opaque="5ccc069c403ebaf9f0171e9517f40e41"'
    h = digest_header(challenge, "Mufasa", "Circle Of Life", "GET", "/dir/index.html", nc=1, cnonce="0a4f113b")
    assert 'response="6629fae49393a05397450978507c4ef1"' in h
