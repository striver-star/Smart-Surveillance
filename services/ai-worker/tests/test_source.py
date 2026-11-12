import time
from pathlib import Path

import pytest

from worker.source import LatestFrameReader

VIDEO = Path(__file__).resolve().parents[3] / "demo" / "media" / "vtest.avi"


@pytest.mark.skipif(not VIDEO.exists(), reason="run tools/fetch-models.sh --demo first")
def test_reader_keeps_only_the_newest_frame():
    r = LatestFrameReader(str(VIDEO), "file").start()
    deadline = time.time() + 10
    while r.decoded_frames < 20 and time.time() < deadline:
        time.sleep(0.05)
    f = r.latest()
    r.stop()
    assert f is not None and f.image.shape == (576, 768, 3)
    assert r.latest(newer_than=f.seq + 10**6) is None


def test_unreachable_camera_reconnects_without_crashing():
    r = LatestFrameReader("rtsp://127.0.0.1:9/none", "dead").start()
    time.sleep(1.5)
    r.stop()
    assert r.connected is False and r.latest() is None
