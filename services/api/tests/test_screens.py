import pytest
from pydantic import ValidationError

from app.screens import ScreenIn, build_pages, grid_shape, resolve_cameras

AVAIL = [f"nvr4-ch{i:02d}" for i in range(1, 33)] + [f"nvr5-ch{i:02d}" for i in range(1, 17)]


def test_sources():
    assert len(resolve_cameras("all", [], AVAIL)) == 48
    assert resolve_cameras("nvr:nvr5", [], AVAIL) == [f"nvr5-ch{i:02d}" for i in range(1, 17)]
    assert resolve_cameras("nvr:nvr4", [], AVAIL)[0] == "nvr4-ch01" and len(resolve_cameras("nvr:nvr4", [], AVAIL)) == 32
    assert resolve_cameras("cameras", ["nvr5-ch03", "nvr4-ch22", "nvr5-ch03"], AVAIL) == ["nvr5-ch03", "nvr4-ch22"]


def test_nvr_screen_fits_one_page_of_32():
    pages = build_pages(resolve_cameras("nvr:nvr4", [], AVAIL), 32, [])
    assert len(pages) == 1 and len(pages[0]) == 32
    assert grid_shape(32) == (8, 4) and grid_shape(16) == (4, 4) and grid_shape(6) == (3, 2)


def test_rotation_pages_and_alert_pinning():
    cams = resolve_cameras("all", [], AVAIL)
    pages = build_pages(cams, 16, [])
    assert len(pages) == 3 and [len(p) for p in pages] == [16, 16, 16]
    pinned = build_pages(cams, 16, ["nvr5-ch09", "nvr4-ch22", "not-on-this-screen"])
    assert all(p[:2] == ["nvr5-ch09", "nvr4-ch22"] for p in pinned)          # alert cameras lead every page
    assert sum(len(p) - 2 for p in pinned) == 46                              # everyone else still shown once
    assert len(pinned) == 4
    assert build_pages(["a", "b"], 4, ["a", "b"]) == [["a", "b"]]
    assert build_pages([], 16, []) == [[]]
    assert build_pages(["a", "b", "c"], 1, ["c"]) == [["c"]]                  # single tile: the alert wins


def test_screen_form():
    assert ScreenIn(name="Gate", source="nvr:nvr4", tiles=32).tiles == 32
    for bad in ({"tiles": 12}, {"source": "nvr:NVR-4"}, {"source": "x"}, {"cameras": ["../etc"]}, {"dwell_s": 2}):
        with pytest.raises(ValidationError):
            ScreenIn(name="x", **bad)


def test_cache_keeps_last_good_value_through_a_short_outage(monkeypatch):
    import pytest
    from app import screens
    clock = [1000.0]
    monkeypatch.setattr(screens.time, "monotonic", lambda: clock[0])
    screens._cache.pop("t", None)
    assert screens._cached("t", 15, lambda: ["cam1"]) == ["cam1"]

    def down():
        raise RuntimeError("gateway restarting")
    clock[0] += 60
    assert screens._cached("t", 15, down) == ["cam1"]          # stale, but the wall keeps its cameras
    clock[0] += 600
    with pytest.raises(RuntimeError):
        screens._cached("t", 15, down)                       # too old: the error goes through
