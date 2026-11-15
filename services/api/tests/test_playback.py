from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.playback import Sessions, day_search_body, merge_spans, nvr_time, parse_spans, playback_source

LAGOS = ZoneInfo("Africa/Lagos")
RESULT = """<CMSearchResult xmlns="http://www.hikvision.com/ver20/XMLSchema"><responseStatusStrg>MORE</responseStatusStrg>
<numOfMatches>3</numOfMatches><matchList>
<searchMatchItem><timeSpan><startTime>2026-11-15T08:00:00Z</startTime><endTime>2026-11-15T09:00:02Z</endTime></timeSpan></searchMatchItem>
<searchMatchItem><timeSpan><startTime>2026-11-15T09:00:00Z</startTime><endTime>2026-11-15T10:00:00Z</endTime></timeSpan></searchMatchItem>
<searchMatchItem><timeSpan><startTime>2026-11-15T13:30:00Z</startTime><endTime>2026-11-15T13:45:00Z</endTime></timeSpan></searchMatchItem>
</matchList></CMSearchResult>"""


def test_nvr_time_is_local_with_a_z():
    t = datetime(2026, 11, 15, 7, 30, 5, tzinfo=timezone.utc)
    assert nvr_time(t, LAGOS) == "20261115T083005Z"            # Lagos is UTC+1; Hikvision wants local time + Z
    src = playback_source("10.1.3.4", 554, "hss", "p@ss:1", 22, t, LAGOS)
    assert src == "rtsp://hss:p%40ss%3A1@10.1.3.4:554/Streaming/tracks/2201?starttime=20261115T083005Z"


def test_search_and_spans():
    body = day_search_body(22, date(2026, 11, 15), LAGOS, 100, "X")
    assert "<trackID>2201</trackID>" in body and "<startTime>2026-11-15T00:00:00Z</startTime>" in body
    assert "<endTime>2026-11-15T23:59:59Z</endTime>" in body and "<searchResultPostion>100</searchResultPostion>" in body
    spans, more = parse_spans(RESULT, LAGOS)
    assert more and len(spans) == 3 and spans[0][0] == datetime(2026, 11, 15, 8, 0, tzinfo=LAGOS)
    merged = merge_spans(spans)
    assert merged == [(datetime(2026, 11, 15, 8, 0, tzinfo=LAGOS), datetime(2026, 11, 15, 10, 0, tzinfo=LAGOS)),
                      (datetime(2026, 11, 15, 13, 30, tzinfo=LAGOS), datetime(2026, 11, 15, 13, 45, tzinfo=LAGOS))]
    assert parse_spans("<CMSearchResult><responseStatusStrg>NO MATCHES</responseStatusStrg></CMSearchResult>", LAGOS) == ([], False)


def test_idle_sessions():
    s = Sessions()
    s.add("a", {"path": "pb-1"})
    s.add("b", {"path": "pb-2"})
    s.items["a"]["touched"] -= 400
    assert s.idle() == ["a"] and s.touch("b") and not s.touch("zz")
