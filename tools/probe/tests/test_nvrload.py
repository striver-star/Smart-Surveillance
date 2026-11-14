import threading
import time

from hss_probe import nvrload
from hss_probe.rtsp import RtspError, digest_header


class FakePull:
    """Delivers video in real time; can refuse, fall behind or skip packets once enough pulls are open."""
    refuse_from = 10**6        # pulls with index >= this get "453 Not Enough Bandwidth"
    slow_after = None          # (pull count, share of real time delivered) once that many pulls are open
    lossy_after = None         # (pull count, share of packets skipped)
    dead_urls = set()          # cameras whose own stream never flows
    opened = 0
    lock = threading.Lock()

    def __init__(self, url, user, password, timeout=10):
        self.url, self.bytes, self.media_seconds, self.video_packets, self.lost = url, 0, 0.0, 0, 0

    def open(self):
        with FakePull.lock:
            idx = FakePull.opened
            FakePull.opened += 1
        if idx >= FakePull.refuse_from:
            raise RtspError("DESCRIBE refused: 453 Not Enough Bandwidth", 453)

    def receive_until(self, deadline, stop):
        last = time.monotonic()
        while not stop.is_set():
            time.sleep(0.01)
            now = time.monotonic()
            if self.url in FakePull.dead_urls:
                last = now
                continue
            factor = 1.0
            if FakePull.slow_after and FakePull.opened >= FakePull.slow_after[0]:
                factor = FakePull.slow_after[1]
            self.media_seconds += (now - last) * factor
            self.bytes += 1000
            self.video_packets += 10
            if FakePull.lossy_after and FakePull.opened >= FakePull.lossy_after[0]:
                self.lost += round(10 * FakePull.lossy_after[1] / (1 - FakePull.lossy_after[1]))
            last = now

    def close(self):
        pass


def reset():
    FakePull.opened, FakePull.refuse_from, FakePull.slow_after, FakePull.lossy_after = 0, 10**6, None, None
    FakePull.dead_urls = set()


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
    reset()
    r = run()
    assert r["verdict"].startswith("no limit reached") and r["max_ok_pulls"] == 12


def test_refusal_stops_the_ramp():
    reset()
    FakePull.refuse_from = 6
    r = run()
    assert r["verdict"] == "first trouble at 8 pulls (ch03#2: DESCRIBE refused: 453 Not Enough Bandwidth)"
    assert r["max_ok_pulls"] == 4 and len(r["steps"]) == 2


def test_falling_behind_real_time_counts_as_trouble():
    reset()
    FakePull.slow_after = (9, 0.6)
    r = run()
    assert "first trouble at 12 pulls" in r["verdict"] and r["steps"][-1]["behind"]


def test_skipped_packets_count_as_trouble():
    reset()
    FakePull.lossy_after = (5, 0.05)
    r = run()
    assert "first trouble at 8 pulls" in r["verdict"] and "packets skipped" in r["steps"][-1]["lossy"][0]


def test_precheck_sets_aside_faulty_cameras():
    reset()
    urls = nvrload.plan_urls("nvr", [1, 2, 3], "main", 3)
    FakePull.dead_urls = {urls[1][0]}
    healthy, problems = nvrload.precheck("u", "p", urls, seconds=0.4, factory=FakePull, log=lambda *a: None)
    assert [lbl for _, lbl in healthy] == ["ch01", "ch03"]
    assert "camera stream not flowing" in problems["ch02"]


def test_rtp_timestamps_and_sequence_gaps():
    from hss_probe.rtsp import RtspPull
    p = RtspPull("rtsp://x/y")

    def pkt(seq, ts):
        rtp = bytes([0x80, 96]) + seq.to_bytes(2, "big") + ts.to_bytes(4, "big") + b"\0" * 4 + b"x" * 20
        return b"$\x00" + len(rtp).to_bytes(2, "big") + rtp
    p._buf = pkt(65534, 2**32 - 1800) + pkt(65535, 2**32 - 1800) + pkt(1, 1800) + pkt(2, 5400)  # wraps, one lost
    for _ in range(4):
        p._skip_interleaved()
    assert p.lost == 1 and p.video_packets == 4
    assert abs(p.media_seconds - 7200 / 90000) < 1e-9


def test_digest_header_matches_rfc2617_example():
    challenge = 'Digest realm="testrealm@host.com", qop="auth", nonce="dcd98b7102dd2f0e8b11d0f600bfb0c093", opaque="5ccc069c403ebaf9f0171e9517f40e41"'
    h = digest_header(challenge, "Mufasa", "Circle Of Life", "GET", "/dir/index.html", nc=1, cnonce="0a4f113b")
    assert 'response="6629fae49393a05397450978507c4ef1"' in h
