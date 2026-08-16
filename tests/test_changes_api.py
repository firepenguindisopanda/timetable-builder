"""
The endpoint the timetable builder asks "did anything happen to my courses?".

The warehouse is faked; code resolution is not, so the codes a student's saved
timetable actually holds are exercised for real. What is pinned here is the
contract the builder depends on: which publication the answer is measured
from, what happens when that publication is gone, and that a course whose code
changed is reported as a rename rather than as missing.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import explore_router
import main

URL = "/api/timetable/changes"

AUGUST_6 = datetime(2026, 8, 6, 14, 22, 58, tzinfo=timezone.utc)
AUGUST_14 = datetime(2026, 8, 14, 15, 41, 35, tzinfo=timezone.utc)

PUBLISHED_CODES = ["COMP 1601", "ECCD 0110", "FREN 3401", "EDMA 1142"]


def moved(code="ECCD 0110"):
    return {
        "code": code, "title": "Foundations of ECCD",
        "changeType": "class_moved", "displayKind": "class_moved",
        "activityType": "Lecture", "streamLabel": None, "lastOfType": False,
        "before": [{"day": "Wednesday", "startTime": "17:00", "endTime": "19:00",
                    "room": "FHE SOE 131", "weeks": "W1-W12"}],
        "after": [{"day": "Friday", "startTime": "17:00", "endTime": "19:00",
                   "room": "FHE SOE 131", "weeks": "W1-W12"}],
    }


def renamed():
    return {
        "code": "EDMA 1142", "title": "Teaching Numeracy",
        "changeType": "course_renamed", "displayKind": "course_renamed",
        "activityType": None, "streamLabel": None, "lastOfType": False,
        "previousCode": "EDMA 11**", "before": [], "after": [],
    }


class FakeWarehouse:
    """Records the codes and `since` the route asked with."""

    def __init__(self):
        self.asked: list[tuple] = []
        self.publications = 2
        self.changes = [moved()]

    def __call__(self, fn, *args):
        if fn.__name__ == "course_codes":
            return list(PUBLISHED_CODES)
        if fn.__name__ == "changes_for_courses":
            codes, since = args
            self.asked.append((tuple(codes), since))
            if self.publications < 2:
                return None

            from_id, to_id, since_unavailable = 1, 2, False
            if since == 2:
                return {"from_id": 2, "to_id": 2,
                        "from_published_at": AUGUST_14, "to_published_at": AUGUST_14,
                        "since_unavailable": False, "changes": []}
            if since is not None and since not in (1, 2):
                since_unavailable = True

            wanted = set(codes)
            visible = [
                c for c in self.changes
                if c["code"] in wanted or c.get("previousCode") in wanted
            ]
            return {"from_id": from_id, "to_id": to_id,
                    "from_published_at": AUGUST_6, "to_published_at": AUGUST_14,
                    "since_unavailable": since_unavailable, "changes": visible}
        raise AssertionError(f"unexpected query: {fn.__name__}")


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


def get(client, **params):
    return client.get(URL, params=params)


# Which publication the answer is measured from


def test_omitting_since_answers_the_last_republish(client):
    body = get(client, codes="ECCD 0110").json()
    assert body["fromPublicationId"] == 1
    assert body["toPublicationId"] == 2
    assert body["publishedAt"].startswith("2026-08-14")
    assert body["previousPublishedAt"].startswith("2026-08-06")


def test_the_builder_passes_the_publication_its_timetable_was_built_against(client, warehouse):
    get(client, codes="ECCD 0110", since=1)
    assert warehouse.asked[-1][1] == 1


def test_a_caller_already_on_the_current_publication_is_told_nothing_changed(client):
    body = get(client, codes="ECCD 0110", since=2).json()
    assert body["changes"] == []
    assert body["sinceUnavailable"] is False


def test_a_publication_the_warehouse_no_longer_holds_says_which_question_it_answered(client):
    """
    Falling back silently would answer a different question than the one
    asked, and the caller could not tell.
    """
    body = get(client, codes="ECCD 0110", since=404).json()
    assert body["sinceUnavailable"] is True
    assert body["fromPublicationId"] == 1


def test_a_single_publication_is_not_an_error(client, warehouse):
    warehouse.publications = 1
    body = get(client, codes="ECCD 0110").json()
    assert body["changes"] == []
    assert body["toPublicationId"] is None


# Which courses come back


def test_a_course_with_nothing_to_report_is_simply_absent(client):
    body = get(client, codes="COMP 1601").json()
    assert body["changes"] == []
    assert body["notFound"] == []


def test_an_unrecognised_code_is_reported_not_fatal(client):
    body = get(client, codes="ECCD 0110,NOPE 9999").json()
    assert body["notFound"] == ["NOPE 9999"]
    assert len(body["changes"]) == 1


def test_codes_resolve_the_way_the_rest_of_the_app_resolves_them(client):
    """`ECCD0110` off a registration screenshot is the same course."""
    body = get(client, codes="eccd0110").json()
    assert [c["code"] for c in body["changes"]] == ["ECCD 0110"]


# Renames, which are the reason unresolved codes are still asked about


def test_a_saved_timetable_holding_the_old_code_is_told_the_new_one(client, warehouse):
    """
    `EDMA 11**` stopped resolving because it was renamed to `EDMA 1142`.
    Answering "not found" would strand the course in a student's timetable
    with no explanation, which is the one thing a rename must not do.
    """
    warehouse.changes = [renamed()]
    body = get(client, codes="EDMA 11**").json()

    assert body["notFound"] == []
    assert len(body["changes"]) == 1
    assert body["changes"][0]["changeType"] == "course_renamed"
    assert body["changes"][0]["previousCode"] == "EDMA 11**"
    assert body["changes"][0]["code"] == "EDMA 1142"


def test_an_unresolved_code_is_still_asked_about(client, warehouse):
    """The rename above is only findable because the code is not dropped."""
    warehouse.changes = [renamed()]
    get(client, codes="EDMA 11**")
    assert "EDMA 11**" in warehouse.asked[-1][0]


def test_a_code_that_is_neither_published_nor_renamed_stays_not_found(client, warehouse):
    warehouse.changes = [renamed()]
    body = get(client, codes="EDMA 11**,NOPE 9999").json()
    assert body["notFound"] == ["NOPE 9999"]


# Limits


def test_no_codes_is_a_bad_request(client):
    assert get(client, codes="  ,  ").status_code == 400


def test_more_than_forty_codes_is_refused(client):
    many = ",".join(f"COMP {1000 + n}" for n in range(41))
    response = get(client, codes=many)
    assert response.status_code == 400
    assert "40" in response.json()["detail"]


def test_forty_codes_is_allowed(client):
    many = ",".join(f"COMP {1000 + n}" for n in range(40))
    assert get(client, codes=many).status_code == 200


def test_a_code_containing_a_space_is_not_split_apart(client, warehouse):
    """`FOUN 1001 (FULL & PART-TIME)` is one course, not three."""
    get(client, codes="FOUN 1001 (FULL & PART-TIME)")
    assert len(warehouse.asked[-1][0]) == 1


def test_an_unreachable_warehouse_answers_503_not_500(client, monkeypatch):
    def unavailable(fn, *args):
        raise explore_router.ExplorerUnavailable("The timetable database is unreachable.")

    monkeypatch.setattr(explore_router, "query", unavailable)
    explore_router.clear_cache()
    response = get(client, codes="ECCD 0110")
    assert response.status_code == 503
    assert "error" in response.json()


def test_the_answer_is_cacheable_by_the_browser(client):
    response = get(client, codes="ECCD 0110")
    assert response.headers["cache-control"] == "public, max-age=300"
