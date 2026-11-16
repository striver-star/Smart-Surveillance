from datetime import datetime, timedelta, timezone

from app.control import live_camera, order_alerts, stream_path

T = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def a(i, sev, status, mins, cam="nvr1-ch01"):
    return {"id": i, "severity": sev, "status": status, "created_at": T - timedelta(minutes=mins), "camera_id": cam}


def test_unacknowledged_critical_first_then_newest():
    rows = [a(1, "warning", "open", 1), a(2, "critical", "acknowledged", 0), a(3, "critical", "open", 30), a(4, "critical", "open", 5)]
    assert [x["id"] for x in order_alerts(rows)] == [4, 3, 1, 2]


def test_live_camera_prefers_waiting_critical():
    rows = order_alerts([a(1, "critical", "acknowledged", 0, "nvr1-ch02"), a(2, "critical", "open", 9, "nvr4-ch22"), a(3, "warning", "open", 0)])
    assert live_camera(rows) == "nvr4-ch22"
    assert live_camera(order_alerts([a(1, "critical", "acknowledged", 0, "nvr1-ch02")])) == "nvr1-ch02"
    assert live_camera([a(3, "warning", "open", 0)]) is None


def test_stream_path_prefers_sub_stream():
    assert stream_path("nvr4-ch22", ["nvr4-ch22", "nvr4-ch22-sub"]) == "nvr4-ch22-sub"
    assert stream_path("nvr4-ch22", ["nvr4-ch22"]) == "nvr4-ch22"
    assert stream_path("nvr4-ch22", []) is None
