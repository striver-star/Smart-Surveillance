import base64

import pytest
from fastapi import HTTPException

from app.auth import check_password_rules, check_totp, hash_password, totp, verify_password, verify_totp

# RFC 6238 appendix B: SHA-1 key "12345678901234567890"
RFC_KEY = base64.b32encode(b"12345678901234567890").decode()


@pytest.mark.parametrize("t, expected8", [(59, "94287082"), (1111111109, "07081804"), (1234567890, "89005924"), (2000000000, "69279037")])
def test_totp_matches_rfc6238(t, expected8):
    assert totp(RFC_KEY, t // 30) == expected8[-6:]
    assert totp(RFC_KEY, t // 30, digits=8) == expected8


def test_totp_drift_and_single_use():
    now = 1_700_000_000.0
    step = int(now // 30)
    assert verify_totp(RFC_KEY, totp(RFC_KEY, step), None, now) == step
    assert verify_totp(RFC_KEY, totp(RFC_KEY, step - 1), None, now) == step - 1     # one step of clock drift
    assert verify_totp(RFC_KEY, totp(RFC_KEY, step - 2), None, now) is None
    assert check_totp(RFC_KEY, totp(RFC_KEY, step), step, now) == (None, True)      # already used
    assert verify_totp(RFC_KEY, "12 34 56", None, now) in (None, step - 1, step, step + 1)
    assert verify_totp(RFC_KEY, "abc", None, now) is None


def test_password_hash_round_trip_and_salt():
    h1, h2 = hash_password("correct horse battery"), hash_password("correct horse battery")
    assert h1 != h2 and h1.startswith("scrypt$")                                   # random salt
    assert verify_password("correct horse battery", h1)
    assert not verify_password("correct horse batterY", h1)
    assert not verify_password("anything", "not-a-hash")


def test_password_rules():
    check_password_rules("a long passphrase here", "operator1")
    for bad in ("short", "operator1-is-me-ok", "password1234"):
        with pytest.raises(HTTPException):
            check_password_rules(bad, "operator1")
