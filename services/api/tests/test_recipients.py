import pytest
from fastapi import HTTPException

from app.notify import RecipientIn, TOPIC_TEXT, TOPICS, _clean


def test_numbers_are_tidied_and_checked():
    r = _clean(RecipientIn(name=" CSO ", whatsapp="+234 801 234-5678", subscriptions=["critical", "critical", "lockdown"]))
    assert r.whatsapp == "+2348012345678" and r.name == "CSO" and r.subscriptions == ["critical", "lockdown"]
    assert _clean(RecipientIn(name="IT", whatsapp="002348012345678")).whatsapp == "+2348012345678"
    for bad in ("08012345678", "+0801", "+234801234567890123"):
        with pytest.raises(HTTPException):
            _clean(RecipientIn(name="X Y", whatsapp=bad))


def test_needs_a_way_to_reach_them_and_known_topics():
    with pytest.raises(HTTPException):
        _clean(RecipientIn(name="Nobody"))
    with pytest.raises(HTTPException):
        _clean(RecipientIn(name="Bad mail", email="not-an-email"))
    with pytest.raises(HTTPException):
        _clean(RecipientIn(name="GM", email="gm@example.com", subscriptions=["everything"]))
    assert _clean(RecipientIn(name="GM", email="gm@example.com", subscriptions=["weekly"])).email == "gm@example.com"
    assert set(TOPIC_TEXT) == TOPICS                      # every message type has a plain description
