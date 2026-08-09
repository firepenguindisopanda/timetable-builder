"""
Tests for the explorer's pure display logic.

The query functions themselves need a database, but the three pieces that
decide what a student actually sees - the week bitmask, course-code
normalisation, and week-grid positioning - are pure and are pinned here.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database.explore_queries import (
    normalise_course_code,
    week_layout,
    weeks_to_mask,
)


# Week bitmask


@pytest.mark.parametrize(
    "weeks, expected",
    [
        (None, 0),
        ([], 0),
        ([1], 0b1),
        ([12], 0b100000000000),
        (list(range(1, 13)), 0xFFF),
        # The fortnightly lab pattern the corpus is full of.
        ([1, 3, 5, 7, 9, 11], 0b010101010101),
        ([2, 4, 6, 8, 10, 12], 0b101010101010),
    ],
)
def test_weeks_to_mask(weeks, expected):
    assert weeks_to_mask(weeks) == expected


def test_weeks_to_mask_ignores_out_of_range_weeks():
    """A week 0 or 13 would silently corrupt neighbouring bits."""
    assert weeks_to_mask([0, 1, 13, 99]) == 0b1


# Course codes


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("COMP 2601", "COMP 2601"),
        ("comp2601", "COMP 2601"),
        ("comp-2601", "COMP 2601"),
        ("  comp   2601 ", "COMP 2601"),
        ("COMP2601", "COMP 2601"),
    ],
)
def test_normalise_course_code(raw, expected):
    assert normalise_course_code(raw) == expected


def test_normalise_course_code_without_digits_is_left_alone():
    assert normalise_course_code("elective") == "ELECTIVE"


# Week grid layout


def session(day, start, end):
    return {"day": day, "start_min": start, "end_min": end}


def test_week_layout_of_nothing_is_empty():
    assert week_layout([])["days"] == []


def test_layout_spans_the_real_duration():
    """A four-hour lab must be four hours tall, not one row."""
    layout = week_layout([session("Monday", 9 * 60, 13 * 60)])
    block = layout["days"][0]["blocks"][0]

    assert block["top_min"] == 0
    assert block["height_min"] == 240
    assert layout["first_min"] == 9 * 60
    assert layout["hours"] == [9, 10, 11, 12]


def test_layout_starts_at_the_hour_before_the_first_class():
    layout = week_layout([session("Monday", 9 * 60 + 30, 10 * 60 + 30)])

    assert layout["first_min"] == 9 * 60
    assert layout["days"][0]["blocks"][0]["top_min"] == 30
    # 09:00 to 11:00 covers a class that ends half way through the hour.
    assert layout["hours"] == [9, 10]


def test_sequential_classes_each_take_the_full_width():
    layout = week_layout([
        session("Monday", 9 * 60, 10 * 60),
        session("Monday", 10 * 60, 11 * 60),
    ])
    blocks = layout["days"][0]["blocks"]

    assert [b["width_pct"] for b in blocks] == [100, 100]
    assert [b["left_pct"] for b in blocks] == [0, 0]


def test_overlapping_classes_split_into_lanes():
    """Parallel streams sit side by side instead of hiding one another."""
    layout = week_layout([
        session("Monday", 9 * 60, 11 * 60),
        session("Monday", 9 * 60, 11 * 60),
    ])
    blocks = layout["days"][0]["blocks"]

    assert [b["width_pct"] for b in blocks] == [50, 50]
    assert sorted(b["left_pct"] for b in blocks) == [0, 50]


def test_a_crowded_hour_does_not_narrow_the_rest_of_the_day():
    """
    Lanes are counted per cluster of overlapping classes, not per day.

    A morning lab that overlaps nothing should stay full width even when the
    same day has five parallel lectures in the afternoon.
    """
    sessions = [session("Thursday", 9 * 60, 13 * 60)]
    sessions += [session("Thursday", 16 * 60, 17 * 60) for _ in range(5)]

    blocks = week_layout(sessions)["days"][0]["blocks"]
    morning = [b for b in blocks if b["top_min"] == 0]
    afternoon = [b for b in blocks if b["top_min"] > 0]

    assert morning[0]["width_pct"] == 100
    assert all(b["width_pct"] == 20 for b in afternoon)
    assert sorted(b["left_pct"] for b in afternoon) == [0, 20, 40, 60, 80]


def test_a_lane_is_reused_once_it_is_free():
    """Three classes where only two ever overlap need two lanes, not three."""
    layout = week_layout([
        session("Monday", 9 * 60, 12 * 60),
        session("Monday", 9 * 60, 10 * 60),
        session("Monday", 10 * 60, 11 * 60),
    ])

    assert layout["days"][0]["lanes"] == 2
    assert all(b["width_pct"] == 50 for b in layout["days"][0]["blocks"])


def test_days_come_back_in_timetable_order():
    layout = week_layout([
        session("Friday", 9 * 60, 10 * 60),
        session("Monday", 9 * 60, 10 * 60),
        session("Wednesday", 9 * 60, 10 * 60),
    ])

    assert [d["day"] for d in layout["days"]] == ["Monday", "Wednesday", "Friday"]


def test_empty_days_are_left_out():
    layout = week_layout([session("Tuesday", 9 * 60, 10 * 60)])
    assert [d["day"] for d in layout["days"]] == ["Tuesday"]
