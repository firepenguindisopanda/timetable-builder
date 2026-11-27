"""
`?term=` on the explorer and the timetable API (SEMESTERS-SPEC.md 7.3).

Phase 2's promise: `/explore?term=2026-27-s2` shows the semester 2
inspection copy with its 13 weeks, `/explore` with no term is unchanged, and
an unknown term is a 404 rather than the default term passed off as the one
asked for. The warehouse is faked, as in test_changes_api.py.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import explore_router
import main

S1 = ("2026/2027", 1)
S2 = ("2026/2027", 2)
NOV_27 = datetime(2026, 11, 27, 12, 46, 4, tzinfo=timezone.utc)


class FakeWarehouse:
    """Two terms held; records the term every query was asked for."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []
        self.held = [
            {"term": S1, "publication_id": 16, "stage": "final", "published_at": NOV_27},
            {"term": S2, "publication_id": 21, "stage": "inspection", "published_at": NOV_27},
        ]

    def terms_for(self, name: str) -> list[tuple]:
        return [args[0] for called, args in self.calls if called == name]

    def __call__(self, fn, *args):
        name = fn.__name__
        self.calls.append((name, args))
        if name == "held_terms":
            return self.held
        term = args[0]
        publication = 16 if term == S1 else 21
        if name == "freshness":
            return {"publication_id": publication, "published_at": NOV_27,
                    "stage": "final" if term == S1 else "inspection"}
        if name == "changes_for_page":
            return None
        if name == "room_index":
            return [{"code": "FST C1", "sessions": 3, "courses": 1,
                     "days": ["Monday"], "hours_per_week": 3}]
        if name == "course_codes":
            return ["ACCT 1002"]
        if name == "sessions_for_courses":
            return [{"code": "ACCT 1002", "title": "Accounting", "sessions": []}]
        if name == "changes_for_courses":
            return None
        if name == "free_rooms_page":
            return {"rooms": ["FST C1"], "bookings": []}
        if name == "course_index":
            return []
        raise AssertionError(f"unexpected query {name}")


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


# Pages


def test_no_term_is_the_default_term_and_its_links_carry_none(client, warehouse):
    html = client.get("/explore/rooms").text
    assert warehouse.terms_for("room_index") == [S1]
    assert 'href="/explore/room/FST%20C1"' in html
    assert "term=" not in html.split('class="term-switch"')[0]


def test_a_named_term_is_read_and_its_links_stay_in_it(client, warehouse):
    html = client.get("/explore/rooms", params={"term": "2026-27-s2"}).text
    assert warehouse.terms_for("room_index") == [S2]
    assert warehouse.terms_for("freshness") == [S2]
    assert 'href="/explore/room/FST%20C1?term=2026-27-s2"' in html
    assert 'href="/explore/staff?term=2026-27-s2"' in html
    assert 'data-term="2026-27-s2"' in html


def test_the_switch_lists_both_terms_and_marks_the_one_shown(client):
    html = client.get("/explore/rooms", params={"term": "2026-27-s2"}).text
    switch = html.split('class="term-switch"', 1)[1].split("</nav>", 1)[0]
    assert '<a href="/explore/rooms">Semester 1 2026/27</a>' in switch
    assert (
        '<a href="/explore/rooms?term=2026-27-s2" aria-current="page">'
        "Semester 2 2026/27 (inspection copy)</a>"
    ) in switch


def test_the_switch_links_a_course_with_spaces_and_an_ampersand(client):
    """The path arrives decoded; the switch's links must not."""
    request = type("R", (), {"url": type("U", (), {"path": "/explore/course/FOUN 1001 (FULL & PART-TIME)"})()})()
    explore_router.clear_cache()
    links = explore_router.term_switch(request, S1)
    assert links[1]["href"] == "/explore/course/FOUN%201001%20%28FULL%20%26%20PART-TIME%29?term=2026-27-s2"


def test_one_term_held_shows_no_switch(client, warehouse):
    warehouse.held = warehouse.held[:1]
    assert 'class="term-switch"' not in client.get("/explore/rooms").text


def test_each_term_is_cached_apart(client, warehouse):
    for _ in range(2):
        client.get("/explore/rooms")
        client.get("/explore/rooms", params={"term": "2026-27-s2"})
    assert warehouse.terms_for("room_index") == [S1, S2]


@pytest.mark.parametrize(
    ("term", "says"),
    [
        ("2027-28-s1", "No timetable is loaded for Semester 1 2027/28."),
        ("semester-2", "There is no term &#39;semester-2&#39;."),
    ],
)
def test_an_unknown_term_is_a_404_page_not_the_default(client, warehouse, term, says):
    response = client.get("/explore/rooms", params={"term": term})
    assert response.status_code == 404
    assert says in response.text
    assert warehouse.terms_for("room_index") == []


def test_the_free_rooms_form_keeps_the_term_and_offers_13_weeks(client, warehouse):
    html = client.get(
        "/explore/free-rooms", params={"term": "2026-27-s2", "day": "Tuesday", "week": "13"}
    ).text
    assert '<input type="hidden" name="term" value="2026-27-s2">' in html
    assert '<option value="13" selected' in html
    assert "Tuesday 13 Apr" in html
    assert warehouse.terms_for("free_rooms_page") == [S2]


def test_week_13_is_refused_in_semester_1(client):
    html = client.get("/explore/free-rooms", params={"week": "13"}).text
    assert 'value="13"' not in html
    assert "could not be read" in html


def test_the_course_index_is_served_per_term(client, warehouse):
    client.get("/explore/courses.json", params={"term": "2026-27-s2"})
    assert warehouse.terms_for("course_index") == [S2]


# The timetable API


def test_sessions_name_their_term_and_stage(client, warehouse):
    body = client.get(
        "/api/timetable/sessions", params={"codes": "ACCT 1002", "term": "2026-27-s2"}
    ).json()
    assert (body["term"], body["stage"], body["publicationId"]) == ("2026-27-s2", "inspection", 21)
    assert warehouse.terms_for("sessions_for_courses") == [S2]


def test_a_course_is_cached_per_term(client, warehouse):
    client.get("/api/timetable/sessions", params={"codes": "ACCT 1002"})
    client.get("/api/timetable/sessions", params={"codes": "ACCT 1002", "term": "2026-27-s2"})
    client.get("/api/timetable/sessions", params={"codes": "ACCT 1002", "term": "2026-27-s2"})
    assert warehouse.terms_for("sessions_for_courses") == [S1, S2]


def test_sessions_with_no_term_are_the_default_terms(client):
    body = client.get("/api/timetable/sessions", params={"codes": "ACCT 1002"}).json()
    assert (body["term"], body["stage"], body["publicationId"]) == ("2026-27-s1", "final", 16)


def test_changes_are_asked_within_the_term(client, warehouse):
    client.get("/api/timetable/changes", params={"codes": "ACCT 1002", "term": "2026-27-s2"})
    assert warehouse.terms_for("changes_for_courses") == [S2]


def test_an_unknown_term_is_a_json_404(client):
    response = client.get(
        "/api/timetable/sessions", params={"codes": "ACCT 1002", "term": "2027-28-s2"}
    )
    assert response.status_code == 404
    assert response.json() == {"detail": "No timetable is loaded for Semester 2 2027/28."}


def test_an_unreachable_warehouse_does_not_turn_a_term_into_a_404(client, monkeypatch):
    def down(fn, *args):
        raise explore_router.ExplorerUnavailable("down")

    monkeypatch.setattr(explore_router, "query", down)
    response = client.get("/explore/rooms", params={"term": "2026-27-s2"})
    assert response.status_code == 503
