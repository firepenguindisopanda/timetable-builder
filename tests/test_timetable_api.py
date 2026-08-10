"""
The sessions endpoint the timetable builder picks courses from.

The fixture is captured verbatim from the publication of 6 August 2026, so the
shapes under test are ones students actually hit: `COMP 1601` for messy lecture
groups and a Saturday lab, `BIOL 1262` for fortnightly weeks, `FOUN 1101` for
volume, and `WW101` and `FOUN 1001 (FULL & PART-TIME)` for the two code
spellings a naive normaliser destroys.

The warehouse itself is faked rather than connected to. What is pinned here is
the route's contract: which codes it resolves, what it refuses, what it reports
as missing rather than failing on, and how many times it goes to the database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explore_router
import main

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "warehouse_sessions.json").read_text()
)
PUBLISHED_CODES: list[str] = FIXTURE["codes"]
COURSES: dict[str, dict] = {c["code"]: c for c in FIXTURE["courses"]}

SESSIONS_URL = "/api/timetable/sessions"


class FakeWarehouse:
    """
    Stands in for `explore_router.query`, recording every round trip.

    Counting the calls is the point as much as answering them: the endpoint's
    reason to exist is that a whole semester of courses costs one query, and
    that is invisible unless something counts.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.fail_with: Exception | None = None

    def __call__(self, fn, *args):
        if self.fail_with is not None:
            raise self.fail_with
        self.calls.append((fn.__name__, args))

        if fn.__name__ == "course_codes":
            return list(PUBLISHED_CODES)
        if fn.__name__ == "freshness":
            return {"publication_id": FIXTURE["publicationId"]}
        if fn.__name__ == "sessions_for_courses":
            (codes,) = args
            return [COURSES[code] for code in codes if code in COURSES]

        # The ops endpoint shares this router's pool, and the sessions route
        # borrows its freshness. Answering its other two queries keeps the two
        # testable together rather than needing a second harness.
        if fn.__name__ == "day_distribution":
            return {"skewed": False, "busiest_weekday": "Monday", "skew_ratio": 1.1}
        if fn.__name__ == "overview":
            return {"sessions": len(COURSES), "courses": len(COURSES)}

        raise AssertionError(f"the route asked for an unexpected query: {fn.__name__}")

    def calls_to(self, name: str) -> list[tuple[str, tuple]]:
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def warehouse(monkeypatch):
    fake = FakeWarehouse()
    monkeypatch.setattr(explore_router, "query", fake)
    # The cache lives for the module's lifetime, so a course left in it by one
    # test would answer the next one's request without a query.
    explore_router.clear_cache()
    yield fake
    explore_router.clear_cache()


@pytest.fixture
def client(warehouse):
    with TestClient(main.app) as test_client:
        yield test_client


def get(client, codes: str):
    return client.get(SESSIONS_URL, params={"codes": codes})


# What comes back


def test_the_courses_asked_for_come_back_with_their_sessions(client):
    body = get(client, "COMP 1601,COMP 2601").json()

    assert [c["code"] for c in body["courses"]] == ["COMP 1601", "COMP 2601"]
    assert len(body["courses"][0]["sessions"]) == 15
    assert body["courses"][0]["title"] == "Computer Programming I"


def test_courses_keep_the_order_they_were_asked_for(client):
    """The caller pairs the response against its own list, so order is part of
    the contract rather than an accident of the query plan."""
    body = get(client, "COMP 2601,BIOL 1262,COMP 1601").json()

    assert [c["code"] for c in body["courses"]] == [
        "COMP 2601",
        "BIOL 1262",
        "COMP 1601",
    ]


def test_a_session_carries_the_fields_the_calendar_builds_from(client):
    body = get(client, "COMP 1601").json()
    session = body["courses"][0]["sessions"][0]

    assert set(session) == {
        "sessionId",
        "type",
        "day",
        "startTime",
        "endTime",
        "room",
        "staff",
        "streamLabel",
        "weeks",
        "weeksRaw",
        "sourceCount",
    }


def test_weeks_arrive_expanded_rather_than_as_a_bitmask(client):
    """The conflict engine intersects week arrays, so the wire has to carry
    them. BIOL 1262 runs fortnightly, which a bitmask would hide."""
    body = get(client, "BIOL 1262").json()
    fortnightly = [
        s for s in body["courses"][0]["sessions"] if s["weeks"] == [2, 4, 6, 8, 10, 12]
    ]

    assert fortnightly, "expected BIOL 1262 to have fortnightly sessions"
    assert fortnightly[0]["weeksRaw"] == "W2, W4, W6, W8, W10, W12"


def test_the_publication_is_named_so_a_saved_timetable_can_spot_a_reload(client):
    assert get(client, "COMP 1601").json()["publicationId"] == FIXTURE["publicationId"]


def test_the_ops_endpoint_names_the_publication_too(client, warehouse):
    """
    The calendar checks for a republish on load, and asking for a course's
    sessions just to read the publication id would fetch a course it already
    has. This is the cheap question.
    """
    body = client.get("/explore/ops.json").json()

    assert body["freshness"]["publication_id"] == FIXTURE["publicationId"]


# Which codes resolve


@pytest.mark.parametrize("raw", ["COMP 1601", "comp1601", "COMP1601", "comp-1601"])
def test_a_code_resolves_however_it_is_spelled(client, raw):
    body = get(client, raw).json()

    assert [c["code"] for c in body["courses"]] == ["COMP 1601"]
    assert body["notFound"] == []


@pytest.mark.parametrize("raw", ["WW101", "ww 101", "FOUN 1001 (FULL & PART-TIME)"])
def test_codes_the_normaliser_would_corrupt_are_not_reported_missing(client, raw):
    """
    Left to `normalise_course_code`, "WW101" becomes "WW 101" and the hyphen in
    "FOUN 1001 (FULL & PART-TIME)" becomes a space. Neither is published, so a
    foundation course most of the campus takes would come back as not found.

    The two are rescued by different halves of the resolver, so both stay
    pinned: spacing-insensitive matching handles the first, and preferring the
    published spelling over the normalised one handles the second.
    """
    body = get(client, raw).json()

    assert body["notFound"] == []
    assert len(body["courses"]) == 1


def test_an_unrecognised_code_is_reported_and_the_rest_still_arrive(client):
    body = get(client, "COMP 1601,BOGUS 1000,BIOL 1262").json()

    assert body["notFound"] == ["BOGUS 1000"]
    assert [c["code"] for c in body["courses"]] == ["COMP 1601", "BIOL 1262"]


def test_an_unrecognised_code_is_echoed_as_the_student_typed_it(client):
    """The UI shows this back to them, so it has to be their text, not a
    normalised version they never wrote."""
    assert get(client, "  bogus-1000  ").json()["notFound"] == ["bogus-1000"]


def test_asking_for_one_course_twice_returns_it_once(client):
    body = get(client, "COMP 1601,comp1601,COMP1601").json()

    assert [c["code"] for c in body["courses"]] == ["COMP 1601"]


def test_a_code_with_spaces_in_it_is_not_split_apart(client):
    """Codes are separated by commas and nothing else, because "CAPE BIOL" and
    "FOUN 1001 (FULL & PART-TIME)" contain spaces of their own."""
    body = get(client, "FOUN 1001 (FULL & PART-TIME)").json()

    assert [c["code"] for c in body["courses"]] == ["FOUN 1001 (FULL & PART-TIME)"]
    assert body["notFound"] == []


# What it refuses


def test_more_codes_than_the_cap_is_refused_with_the_cap_in_the_message(client):
    too_many = ",".join(f"COMP {1600 + i}" for i in range(41))

    response = get(client, too_many)

    assert response.status_code == 400
    assert str(explore_router.MAX_CODES_PER_REQUEST) in response.json()["detail"]


def test_the_cap_itself_is_allowed(client):
    at_the_cap = ",".join(f"COMP {1600 + i}" for i in range(40))

    assert get(client, at_the_cap).status_code == 200


@pytest.mark.parametrize("codes", ["", "   ", ",,,", " , , "])
def test_naming_no_courses_at_all_is_refused(client, codes):
    assert get(client, codes).status_code == 400


def test_the_warehouse_being_down_is_a_503_rather_than_a_crash(client, warehouse):
    warehouse.fail_with = explore_router.ExplorerUnavailable(
        "The timetable database did not respond."
    )

    response = get(client, "COMP 1601")

    assert response.status_code == 503
    assert "error" in response.json()


def test_the_route_needs_no_api_key(client):
    """It reads published data, like the rest of the explorer."""
    assert get(client, "COMP 1601").status_code == 200


# How often it goes to the warehouse


def test_a_whole_semester_costs_one_query(client, warehouse):
    get(client, "COMP 1601,COMP 2601,BIOL 1262,FOUN 1101,WW101")

    assert len(warehouse.calls_to("sessions_for_courses")) == 1


def test_courses_already_fetched_are_not_fetched_again(client, warehouse):
    get(client, "COMP 1601,BIOL 1262")
    get(client, "COMP 1601,BIOL 1262,FOUN 1101")

    second = warehouse.calls_to("sessions_for_courses")[1]

    assert second[1] == (["FOUN 1101"],)


def test_the_course_list_is_read_once_not_once_per_request(client, warehouse):
    get(client, "COMP 1601")
    get(client, "BIOL 1262")

    assert len(warehouse.calls_to("course_codes")) == 1
