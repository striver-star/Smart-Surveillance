import time

import httpx
import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.outputs import Active, OutputIn, relay_xml, switch


def test_relay_xml():
    assert "<outputState>high</outputState>" in relay_xml(True) and "<outputState>low</outputState>" in relay_xml(False)


def test_http_output_switches_and_reports():
    seen = []
    t = httpx.MockTransport(lambda r: (seen.append((r.method, str(r.url))), httpx.Response(200))[1])
    o = {"kind": "http", "url_on": "http://10.1.9.5/relay/0?turn=on", "url_off": "http://10.1.9.5/relay/0?turn=off",
         "method": "GET", "username": "", "secret": ""}
    switch(o, True, transport=t)
    switch(o, False, transport=t)
    assert seen == [("GET", "http://10.1.9.5/relay/0?turn=on"), ("GET", "http://10.1.9.5/relay/0?turn=off")]
    switch({**o, "url_off": None}, False, transport=t)                     # no 'off' address: nothing sent
    assert len(seen) == 2
    with pytest.raises(HTTPException, match="HTTP 500"):
        switch(o, True, transport=httpx.MockTransport(lambda r: httpx.Response(500)))


def test_auto_off_and_silence_by_alert():
    a, offs = Active(), []
    a.start({"id": 1, "name": "Gate siren", "duration_s": 1}, "alert-1", "alert rule", lambda: offs.append(1))
    a.start({"id": 2, "name": "Floodlight", "duration_s": 0}, "alert-1", "alert rule", lambda: offs.append(2))
    a.start({"id": 3, "name": "Fence strobe", "duration_s": 0}, "alert-2", "alert rule", lambda: offs.append(3))
    assert sorted(a.for_alert("alert-1")) == [1, 2] and a.for_alert("alert-2") == [3]
    time.sleep(1.3)
    assert offs == [1] and 1 not in a.snapshot()                            # timed output switched itself off
    assert a.snapshot()[2]["until"] is None                                 # duration 0 stays on
    a.start({"id": 2, "name": "Floodlight", "duration_s": 0}, "alert-3", "alert rule", lambda: None)
    assert a.snapshot()[2]["alerts"] == ["alert-1", "alert-3"]              # a second alert keeps it on too
    assert a.stop(2) and 2 not in a.snapshot()


def test_form():
    assert OutputIn(name="Gate siren", kind="nvr_relay", nvr_alias="nvr4", port=1).port == 1
    for bad in ({"name": "a,b"}, {"kind": "smoke"}, {"url_on": "ftp://x"}, {"duration_s": 99999}):
        with pytest.raises(ValidationError):
            OutputIn(**{"name": "x", "kind": "http", **bad})
