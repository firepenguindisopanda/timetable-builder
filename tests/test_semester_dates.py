"""
Dates for the teaching weeks.

CELCAT publishes week numbers and never dates, so the calendar's dated weeks
rest on one table of semester start dates. The table is keyed on a normalised
semester because the label CELCAT prints has drifted: three spellings of one
semester in four publications. What is pinned here is that every spelling
lands, that an unknown semester is never guessed at, and that the calendar
page still renders when the dates cannot be found.
"""

from __future__ import annotations

import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

import explore_router
import main
from timetable_extractor.database import explore_queries as eq
from timetable_extractor.database.weeks import (
    TERMS,
    publication_stage,
    semester_key,
    teaching_start,
)


@pytest.mark.parametrize(
    "label",
    ["Semester_1_TT2026_2027", "Semester_I_2026_2027", "Semester_I_2026_2027_"],
)
def test_every_spelling_of_semester_1_lands_on_31_august(label):
    assert semester_key(label) == ("2026/2027", 1)
    assert teaching_start(label) == date(2026, 8, 31)


def test_semester_2_starts_18_january_2027():
    assert teaching_start("Semester_II_2026_2027") == date(2027, 1, 18)
    assert teaching_start("Semester_2_TT2026_2027") == date(2027, 1, 18)


@pytest.mark.parametrize("label", [None, "", "Summer", "Semester_3_TT2026_2027"])
def test_an_unknown_semester_has_no_start_rather_than_a_guess(label):
    assert teaching_start(label) is None


# Terms and stages (SEMESTERS-SPEC.md 3 and 4)


@pytest.mark.parametrize(
    ("label", "term", "stage"),
    [
        ("Semester_1_TT2026_2027", ("2026/2027", 1), "final"),
        ("Semester_I_2026_2027", ("2026/2027", 1), "final"),
        ("Semester_I_2026_2027_", ("2026/2027", 1), "final"),
        # The semester 2 inspection copy of 26 Nov 2026. With "Semester"
        # required it gave no term, and no week could be dated.
        ("Inspection_Sem_2_2026_2027", ("2026/2027", 2), "inspection"),
    ],
)
def test_every_label_seen_gives_its_term_and_stage(label, term, stage):
    assert semester_key(label) == term
    assert publication_stage(label) == stage


def test_the_inspection_copy_is_dated_from_18_january_2027():
    assert teaching_start("Inspection_Sem_2_2026_2027") == date(2027, 1, 18)


@pytest.mark.parametrize("key", sorted(TERMS))
def test_each_terms_week_count_matches_its_dates(key):
    """Typed in by hand, so each row is checked against itself."""
    term = TERMS[key]
    assert term.week_one.weekday() == 0, "week 1 starts on a Monday"
    assert term.teaching_ends.weekday() == 4, "teaching ends on a Friday"
    weeks = (term.teaching_ends - term.week_one).days // 7 + 1
    assert weeks == term.teaching_weeks
    assert term.teaching_ends < term.exams[0] <= term.exams[1]


def test_semester_2_has_13_teaching_weeks():
    """S2W1-S2W13, and the academic calendar agrees: 18 Jan to 16 Apr 2027."""
    assert TERMS[("2026/2027", 2)].teaching_weeks == 13
    assert TERMS[("2026/2027", 1)].teaching_weeks == eq.TOTAL_WEEKS


# What the calendar page is handed


def _calendar_with(monkeypatch, semester):
    def fake(fn, *args):
        if fn is eq.current_semester:
            if isinstance(semester, Exception):
                raise semester
            return semester
        raise explore_router.ExplorerUnavailable("not needed here")

    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    try:
        with TestClient(main.app) as client:
            return client.get("/calendar").text
    finally:
        explore_router.clear_cache()


def _teaching(body):
    """The value the page's script reads, parsed rather than string-matched."""
    line = next(l for l in body.splitlines() if "const teaching = " in l)
    return json.loads(line.split("const teaching = ", 1)[1].rstrip().rstrip(";"))


def test_the_calendar_is_handed_week_one_and_the_week_count(monkeypatch):
    body = _calendar_with(monkeypatch, "Semester_I_2026_2027")
    assert _teaching(body) == {"weekOne": "2026-08-31", "totalWeeks": eq.TOTAL_WEEKS}


def test_an_unknown_semester_leaves_the_calendar_undated(monkeypatch):
    body = _calendar_with(monkeypatch, "Semester_3_TT2026_2027")
    assert _teaching(body) is None


def test_an_unreachable_warehouse_still_serves_the_calendar(monkeypatch):
    body = _calendar_with(monkeypatch, explore_router.ExplorerUnavailable("down"))
    assert _teaching(body) is None
    assert 'id="calendarWrapper"' in body
