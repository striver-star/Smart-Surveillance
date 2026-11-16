from datetime import timedelta

import pytest
from fastapi import HTTPException

from app.publicapi import KEY, Bucket
from app.webhooks import check_url, next_delay, sign, verify, wants

HOOK = {"enabled": True, "events": ["alert.created", "alert.closed", "lockdown.started"], "min_severity": "warning", "cameras": []}


def test_signature_round_trip_and_tampering():
    body = b'{"type":"alert.created"}'
    h = sign("whsec_x", body, 1_800_000_000)
    assert verify("whsec_x", body, h, 1_800_000_100)
    assert not verify("whsec_x", body + b" ", h, 1_800_000_100)          # body changed
    assert not verify("whsec_y", body, h, 1_800_000_100)                 # wrong secret
    assert not verify("whsec_x", body, h, 1_800_000_000 + 301)           # too old: replay
    assert not verify("whsec_x", body, "garbage", 1_800_000_000)


def test_retry_schedule():
    assert next_delay(1) == timedelta(minutes=1) and next_delay(5) == timedelta(hours=6) and next_delay(6) is None


def test_which_events_a_hook_takes():
    assert wants(HOOK, "alert.created", "critical", "nvr4-ch22")
    assert not wants(HOOK, "alert.created", "info", "nvr4-ch22")           # below the minimum severity
    assert not wants(HOOK, "alert.acknowledged", "critical", "nvr4-ch22")  # not subscribed
    assert wants(HOOK, "lockdown.started", None, None)
    gate = {**HOOK, "cameras": ["nvr4-*"]}
    assert wants(gate, "alert.closed", "warning", "nvr4-ch05") and not wants(gate, "alert.closed", "warning", "nvr1-ch05")
    assert not wants({**HOOK, "enabled": False}, "alert.created", "critical", "x")


def test_urls():
    assert check_url("https://203.0.113.10/hook") and check_url("http://10.1.3.50:8080/hss")
    for bad in ("ftp://x.example/h", "http://api:8000/x", "http://127.0.0.1/x", "http://169.254.169.254/latest", "http://8.8.8.8/hook", "nonsense"):
        with pytest.raises(HTTPException):
            check_url(bad)


def test_key_format_and_rate_limit():
    assert KEY.match("hss_0123456789ab_" + "A" * 43) and not KEY.match("hss_short_x") and not KEY.match("Bearer hss_0123456789ab_x")
    b = Bucket(3)
    assert all(b.take("k", now=t) for t in (0, 1, 2)) and not b.take("k", now=3)
    assert b.take("k", now=61) and b.take("other", now=3)
