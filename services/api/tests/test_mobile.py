import pytest
from pydantic import ValidationError

from app.auth import ROLES
from app.logbook import CONTROL, READERS, WRITERS
from app.mobile import MAX_ACCURACY_M, PEOPLE, Position, SosIn


def test_guard_role_is_phone_only():
    assert "guard" in ROLES and "guard" in PEOPLE
    assert "guard" in WRITERS and "guard" in READERS and "guard" not in CONTROL      # no shift handover
    assert "management" not in PEOPLE


def test_positions_are_checked():
    assert Position(lat=6.5, lon=3.35, accuracy=8).lat == 6.5
    for bad in ({"lat": 91, "lon": 0}, {"lat": 0, "lon": 181}):
        with pytest.raises(ValidationError):
            Position(**bad)
    assert MAX_ACCURACY_M == 50


def test_sos_without_location_is_allowed():
    s = SosIn()
    assert s.lat is None and s.lon is None
