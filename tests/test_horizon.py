"""
Tests for carrying past weeks across a republish.

CELCAT exports from the current teaching week on, so on 11 September 2026 every
PDF said "(Wks W2-W12)" and the warehouse took week 1 off every class. The
diff then reported 1,624 moves where there were 99. What is pinned here is
that weeks which have passed come back from the previous publication, that no
week is ever invented, and that an unchanged class reads as unchanged all the
way to the string a saved timetable compares against.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database.changes import (
    CLASS_MOVED,
    CLASS_REMOVED,
    diff_sessions,
)
from timetable_extractor.database.horizon import (
    EarlierSitting,
    carry_past_weeks,
    record_horizon,
)
from timetable_extractor.database.records import SessionRecord
from timetable_extractor.database.weeks import expand_weeks, export_horizon, render_weeks
from timetable_extractor.observability import Diagnostics


# The title range


@pytest.mark.parametrize(
    "title,expected",
    [
        ("Course timetable - ACCT 1003, Intro. to Cost & Management Accounting (Wks W2-W12)", 2),
        ("Staff timetable - DIAL,Keegan (Wks W2-W12)", 2),
        ("Room timetable - ENG SV105 (Wks W2-W12)", 2),
        ("Course timetable - NURS 1110, Biochemistry (Wks W1-W12)", 1),
        ("Course timetable - COMP 1601 (Wks W10-W12)", 10),
    ],
)
def test_the_horizon_is_read_from_every_kind_of_title(title, expected):
    assert export_horizon(title) == expected


@pytest.mark.parametrize("title", [None, "", "Course timetable - COMP 1601"])
def test_a_title_without_a_range_has_no_horizon_rather_than_week_one(title):
    assert export_horizon(title) is None


# Writing weeks back out


@pytest.mark.parametrize(
    "raw",
    ["W1-W12", "W1-W7, W9-W12", "W1, W3, W5, W7, W9, W11", "W8", "W1-W11", "W2-W6, W8-W12"],
)
def test_rendering_is_the_inverse_of_expanding_for_what_celcat_prints(raw):
    assert render_weeks(expand_weeks(raw)) == raw


def test_no_weeks_render_as_nothing():
    assert render_weeks([]) is None


# Carrying


def record(weeks="W2-W12", room="FST CSL1", source="m1.pdf", **overrides):
    fields = {
        "course_code": "COMP 1601",
        "day": "Monday",
        "start_min": 540,
        "end_min": 600,
        "room_code": room,
        "activity_type": "Lecture",
        "stream_label": None,
        "weeks_raw": weeks,
        "weeks": expand_weeks(weeks),
        "week_count": len(expand_weeks(weeks)) if weeks else None,
        "sources": {source},
    }
    fields.update(overrides)
    return SessionRecord(**fields)


def earlier(weeks="W1-W12", room="FST CSL1", **overrides):
    fields = {
        "course_code": "COMP 1601",
        "activity_type": "Lecture",
        "stream_label": None,
        "day": "Monday",
        "start_min": 540,
        "end_min": 600,
        "room_code": room,
        "weeks_raw": weeks,
        "weeks": tuple(expand_weeks(weeks)),
    }
    fields.update(overrides)
    return EarlierSitting(**fields)


WEEK_2 = {"m1.pdf": 2}


def test_an_unchanged_class_takes_week_one_back():
    r = record("W2-W12")
    assert carry_past_weeks([r], [earlier("W1-W12")], WEEK_2) == 1
    assert r.weeks_raw == "W1-W12"
    assert r.weeks == list(range(1, 13))
    assert r.week_count == 12


def test_the_earlier_week_string_is_reused_verbatim():
    """A saved timetable compares strings; re-rendering must not be what it sees."""
    r = record("W3, W5")
    carry_past_weeks([r], [earlier("W1,W3,W5")], WEEK_2)
    assert r.weeks_raw == "W1,W3,W5"


def test_an_alternate_week_pattern_keeps_its_numbering():
    r = record("W3, W5, W7, W9, W11")
    carry_past_weeks([r], [earlier("W1, W3, W5, W7, W9, W11")], WEEK_2)
    assert r.weeks_raw == "W1, W3, W5, W7, W9, W11"


def test_a_class_that_genuinely_starts_in_week_two_is_not_given_week_one():
    r = record("W2-W12")
    assert carry_past_weeks([r], [earlier("W2-W12")], WEEK_2) == 0
    assert r.weeks_raw == "W2-W12"


def test_a_change_to_upcoming_weeks_survives_and_gains_the_past():
    r = record("W2-W7, W9-W12")
    carry_past_weeks([r], [earlier("W1-W12")], WEEK_2)
    assert r.weeks_raw == "W1-W7, W9-W12"
    assert r.week_count == 11


def test_history_carries_on_through_later_republishes():
    """Publication 9 inherits from publication 8, which already holds week 1."""
    r = record("W3-W12")
    carry_past_weeks([r], [earlier("W1-W12")], {"m1.pdf": 3})
    assert r.weeks_raw == "W1-W12"


def test_a_class_with_no_earlier_sitting_in_its_slot_keeps_what_was_printed():
    moved = record("W2-W12", room="TLC LT A1")
    assert carry_past_weeks([moved], [earlier("W1-W12", room="FST CSL1")], WEEK_2) == 0
    assert moved.weeks_raw == "W2-W12"


def test_a_different_stream_in_the_same_slot_is_not_a_source():
    r = record("W2-W12", stream_label="T2")
    assert carry_past_weeks([r], [earlier("W1-W12", stream_label="T1")], WEEK_2) == 0


def test_an_exact_match_is_chosen_among_several_earlier_sittings():
    r = record("W4, W6")
    carry_past_weeks([r], [earlier("W1-W12"), earlier("W1, W4, W6")], WEEK_2)
    assert r.weeks_raw == "W1, W4, W6"


def test_several_earlier_sittings_and_no_exact_match_is_left_alone_and_reported():
    r = record("W5-W9")
    findings = Diagnostics(source="finder.xml")
    carried = carry_past_weeks(
        [r], [earlier("W1-W12"), earlier("W1, W3")], WEEK_2, findings
    )
    assert carried == 0
    assert r.weeks_raw == "W5-W9"
    assert findings.findings["past_weeks_ambiguous"] == 1


@pytest.mark.parametrize("horizons", [{"m1.pdf": 1}, {"m1.pdf": None}, {}])
def test_nothing_is_carried_before_the_semester_moves_on_or_when_unknown(horizons):
    r = record("W1-W12")
    assert carry_past_weeks([r], [earlier("W1-W12")], horizons) == 0


def test_a_record_with_no_weeks_is_not_narrowed_to_past_ones():
    r = record(None)
    assert carry_past_weeks([r], [earlier("W1")], WEEK_2) == 0
    assert r.weeks_raw is None


def test_a_record_takes_the_lowest_horizon_among_its_sources():
    """A week any source still printed has not passed."""
    r = record(sources={"m1.pdf", "s1.pdf"})
    assert record_horizon(r, {"m1.pdf": 3, "s1.pdf": 2}) == 2
    assert record_horizon(r, {"m1.pdf": None}) is None


# The diff


def row(weeks="W1-W12", activity_type="Lecture", day="Monday"):
    return {
        "code": "COMP 1601",
        "title": "Introduction to Computing",
        "resource_id": None,
        "activity_type": activity_type,
        "stream_label": None,
        "day": day,
        "start_min": 540,
        "end_min": 600,
        "room": "FST CSL1",
        "weeks_raw": weeks,
    }


def test_a_class_that_only_ran_in_weeks_now_past_has_finished_not_been_removed():
    before = [row(), row("W1", activity_type="Tutorial")]
    assert diff_sessions(before, [row()], horizon=2) == []


def test_without_a_horizon_that_class_still_reads_as_removed():
    before = [row(), row("W1", activity_type="Tutorial")]
    changes = diff_sessions(before, [row()])
    assert [c.change_type for c in changes] == [CLASS_REMOVED]


def test_a_class_with_weeks_still_to_come_that_vanishes_is_still_removed():
    before = [row(), row("W1-W3", activity_type="Tutorial")]
    changes = diff_sessions(before, [row()], horizon=2)
    assert [c.change_type for c in changes] == [CLASS_REMOVED]


def test_the_eleventh_of_september_carried_is_no_change_at_all():
    """The whole failure, end to end: carry, then diff."""
    r = record("W2-W12")
    carry_past_weeks([r], [earlier("W1-W12")], WEEK_2)
    assert diff_sessions([row("W1-W12")], [row(r.weeks_raw)], horizon=2) == []


def test_a_real_move_still_shows_once_the_weeks_are_carried():
    """Carrying matches on the slot, so a class that changed day gets no history."""
    r = record("W2-W12", day="Tuesday")
    carry_past_weeks([r], [earlier("W1-W12")], WEEK_2)
    changes = diff_sessions([row("W1-W12")], [row(r.weeks_raw, day="Tuesday")], horizon=2)
    assert [c.change_type for c in changes] == [CLASS_MOVED]
