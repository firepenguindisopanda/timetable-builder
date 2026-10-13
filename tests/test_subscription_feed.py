"""
The calendar subscription route, `GET /api/timetable/calendar.ics`.

The resolving rules are pinned in test_subscription.py and the calendar text
in test_ics.py. What is pinned here is the route's contract with calendar
apps: what it refuses and how, that a republish is followed through the
token's own publication and only one the warehouse holds, that the same
publication yields the same bytes so the ETag holds, and that the token never
reaches the log.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explore_router
import main
from timetable_extractor.subscription import Token, TokenCourse, encode_token, slot_hash

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "warehouse_sessions.json").read_text()
)
COURSES = {c["code"]: c for c in FIXTURE["courses"]}
URL = "/api/timetable/calendar.ics"

#: The token's publication, and the one the warehouse now serves.
OLD_PUBLICATION, NEW_PUBLICATION = 10, 11


def _renumbered(course, offset):
    out = copy.deepcopy(course)
    for s in out["sessions"]:
        s["sessionId"] += offset
    return out


class FakeWarehouse:
    """Two publications of the fixture: the old one, and the same renumbered."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.current = {code: _renumbered(c, 40000) for code, c in COURSES.items()}
        self.old = {code: copy.deepcopy(c["sessions"]) for code, c in COURSES.items()}

    def __call__(self, fn, *args):
        self.calls.append((fn.__name__, args))
        name = fn.__name__
        if name == "course_codes":
            return list(FIXTURE["codes"])
        if name == "freshness":
            return {
                "publication_id": NEW_PUBLICATION,
                "published_at": datetime(2026, 10, 9, 13, 22, 49, tzinfo=timezone.utc),
            }
        if name == "current_semester":
            return "Semester_1_TT2026_2027"
        if name == "sessions_for_courses":
            (codes,) = args
            return [copy.deepcopy(self.current[c]) for c in codes if c in self.current]
        if name == "publication_ids":
            return [OLD_PUBLICATION, NEW_PUBLICATION]
        if name == "publication_slots":
            codes, publication_id = args
            assert publication_id == OLD_PUBLICATION
            return {c: copy.deepcopy(self.old[c]) for c in codes if c in self.old}
        raise AssertionError(f"the route asked for an unexpected query: {name}")

    def calls_to(self, name):
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def warehouse(monkeypatch):
    fake = FakeWarehouse()
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    yield fake
    explore_router.clear_cache()


@pytest.fixture
def client(warehouse):
    with TestClient(main.app) as test_client:
        yield test_client


def _lab_and_lecture():
    """COMP 2611's first lecture and lab, as the browser would encode them."""
    sessions = COURSES["COMP 2611"]["sessions"]
    lecture = next(s for s in sessions if s["type"] == "Lecture")
    lab = next(s for s in sessions if s["type"] == "Lab")
    return lecture, lab


def _token(*sessions, publication=OLD_PUBLICATION):
    picks = tuple(sorted({slot_hash(s) for s in sessions}))
    return encode_token(Token(publication, (TokenCourse("COMP 2611", picks),)))


def _events(text):
    return [block for block in text.split("BEGIN:VEVENT")[1:]]


def test_a_republish_reaches_the_calendar_under_new_ids(client):
    lecture, lab = _lab_and_lecture()
    response = client.get(URL, params={"t": _token(lecture, lab)})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/calendar")
    text = response.text
    assert "X-WR-CALNAME:UWI timetable" in text
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT6H" in text
    assert "SUMMARY:COMP 2611 Lecture" in text
    assert "SUMMARY:COMP 2611 Lab" in text
    assert "VALUE=DATE" not in text, "nothing needed a note"


def test_a_moved_class_is_followed_through_the_tokens_publication(client, warehouse):
    lecture, lab = _lab_and_lecture()
    moved = next(s for s in warehouse.current["COMP 2611"]["sessions"]
                 if s["sessionId"] == lab["sessionId"] + 40000)
    moved["day"] = "Saturday"

    text = client.get(URL, params={"t": _token(lecture, lab)}).text

    assert len(warehouse.calls_to("publication_slots")) == 1
    lab_event = next(e for e in _events(text) if "SUMMARY:COMP 2611 Lab" in e)
    assert "20260905T" in lab_event, "the lab follows to week 1's Saturday"


def test_a_token_naming_an_unknown_publication_is_not_queried(client, warehouse):
    lecture, lab = _lab_and_lecture()
    warehouse.current["COMP 2611"]["sessions"][0]["day"] = "Sunday"

    response = client.get(URL, params={"t": _token(lecture, lab, publication=999)})

    assert response.status_code == 200
    assert warehouse.calls_to("publication_slots") == []


def test_an_unchanged_timetable_never_reads_the_old_publication(client, warehouse):
    lecture, lab = _lab_and_lecture()
    client.get(URL, params={"t": _token(lecture, lab)})
    assert warehouse.calls_to("publication_slots") == []


@pytest.mark.parametrize("token", ["", "%%%", "bm90IGEgdG9rZW4", "x" * 3000])
def test_a_bad_link_is_a_plain_400(client, token):
    response = client.get(URL, params={"t": token})
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("text/plain")
    assert "calendar link" in response.text


def test_the_same_publication_gives_the_same_bytes_and_a_304(client):
    lecture, lab = _lab_and_lecture()
    first = client.get(URL, params={"t": _token(lecture, lab)})
    second = client.get(URL, params={"t": _token(lecture, lab)})
    assert first.content == second.content
    assert first.headers["etag"] == second.headers["etag"]
    assert "max-age=21600" in first.headers["cache-control"]

    again = client.get(
        URL, params={"t": _token(lecture, lab)},
        headers={"If-None-Match": first.headers["etag"]},
    )
    assert again.status_code == 304
    assert again.content == b""


def test_head_is_answered(client):
    lecture, lab = _lab_and_lecture()
    response = client.head(URL, params={"t": _token(lecture, lab)})
    assert response.status_code == 200
    assert response.headers["etag"]


def test_unknown_semester_dates_are_a_503_not_guessed_dates(client, monkeypatch):
    monkeypatch.setattr(explore_router, "teaching_calendar_context", lambda: None)
    lecture, lab = _lab_and_lecture()
    assert client.get(URL, params={"t": _token(lecture, lab)}).status_code == 503


def test_an_unreachable_warehouse_is_a_503(client, monkeypatch):
    # A calendar app keeps its last good copy through a 503, where a 500 or
    # an empty calendar would wipe the student's classes off their phone.
    def down(fn, *args):
        raise explore_router.ExplorerUnavailable("down")

    lecture, lab = _lab_and_lecture()
    client.get(URL, params={"t": _token(lecture, lab)})  # warms the semester
    explore_router.clear_cache()
    monkeypatch.setattr(explore_router, "query", down)
    monkeypatch.setattr(
        explore_router, "teaching_calendar_context",
        lambda: {"weekOne": "2026-08-31", "totalWeeks": 12},
    )
    assert client.get(URL, params={"t": _token(lecture, lab)}).status_code == 503


def test_the_log_counts_but_never_names_courses(client, caplog):
    lecture, lab = _lab_and_lecture()
    token = _token(lecture, lab)
    with caplog.at_level(logging.INFO, logger="timetable.explore"):
        client.get(URL, params={"t": token})

    record = next(r for r in caplog.records if getattr(r, "event", None) == "timetable.feed")
    assert record.courses == 1 and record.picks == 2
    # The test client's own httpx logger prints the URL it sent; only the
    # server's records are the deployment's logs.
    for r in caplog.records:
        if r.name.startswith("httpx"):
            continue
        assert token not in r.getMessage()
        assert "COMP 2611" not in json.dumps(r.__dict__, default=str)


def test_uvicorns_access_line_loses_the_token():
    """uvicorn prints the whole request target; the app's filter cuts it."""
    from timetable_extractor.observability import RedactPrivateQueries

    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", f"{URL}?t=MXwxMXxDT01Q", "1.1", 200), None,
    )
    assert RedactPrivateQueries().filter(record)
    assert record.getMessage() == f'1.2.3.4:5 - "GET {URL}?[redacted] HTTP/1.1" 200'

    other = logging.LogRecord(
        "uvicorn.access", logging.INFO, "", 0, '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "GET", "/api/timetable/sessions?codes=COMP%202611", "1.1", 200), None,
    )
    RedactPrivateQueries().filter(other)
    assert "codes=COMP%202611" in other.getMessage()


def test_the_filter_is_installed_on_uvicorns_access_logger():
    from timetable_extractor.observability import RedactPrivateQueries

    access = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, RedactPrivateQueries) for f in access.filters)
