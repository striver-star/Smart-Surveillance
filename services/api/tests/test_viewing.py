from app.viewing import MERGE_S, Merger, camera_of, stream_path


def test_only_whep_requests_are_video():
    assert stream_path("/nvr4-ch05/whep", "POST") == "nvr4-ch05"            # after the proxy strips /stream
    assert stream_path("/stream/nvr4-ch05-sub/whep", "post") == "nvr4-ch05-sub"
    assert stream_path("/pb-0123abcd/whep/9f2c-11aa", "PATCH") == "pb-0123abcd"
    assert stream_path("/nvr4-ch05/whep?x=1", "DELETE") == "nvr4-ch05"
    assert stream_path("/nvr4-ch05/", "GET") is None                         # the gateway's own test page
    assert stream_path("/nvr4-ch05/whep", "GET") is None
    assert stream_path("/../api/whep", "POST") is None
    assert stream_path("/a/b/whep", "POST") is None


def test_camera_of_sub_stream():
    assert camera_of("nvr4-ch05-sub") == "nvr4-ch05" and camera_of("nvr4-ch05") == "nvr4-ch05"


def test_reconnects_extend_one_entry():
    m = Merger()
    assert m.entry("ade", "nvr4-ch05", now=100) is None
    m.remember("ade", "nvr4-ch05", 7, now=100)
    assert m.entry("ade", "nvr4-ch05", now=100 + MERGE_S - 1) == 7          # reconnect: same line
    assert m.entry("ade", "nvr4-ch05", now=100 + 2 * MERGE_S - 2) == 7       # each reconnect moves the window on
    assert m.entry("ade", "nvr4-ch05", now=100 + 4 * MERGE_S) is None        # long gap: a new line
    assert m.entry("bola", "nvr4-ch05", now=101) is None                     # another person: their own line
