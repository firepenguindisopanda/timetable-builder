"""
The page that tells a student what the last republish changed.

The warehouse is faked rather than connected to, in the same way as
`test_timetable_api.py`. What is pinned here is the page's contract: that it
survives a single publication with nothing to compare against, that it never
becomes a dead end, and that a student arriving from a half-built timetable
can get back to it.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import explore_router
import main

CHANGES_URL = "/explore/changes"

AUGUST_6 = datetime(2026, 8, 6, 14, 22, 58, tzinfo=timezone.utc)
AUGUST_14 = datetime(2026, 8, 14, 15, 41, 35, tzinfo=timezone.utc)


def change_set(**overrides):
    """The 14 August republish, reduced to one of each kind."""
    base = {
        "from_id": 1,
        "to_id": 2,
        "from_published_at": AUGUST_6,
        "to_published_at": AUGUST_14,
        "counts": {"class_moved": 1, "class_venue_confirmed": 1},
        "classes": [
            {
                "course_code": "ECCD 0110",
                "course_title": "Foundations of ECCD",
                "activity_type": "Lecture",
                "stream_label": None,
                "kind": "class_moved",
                "display_kind": "class_moved",
                "before_slots": [
                    {"day": "Wednesday", "startTime": "17:00", "endTime": "19:00",
                     "room": "FHE SOE 131", "weeks": "W1-W12"}
                ],
                "after_slots": [
                    {"day": "Friday", "startTime": "17:00", "endTime": "19:00",
                     "room": "FHE SOE 131", "weeks": "W1-W12"}
                ],
            },
            {
                "course_code": "COMS 6003",
                "course_title": "Communication Studies",
                "activity_type": "Postgraduate",
                "stream_label": None,
                "kind": "class_venue_confirmed",
                "display_kind": "class_venue_confirmed",
                "before_slots": [
                    {"day": "Tuesday", "startTime": "17:00", "endTime": "20:00",
                     "room": "Venue to be advised", "weeks": "W1-W12"}
                ],
                "after_slots": [
                    {"day": "Tuesday", "startTime": "17:00", "endTime": "20:00",
                     "room": "FHE 314 A", "weeks": "W1-W12"}
                ],
            },
        ],
        "courses_added": [
            {"course_code": "PORT 2001", "course_title": "Portuguese Language IIA"}
        ],
        "courses_dropped": [
            {"course_code": "LING 2304", "course_title": "Language Situations"}
        ],
        "renamed": [
            {"course_code": "EDMA 1142", "from_code": "EDMA 11**",
             "course_title": "Teaching Numeracy"}
        ],
        "lost_types": [
            {"course_code": "FREN 3401", "course_title": "French Language IIIA",
             "activity_type": "Lecture", "kind": "class_removed",
             "display_kind": "class_removed", "before_slots": [], "after_slots": []}
        ],
        "total": 6,
    }
    base.update(overrides)
    return base


class FakeWarehouse:
    def __init__(self, changes):
        self.changes = changes
        self.calls: list[str] = []

    def __call__(self, fn, *args):
        self.calls.append(fn.__name__)
        if fn.__name__ == "changes_for_page":
            return self.changes
        # The rooms page is the cheapest explorer page to render, so it stands
        # in for "any page that is not the changes page" when testing the
        # banner that sits on all of them.
        if fn.__name__ == "room_index":
            return []
        if fn.__name__ == "freshness":
            return {"publication_id": 2, "published_at": AUGUST_14,
                    "imported_at": AUGUST_14, "checked_at": AUGUST_14,
                    "resource_count": 1630, "check_count": 7,
                    "publication_count": 2, "update_pending": False}
        raise AssertionError(f"unexpected query: {fn.__name__}")


@pytest.fixture
def warehouse(monkeypatch):
    fake = FakeWarehouse(change_set())
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    yield fake
    explore_router.clear_cache()


@pytest.fixture
def client(warehouse):
    with TestClient(main.app) as test_client:
        yield test_client


# What the page says


def test_the_page_names_both_publications(client):
    body = client.get(CHANGES_URL).text
    assert "14 August" in body
    assert "6 August 2026" in body


def test_a_single_digit_day_carries_no_leading_zero(client):
    """
    The assertion above cannot catch this: "06 August 2026" contains
    "6 August 2026". The page once used `strftime("%-d")` for exactly this
    rendering, which is glibc-only and crashed every test here on Windows, so
    the portable replacement has to be held to the same output.
    """
    body = client.get(CHANGES_URL).text
    assert "06 August" not in body


def test_long_date_drops_the_leading_zero_on_every_platform():
    assert explore_router.long_date(AUGUST_6) == "6 August 2026"
    assert explore_router.long_date(AUGUST_14) == "14 August 2026"


def test_long_date_can_leave_the_year_off():
    assert explore_router.long_date(AUGUST_6, year=False) == "6 August"


def test_every_kind_of_change_reaches_the_page(client):
    body = client.get(CHANGES_URL).text
    for expected in (
        "ECCD 0110",       # moved
        "COMS 6003",       # venue confirmed
        "PORT 2001",       # course added
        "LING 2304",       # course withdrawn
        "EDMA 11**",       # renamed, from
        "EDMA 1142",       # renamed, to
        "FREN 3401",       # lost a class type
    ):
        assert expected in body, f"{expected} is missing from the page"


def test_a_move_shows_where_it_was_and_where_it_is_now(client):
    body = client.get(CHANGES_URL).text
    assert "Wednesday"[:3] in body and "Fri" in body
    assert "17:00" in body


def test_a_venue_confirmation_is_not_called_a_move(client):
    """The largest category is good news, and saying "moved" overstates it."""
    body = client.get(CHANGES_URL).text
    assert "venue confirmed" in body


# Getting there and back


def test_the_explorer_nav_offers_the_page(client):
    """A student who dismissed the banner needs a route back to the answer."""
    body = client.get("/explore/changes").text
    assert 'href="/explore/changes"' in body


def test_the_page_marks_itself_current_in_the_nav(client):
    body = client.get(CHANGES_URL).text
    assert 'href="/explore/changes" aria-current="page"' in body


def test_arriving_from_the_calendar_offers_a_way_back(client):
    body = client.get(CHANGES_URL, params={"from": "calendar"}).text
    assert "Back to your timetable" in body
    assert 'href="/calendar"' in body


def test_arriving_any_other_way_does_not_offer_that_link(client):
    """The link is a promise that a half-built timetable is still there."""
    assert "Back to your timetable" not in client.get(CHANGES_URL).text


# The states that are not a list of changes


def test_a_single_publication_is_explained_rather_than_erroring(monkeypatch):
    """The first load has nothing to compare against. That is not a fault."""
    fake = FakeWarehouse(None)
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    with TestClient(main.app) as client:
        response = client.get(CHANGES_URL)
    explore_router.clear_cache()

    assert response.status_code == 200
    assert "Nothing to compare yet" in response.text


def test_a_republish_that_changed_nothing_says_so(monkeypatch):
    empty = change_set(
        counts={}, classes=[], courses_added=[], courses_dropped=[],
        renamed=[], lost_types=[], total=0,
    )
    fake = FakeWarehouse(empty)
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    with TestClient(main.app) as client:
        response = client.get(CHANGES_URL)
    explore_router.clear_cache()

    assert response.status_code == 200
    assert "Nothing changed" in response.text


def test_an_unreachable_warehouse_answers_in_the_explorer_shell(monkeypatch):
    """
    503, not 500, and rendered as a page rather than a stack trace - the same
    treatment every other explorer page gives an unreachable warehouse.
    """
    def unavailable(fn, *args):
        raise explore_router.ExplorerUnavailable("The timetable database is unreachable.")

    monkeypatch.setattr(explore_router, "query", unavailable)
    explore_router.clear_cache()
    with TestClient(main.app) as client:
        response = client.get(CHANGES_URL)
    explore_router.clear_cache()

    assert response.status_code == 503
    assert "<html" in response.text
    assert "Traceback" not in response.text


def test_the_page_costs_one_query(warehouse, client):
    """It reads a table the loader already wrote; it must not diff on request."""
    client.get(CHANGES_URL)
    assert warehouse.calls.count("changes_for_page") == 1


# The notice that sends a student here
#
# Without it the page only answers people who already went looking, which is
# not the people who need it.

ROOMS_URL = "/explore/rooms"


def test_an_explorer_page_carries_the_update_notice(client):
    body = client.get(ROOMS_URL).text
    assert 'id="updateBar"' in body
    assert "The timetable was updated" in body


def test_the_notice_leads_to_the_changes_page(client):
    body = client.get(ROOMS_URL).text
    assert 'class="update-cta" href="/explore/changes"' in body


def test_the_notice_carries_the_publication_it_is_about(client):
    """
    The dismissal is saved against this, so a later republish brings the
    notice back rather than staying dismissed for the rest of term.
    """
    assert 'data-publication="2"' in client.get(ROOMS_URL).text


def test_the_notice_and_the_page_report_the_same_numbers(client):
    """
    Both read one cached change set. A notice claiming more moved classes
    than the page lists would be worse than no notice at all.
    """
    banner = client.get(ROOMS_URL).text
    page = client.get(CHANGES_URL).text

    assert "1 class moved" in banner
    assert "1 venue confirmed" in banner
    assert "1 course added" in banner
    assert "1 no longer published" in banner
    # The page's own tiles, from the same counts.
    assert "<b>1</b><span>classes moved</span>" in page
    assert "<b>1</b><span>venues confirmed</span>" in page


def test_the_notice_is_not_shown_on_the_changes_page(client):
    """It would announce the page the reader is already reading."""
    assert 'id="updateBar"' not in client.get(CHANGES_URL).text


def test_no_notice_when_there_is_only_one_publication(monkeypatch):
    fake = FakeWarehouse(None)
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    with TestClient(main.app) as client:
        body = client.get(ROOMS_URL).text
    explore_router.clear_cache()

    assert 'id="updateBar"' not in body


def test_no_notice_when_the_republish_changed_nothing(monkeypatch):
    """A republish that moved nothing is not news."""
    empty = change_set(
        counts={}, classes=[], courses_added=[], courses_dropped=[],
        renamed=[], lost_types=[], total=0,
    )
    fake = FakeWarehouse(empty)
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    with TestClient(main.app) as client:
        body = client.get(ROOMS_URL).text
    explore_router.clear_cache()

    assert 'id="updateBar"' not in body


def test_the_notice_costs_no_extra_query(warehouse, client):
    """
    It shares the changes page's cache entry. Rendering a page with the notice
    and then the page itself must still be one trip to the warehouse.
    """
    client.get(ROOMS_URL)
    client.get(CHANGES_URL)
    assert warehouse.calls.count("changes_for_page") == 1


def test_a_dismissible_control_is_offered(client):
    body = client.get(ROOMS_URL).text
    assert 'id="updateDismiss"' in body
    assert "Dismiss this update notice" in body
