"""
"When the campus is busy": classes on campus, in a typical week.

The grid counted stored rows across the whole semester. On publication 12 it
said "peak 190 at once" for Monday 5pm, when 126 classes run then in a
typical week and the room timetables show 128 rooms in use
(HEATMAP-VALIDATION-SPEC.md). Each test pins one way the rows and the classes
differ.
"""

from __future__ import annotations

import itertools

from timetable_extractor.database.explore_queries import (
    DAY_END_HOUR,
    DAY_START_HOUR,
    heat_grid,
    heat_matrix,
)

_ids = itertools.count(1)
ALL_WEEKS = list(range(1, 13))


def row(day="Monday", start="17:00", end="18:00", *, course="COMP 2601",
        room="FST C2", weeks=ALL_WEEKS, raw_text=None, type_="Lecture",
        stream=None, weeks_raw="W1-W12"):
    hours, minutes = map(int, start.split(":"))
    end_h, end_m = map(int, end.split(":"))
    return {
        "id": next(_ids), "course": course, "day": day,
        "start_min": hours * 60 + minutes, "end_min": end_h * 60 + end_m,
        "activity_type": type_, "stream_label": stream, "weeks_raw": weeks_raw,
        "weeks": list(weeks), "room": room,
        "raw_text": raw_text if raw_text is not None else f"block {course} {day} {start} {room}",
    }


def test_a_weekly_class_counts_once_in_each_hour_it_spans():
    assert heat_matrix([row(start="14:00", end="16:00")]) == {
        ("Monday", 14): 1, ("Monday", 15): 1,
    }


def test_a_block_listing_two_courses_is_one_class():
    """A shared lecture was counted once per course code."""
    text = "Lecture\nCourses: CHEM 3670; CHEM 3671"
    rows = [row(course="CHEM 3670", raw_text=text), row(course="CHEM 3671", raw_text=text)]
    assert heat_matrix(rows) == {("Monday", 17): 1}


def test_a_block_listing_two_rooms_is_one_class():
    """One class in several rooms was counted once per room."""
    text = "Exam\nRooms: ENG MD3; JFK AUD"
    rows = [row(room="ENG MD3", raw_text=text), row(room="JFK AUD", raw_text=text)]
    assert heat_matrix(rows) == {("Monday", 17): 1}


def test_parallel_groups_in_separate_blocks_stay_separate():
    """ECON 1005's Tuesday tutorials in two rooms are two classes."""
    rows = [row(room="FSS 101 E", raw_text="Tutorial, FSS 101 E"),
            row(room="FSS 102 E", raw_text="Tutorial, FSS 102 E")]
    assert heat_matrix(rows) == {("Monday", 17): 2}


def test_rows_without_block_text_never_merge():
    rows = [row(raw_text=""), row(raw_text="")]
    assert heat_matrix(rows) == {("Monday", 17): 2}


def test_a_one_off_is_not_a_weekly_class():
    """A week-8 exam counted as if it sat in that slot every week."""
    rows = [row(type_="Examination", weeks=[8]), row(type_="Lecture Relocated", weeks=[5])]
    assert heat_matrix(rows) == {}


def test_a_class_running_under_half_the_semester_is_not_typical():
    assert heat_matrix([row(weeks=range(8, 13))]) == {}
    assert heat_matrix([row(weeks=range(1, 8))]) == {("Monday", 17): 1}


def test_two_labs_alternating_weeks_fill_the_slot_every_week():
    rows = [row(course="BIOL 1262", weeks=[2, 4, 6, 8, 10, 12]),
            row(course="BIOL 1263", weeks=[1, 3, 5, 7, 9, 11])]
    assert heat_matrix(rows) == {("Monday", 17): 1}


def test_remote_teaching_is_not_on_campus():
    assert heat_matrix([row(room="Remote Teaching")]) == {}


def test_a_class_with_no_published_room_still_counts():
    """Its venue is unknown, not elsewhere."""
    rows = [row(room=None), row(room="Venue to be advised", course="MATH 1115")]
    assert heat_matrix(rows) == {("Monday", 17): 2}


def test_hours_outside_the_grid_are_left_off_it():
    early = row(start=f"{DAY_START_HOUR - 1:02d}:00", end=f"{DAY_START_HOUR + 1:02d}:00")
    late = row(start=f"{DAY_END_HOUR:02d}:00", end=f"{DAY_END_HOUR + 2:02d}:00", course="X")
    assert set(heat_matrix([early, late])) == {
        ("Monday", DAY_START_HOUR), ("Monday", DAY_END_HOUR),
    }


def test_the_grid_is_dense_and_banded_against_its_peak():
    grid = heat_grid({("Monday", 17): 10, ("Tuesday", 9): 1})
    assert grid["peak"] == 10
    assert len(grid["rows"]) == 7
    assert all(len(r["cells"]) == len(grid["hours"]) for r in grid["rows"])
    monday = {c["hour"]: c for c in grid["rows"][0]["cells"]}
    tuesday = {c["hour"]: c for c in grid["rows"][1]["cells"]}
    assert (monday[17]["count"], monday[17]["level"]) == (10, 5)
    assert (tuesday[9]["count"], tuesday[9]["level"]) == (1, 1)
    assert (monday[8]["count"], monday[8]["level"]) == (0, 0)


def test_an_empty_timetable_has_no_peak():
    grid = heat_grid({})
    assert grid["peak"] == 0
    assert all(c["level"] == 0 for r in grid["rows"] for c in r["cells"])
