"""
Free rooms: somewhere to study between classes (UX plan 3.4, phase H).

The page can only say a room has no class timetabled, so what is pinned here
is that it says no more than that: placeholders and remote teaching are not
rooms, a booking that merely touches the window does not make a room busy,
off-campus rooms are kept apart, and the caveat is on the page.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explore_router
import main
from timetable_extractor.database import free_rooms as fr

WEEK_ONE = date(2026, 8, 31)


# Which rooms are free


def test_a_room_booked_across_the_window_is_busy_and_one_that_touches_it_is_free():
    bookings = [
        ("ENG 105", 8 * 60, 10 * 60),  # ends as the window opens
        ("ENG 105", 12 * 60, 13 * 60),  # starts after it closes
        ("FST 114", 9 * 60 + 30, 10 * 60 + 30),  # overlaps the start
        ("TLC LT E", 10 * 60 + 15, 10 * 60 + 45),  # inside it
    ]
    free = fr.free_in_window(["ENG 105", "FST 114", "TLC LT E"], bookings, 10 * 60, 11 * 60)
    assert [(r.code, r.free_until) for r in free] == [("ENG 105", 12 * 60)]


def test_a_room_with_nothing_else_that_day_is_free_for_the_rest_of_it():
    free = fr.free_in_window(["JFK AUD"], [("JFK AUD", 8 * 60, 9 * 60)], 10 * 60, 11 * 60)
    assert free[0].free_until is None


def test_registry_and_booking_spellings_meet():
    # The registry writes double spaces; the bookings do not.
    free = fr.free_in_window(["FHE CLL  Room  9"], [("FHE CLL Room 9", 600, 700)], 600, 660)
    assert free == []


@pytest.mark.parametrize(
    "room", ["Remote Teaching", "Remote", "Venue to be advised", "FST TBA", "Room not confirmed", None, ""]
)
def test_placeholders_and_remote_teaching_are_not_study_spaces(room):
    assert not fr.is_study_space(room)


def test_a_real_room_is_a_study_space():
    assert fr.is_study_space("FHE SOE N 12")


# Buildings


@pytest.mark.parametrize(
    "code, label, on_campus",
    [
        ("FST C1", "Science & Technology", True),
        ("Eng Blue Room", "Engineering", True),
        ("Daaga Auditorium", "Daaga Auditorium", True),
        ("UWI SPEC RM# 80", "Sport and Physical Education Centre", True),
        ("UWI Couva Teaching Facility - Seminar Room 3", "Couva Teaching Facility (off campus)", False),
        ("Lecturer's Office", fr.OTHER_BUILDING, True),
        ("FSTX 1", fr.OTHER_BUILDING, True),  # a prefix must be a whole word
    ],
)
def test_buildings_come_from_the_room_code(code, label, on_campus):
    assert fr.building_of(code) == (label, on_campus)


def test_campus_buildings_come_first_and_couva_last():
    free = fr.free_in_window(
        ["UWI Couva Teaching Facility - Lecture Room 5", "Lecturer's Office", "TLC LT E", "ENG 12"],
        [], 600, 660,
    )
    assert [label for label, _ in fr.group_by_building(free)] == [
        "Engineering", "Teaching & Learning Complex", fr.OTHER_BUILDING,
        "Couva Teaching Facility (off campus)",
    ]


def test_the_builder_names_buildings_the_same_way():
    """my-week.js warns about dashes between buildings with these names."""
    source = (Path(__file__).parent.parent / "assets" / "js" / "my-week.js").read_text(encoding="utf-8")
    block = re.search(r"const MY_WEEK_BUILDINGS = \{(.*?)\};", source, re.S).group(1)
    js = dict(re.findall(r"(\w+): '([^']*)'", block))
    python = {prefix.upper(): label for prefix, label, _ in fr.BUILDINGS}
    for key, label in js.items():
        assert python.get(key) == label, key


# The window asked about


@pytest.mark.parametrize(
    "now, expected",
    [
        (datetime(2026, 10, 13, 10, 40), fr.Window("Tuesday", 600, 660, 7)),
        (datetime(2026, 10, 13, 6, 5), fr.Window("Tuesday", 480, 540, 7)),  # before 8am
        (datetime(2026, 10, 13, 20, 30), fr.Window("Wednesday", 480, 540, 7)),  # evening
        (datetime(2026, 10, 17, 21, 0), fr.Window("Monday", 480, 540, 8)),  # Saturday night
        (datetime(2026, 10, 18, 12, 0), fr.Window("Monday", 480, 540, 8)),  # Sunday
        (datetime(2026, 8, 1, 10, 0), fr.Window("Saturday", 600, 660, 1)),  # before term
        (datetime(2026, 12, 1, 10, 0), fr.Window("Tuesday", 600, 660, 12)),  # after it
    ],
)
def test_the_page_opens_on_the_hour_starting_now(now, expected):
    assert fr.default_window(now, WEEK_ONE, 12) == expected


def test_an_unknown_semester_opens_on_week_one():
    assert fr.default_window(datetime(2026, 10, 13, 10, 0), None, 12).week == 1


DEFAULT = fr.Window("Tuesday", 600, 660, 7)


def test_a_full_query_is_read():
    window, refused = fr.window_from(DEFAULT, 12, "monday", "12:00", "14:30", "9")
    assert window == fr.Window("Monday", 720, 870, 9) and not refused


def test_a_start_alone_asks_for_an_hour():
    assert fr.window_from(DEFAULT, 12, start="15:00")[0] == fr.Window("Tuesday", 900, 960, 7)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"day": "Funday"},
        {"start": "14:00", "end": "13:00"},
        {"start": "25:00", "end": "26:00"},
        {"start": "noon", "end": "1pm"},
        {"week": "13"},
        {"week": "0"},
        {"week": "seven"},
    ],
)
def test_what_cannot_be_read_falls_back_and_says_so(kwargs):
    window, refused = fr.window_from(DEFAULT, 12, **kwargs)
    assert refused
    for field in ("day", "week"):
        if field in kwargs:
            assert getattr(window, field) == getattr(DEFAULT, field)


# The page


class FakeWarehouse:
    def __init__(self):
        self.calls = []

    def __call__(self, fn, *args):
        self.calls.append(fn.__name__)
        if fn.__name__ == "free_rooms_page":
            return {
                "rooms": ["ENG 105", "FST 114", "UWI Couva Teaching Facility - Lecture Room 5"],
                "bookings": [("ENG 105", 480, 600), ("ENG 105", 720, 780), ("FST 114", 600, 660)],
            }
        if fn.__name__ == "freshness":
            return {"publication_id": 11, "published_at": None}
        if fn.__name__ == "changes_for_page":
            return None
        if fn.__name__ == "current_semester":
            return "Semester_1_TT2026_2027"
        raise AssertionError(f"unexpected query {fn.__name__}")


@pytest.fixture
def client(monkeypatch):
    fake = FakeWarehouse()
    monkeypatch.setattr(explore_router, "query", fake)
    monkeypatch.setattr(explore_router, "changes_banner_context", lambda: None)
    explore_router.clear_cache()
    with TestClient(main.app) as test_client:
        test_client.fake = fake
        yield test_client
    explore_router.clear_cache()


URL = "/explore/free-rooms"


def test_the_page_lists_free_rooms_with_its_caveat(client):
    html = client.get(URL, params={"day": "Tuesday", "start": "10:00", "end": "11:00", "week": "7"}).text
    assert "1 room with no class" in html, "off-campus rooms are not counted in the headline"
    assert "Tuesday 13 Oct" in html
    assert "ENG 105" in html and "free until 12pm" in html
    assert "FST 114" not in html
    assert "Couva Teaching Facility (off campus)" in html
    assert "not that the room is open" in html
    assert 'href="/explore/room/ENG%20105"' in html


def test_an_unreadable_time_says_so_and_still_shows_rooms(client):
    html = client.get(URL, params={"start": "14:00", "end": "13:00"}).text
    assert "could not be read" in html
    assert "with no class" in html


def test_the_cache_is_keyed_by_day_and_week_not_by_window(client):
    for start, end in (("10:00", "11:00"), ("12:00", "13:00"), ("14:00", "16:00")):
        client.get(URL, params={"day": "Tuesday", "start": start, "end": end, "week": "7"})
    assert client.fake.calls.count("free_rooms_page") == 1


def test_the_site_nav_links_to_it(client):
    html = client.get(URL).text
    assert '<a href="/explore/free-rooms" aria-current="page">Free rooms</a>' in html


def test_an_unreachable_warehouse_explains_itself(client, monkeypatch):
    def down(fn, *args):
        raise explore_router.ExplorerUnavailable("down")

    monkeypatch.setattr(explore_router, "query", down)
    assert client.get(URL).status_code == 503
