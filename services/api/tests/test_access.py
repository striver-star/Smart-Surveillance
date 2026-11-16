import pytest
from fastapi import HTTPException

from app.access import allowed, can_play_back, clean_patterns, patterns, sql


def u(role, cams=(), playback=True):
    return {"role": role, "cameras": list(cams), "can_playback": playback}


def test_admin_and_cso_see_everything():
    assert patterns(u("admin", ["nvr1-*"])) is None and patterns(u("cso")) is None
    assert allowed(u("cso", ["nvr1-*"]), "nvr4-ch22")


def test_empty_list_means_all_cameras():
    assert patterns(u("operator")) is None and allowed(u("operator"), "anything")


def test_patterns_and_sub_streams():
    v = u("viewer", ["nvr4-*", "nvr1-ch05"])
    assert allowed(v, "nvr4-ch22") and allowed(v, "nvr4-ch22-sub") and allowed(v, "NVR4-CH01")
    assert allowed(v, "nvr1-ch05") and not allowed(v, "nvr1-ch50") and not allowed(v, "nvr1-ch05x")
    assert not allowed(v, None) and not allowed(v, "")


def test_sql_fragment():
    assert sql(u("operator"), "camera_id") == ("", [])
    where, args = sql(u("client", ["nvr4-*", "gate_cam?"]), "e.camera_id")
    assert where == " AND lower(e.camera_id) LIKE ANY(%s)"
    assert args == [["nvr4-%", "gate\\_cam_"]]           # _ is escaped, ? becomes _


def test_playback_switch():
    assert can_play_back(u("client")) and not can_play_back(u("client", playback=False))
    assert not can_play_back(u("management")) and not can_play_back(u("guard"))


def test_clean_patterns():
    assert clean_patterns([" nvr4-* ", "nvr4-*", "", "nvr1-ch05"]) == ["nvr4-*", "nvr1-ch05"]
    with pytest.raises(HTTPException):
        clean_patterns(["nvr4; drop"])
