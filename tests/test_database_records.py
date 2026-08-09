"""
Tests for week expansion and the cross-source session merge.

These cover the logic that turns three overlapping views of the timetable -
the course, room and staff PDFs - into one set of session rows, without
touching a database.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database.records import (
    SessionRecord,
    merge_records,
    normalise_course_code,
    records_from_extraction,
    split_courses,
    split_rooms,
    split_staff,
    time_to_minutes,
)
from timetable_extractor.database.weeks import expand_weeks, weeks_overlap


class TestExpandWeeks:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("W1-W11", list(range(1, 12))),
            ("W1-W7, W9-W12", [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12]),
            ("W1, W3, W5, W7, W9, W11", [1, 3, 5, 7, 9, 11]),
            ("W8", [8]),
            ("S2W7-S2W12", [7, 8, 9, 10, 11, 12]),
            ("SUM W1-SUM W7", [1, 2, 3, 4, 5, 6, 7]),
            ("W3-W4", [3, 4]),
        ],
    )
    def test_expansion(self, raw: str, expected: list[int]):
        assert expand_weeks(raw) == expected

    @pytest.mark.parametrize("raw", [None, "", "not a week expression"])
    def test_unparseable_is_empty(self, raw):
        assert expand_weeks(raw) == []

    def test_duplicates_collapse(self):
        assert expand_weeks("W1-W3, W2-W4") == [1, 2, 3, 4]


class TestWeeksOverlap:
    def test_disjoint_ranges_do_not_overlap(self):
        # The pair that makes a calendar clash look real when it is not.
        assert weeks_overlap("W1-W7", "W9-W12") is False

    def test_shared_week_overlaps(self):
        assert weeks_overlap("W1-W7", "W7-W12") is True

    def test_unknown_weeks_assumed_to_overlap(self):
        # Warning about a clash that may not exist beats hiding a real one.
        assert weeks_overlap(None, "W1-W12") is True


class TestNormalisation:
    @pytest.mark.parametrize(
        "raw,expected",
        [("comp 2601", "COMP 2601"), ("COMP  2601", "COMP 2601"), (" COMP 2601 ", "COMP 2601")],
    )
    def test_course_code(self, raw: str, expected: str):
        assert normalise_course_code(raw) == expected

    def test_split_courses(self):
        assert split_courses("CHEM 1075; CHEM 1080") == ["CHEM 1075", "CHEM 1080"]

    def test_split_rooms(self):
        assert split_rooms("FST 415; FST 416") == ["FST 415", "FST 416"]

    def test_split_staff_strips_annotation(self):
        assert split_staff("AUSTIN, Nigel (*); HULME, Mark") == [
            "AUSTIN, Nigel",
            "HULME, Mark",
        ]

    @pytest.mark.parametrize(
        "label,expected",
        [("09:00 AM", 540), ("12:00 PM", 720), ("12:00 AM", 0), ("05:00 PM", 1020)],
    )
    def test_time_to_minutes(self, label: str, expected: int):
        assert time_to_minutes(label) == expected

    def test_unparseable_time(self):
        assert time_to_minutes("?") is None


def extraction(entries: list[dict], semester: str = "Semester_1_TT2026_2027") -> dict:
    return {"semester": semester, "entries": entries}


def entry(**overrides) -> dict:
    base = {
        "day": "Monday",
        "start_time": "09:00 AM",
        "end_time": "10:00 AM",
        "type": "Lecture",
        "weeks": "W1-W12",
        "week_count": 12,
        "course": "COMP 2601",
        "staff": None,
        "room": "TLC LT E",
        "group_label": None,
        "notes": None,
        "raw_text": "",
    }
    base.update(overrides)
    return base


class TestRecordsFromExtraction:
    def test_basic_record(self):
        [record] = records_from_extraction(extraction([entry()]), source="m62596.pdf")
        assert record.course_code == "COMP 2601"
        assert (record.start_min, record.end_min) == (540, 600)
        assert record.weeks == list(range(1, 13))
        assert record.sources == {"m62596.pdf"}

    def test_unplaceable_entries_are_dropped(self):
        entries = [
            entry(day="Unknown"),
            entry(start_time="?"),
            entry(end_time="09:00 AM"),  # end not after start
            entry(course=None),
        ]
        assert records_from_extraction(extraction(entries), source="x.pdf") == []

    def test_shared_block_yields_one_record_per_course(self):
        records = records_from_extraction(
            extraction([entry(course="CHEM 1075; CHEM 1080")]), source="m1.pdf"
        )
        assert sorted(r.course_code for r in records) == ["CHEM 1075", "CHEM 1080"]

    def test_multi_room_block_yields_one_record_per_room(self):
        records = records_from_extraction(
            extraction([entry(room="FST 415; FST 416")]), source="m1.pdf"
        )
        assert sorted(r.room_code or "" for r in records) == ["FST 415", "FST 416"]


class TestMerge:
    def test_same_class_from_two_pdfs_becomes_one_record(self):
        # The course PDF names the room; the room PDF names the teacher.
        from_course = records_from_extraction(
            extraction([entry(staff=None)]), source="m62596.pdf"
        )
        from_room = records_from_extraction(
            extraction([entry(staff="RAGBIR-SHRIPAT, Diana")]), source="r3340.pdf"
        )

        [merged] = merge_records(from_course + from_room)
        assert merged.staff == ["RAGBIR-SHRIPAT, Diana"]
        assert merged.sources == {"m62596.pdf", "r3340.pdf"}

    def test_parallel_streams_in_different_rooms_stay_separate(self):
        # LAW 0101 runs concurrent tutorials with no stream label to tell them
        # apart; merging them would hide a choice the student has to make.
        records = records_from_extraction(
            extraction(
                [
                    entry(course="LAW 0101", type="Tutorial", room="ENG 104"),
                    entry(course="LAW 0101", type="Tutorial", room="ENG 105"),
                ]
            ),
            source="m103865.pdf",
        )
        assert len(merge_records(records)) == 2

    def test_relocated_session_is_not_merged_into_the_original(self):
        records = records_from_extraction(
            extraction(
                [
                    entry(type="Lecture", weeks="W1-W7, W9-W12", room="TLC LT B"),
                    entry(type="Lecture Relocated", weeks="W8", room="TCB 23"),
                ]
            ),
            source="m11814.pdf",
        )
        assert len(merge_records(records)) == 2

    def test_roomless_record_adopts_an_unambiguous_room(self):
        roomless = records_from_extraction(
            extraction([entry(room=None, staff="SMITH, J")]), source="s1.pdf"
        )
        roomed = records_from_extraction(extraction([entry()]), source="m62596.pdf")

        [merged] = merge_records(roomless + roomed)
        assert merged.room_code == "TLC LT E"
        assert merged.staff == ["SMITH, J"]
        assert merged.sources == {"s1.pdf", "m62596.pdf"}

    def test_roomless_record_kept_when_the_room_is_ambiguous(self):
        # Two candidate rooms: adopting either would invent a fact.
        roomless = records_from_extraction(
            extraction([entry(course="LAW 0101", room=None)]), source="s1.pdf"
        )
        roomed = records_from_extraction(
            extraction(
                [
                    entry(course="LAW 0101", room="ENG 104"),
                    entry(course="LAW 0101", room="ENG 105"),
                ]
            ),
            source="m103865.pdf",
        )
        assert len(merge_records(roomless + roomed)) == 3

    def test_record_without_a_stream_marker_folds_into_the_labelled_one(self):
        # Staff timetables often omit the "(T1)" the course timetable prints;
        # left unmerged these become two rows for the same tutorial.
        labelled = records_from_extraction(
            extraction([entry(type="Tutorial", group_label="T1", room="FST C2")]),
            source="m25299.pdf",
        )
        unlabelled = records_from_extraction(
            extraction([entry(type="Tutorial", group_label=None, room="FST C2",
                              staff="HULME, Mark")]),
            source="s98074.pdf",
        )

        [merged] = merge_records(labelled + unlabelled)
        assert merged.stream_label == "T1"
        assert merged.staff == ["HULME, Mark"]
        assert merged.sources == {"m25299.pdf", "s98074.pdf"}

    def test_record_missing_both_room_and_stream_still_folds(self):
        full = records_from_extraction(
            extraction([entry(room="TCB 23", group_label="T2")]), source="m1.pdf"
        )
        bare = records_from_extraction(
            extraction([entry(room=None, group_label=None, staff="X, Y")]), source="s1.pdf"
        )
        [merged] = merge_records(full + bare)
        assert (merged.room_code, merged.stream_label) == ("TCB 23", "T2")

    def test_conflicting_stream_markers_are_kept_apart(self):
        # T1 and T2 in the same room at the same hour are different streams.
        records = records_from_extraction(
            extraction(
                [
                    entry(room="FST C2", group_label="T1"),
                    entry(room="FST C2", group_label="T2"),
                ]
            ),
            source="m1.pdf",
        )
        assert len(merge_records(records)) == 2

    def test_staff_are_unioned_without_duplicates(self):
        a = records_from_extraction(extraction([entry(staff="A, One")]), source="m1.pdf")
        b = records_from_extraction(
            extraction([entry(staff="A, One; B, Two")]), source="r1.pdf"
        )
        [merged] = merge_records(a + b)
        assert merged.staff == ["A, One", "B, Two"]

    def test_merge_output_is_day_ordered(self):
        records = [
            SessionRecord(course_code="X 1", day="Friday", start_min=540, end_min=600),
            SessionRecord(course_code="X 1", day="Monday", start_min=540, end_min=600),
        ]
        assert [r.day for r in merge_records(records)] == ["Monday", "Friday"]
