import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.isapi import parse_earliest, search_body
from app.licence import canonical, verify
from app.system import age_check, recording_days, token_checks

KEY = Ed25519PrivateKey.generate()
PUB = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()
LIC = {"id": "HSS-2026-ABC", "licensee": "Client Ltd", "site": "Main campus", "installation_id": "inst-1", "issued": "2026-11-15",
       "support_until": "2027-12-31", "max_nvrs": 7, "max_cameras": 224, "features": ["face_plate", "gps"]}


def signed(lic, key=KEY):
    return json.dumps({"licence": lic, "signature": base64.b64encode(key.sign(canonical(lic))).decode()})


def test_licence_signature():
    assert verify(signed(LIC), PUB)["max_nvrs"] == 7
    tampered = json.loads(signed(LIC))
    tampered["licence"]["max_nvrs"] = 70
    with pytest.raises(ValueError, match="not valid"):
        verify(json.dumps(tampered), PUB)
    with pytest.raises(ValueError, match="not valid"):
        verify(signed(LIC, Ed25519PrivateKey.generate()), PUB)              # someone else's key
    with pytest.raises(ValueError, match="isn't an HSS licence"):
        verify("hello", PUB)
    with pytest.raises(ValueError, match="missing"):
        verify(signed({**LIC}) .replace('"max_cameras": 224, ', ""), PUB)


def test_token_checks_never_show_values():
    env = {"HSS_WORKER_TOKEN": "change-me-too", "HSS_WALL_TOKEN": "a" * 40 + "Zx9", "HSS_WA_TOKEN": "",
           "HSS_DATABASE_URL": "postgresql://hss:change-me@db:5432/hss", "HSS_ADMIN_TOKEN": "admin@12345"}
    out = {c["id"]: c for c in token_checks(env)}
    assert out["token-HSS_WORKER_TOKEN"]["status"] == "fail" and out["token-HSS_WALL_TOKEN"]["status"] == "ok"
    assert out["token-HSS_WA_TOKEN"]["status"] == "warn" and out["db-password"]["status"] == "fail"
    assert out["admin-token"]["status"] == "warn"
    assert not any(v in json.dumps(list(out.values())) for v in ("change-me-too", "admin@12345", "change-me@"))


def test_backup_age():
    now = datetime(2026, 11, 15, 12, tzinfo=timezone.utc)
    fresh = {"status": "ok", "detail": "120 MB", "at": now - timedelta(hours=10)}
    assert age_check("b", "Backup", fresh, timedelta(hours=36), now, "")["status"] == "ok"
    assert age_check("b", "Backup", {**fresh, "at": now - timedelta(days=3)}, timedelta(hours=36), now, "")["status"] == "fail"
    assert age_check("b", "Backup", {**fresh, "status": "failed"}, timedelta(hours=36), now, "")["status"] == "fail"
    assert age_check("b", "Backup", None, timedelta(hours=36), now, "", missing_status="warn")["status"] == "warn"


def test_recording_search():
    assert "<trackID>2201</trackID>" in search_body(22, "X") and "searchResultPostion" in search_body(22, "X")
    xml = ("<CMSearchResult xmlns='http://www.hikvision.com/ver20/XMLSchema'><numOfMatches>1</numOfMatches><matchList><searchMatchItem>"
           "<trackID>2201</trackID><timeSpan><startTime>2026-10-20T08:15:02Z</startTime><endTime>2026-10-20T09:00:00Z</endTime></timeSpan>"
           "</searchMatchItem></matchList></CMSearchResult>")
    first = parse_earliest(xml)
    assert first == "2026-10-20T08:15:02Z"
    assert recording_days(first, datetime(2026, 11, 15, 8, 15, 2, tzinfo=timezone.utc)) == 26.0
    assert parse_earliest("<CMSearchResult><numOfMatches>0</numOfMatches></CMSearchResult>") is None
    assert recording_days(None, datetime.now(timezone.utc)) is None
