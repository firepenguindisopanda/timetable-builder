"""
Regression tests for block text parsing.

The week-token formats below are taken verbatim from real CELCAT PDFs.
Semester 1 2026/2027 switched from the semester-prefixed form ("S2W7-S2W12")
to a bare form ("W1-W11"), so both must keep parsing.
"""

from __future__ import annotations

import pytest

from timetable_extractor.text_parser import parse_block_text


def block(text: str, line_gap: float = 9.0) -> list[dict]:
    """
    Turn a block's rendered text into the word dicts pdfplumber would give.

    The default gap keeps every line in one paragraph; pass a gap of at least
    PARAGRAPH_GAP to model a logical break (a note, or a new field group).
    """
    words = []
    for line_no, line in enumerate(text.split("\n")):
        x = 100.0
        for word in line.split():
            words.append({"top": line_no * line_gap, "x0": x, "text": word})
            x += 10.0 * len(word)
    return words


class TestWeeks:
    @pytest.mark.parametrize(
        "text,expected",
        [
            # -- Current format (Semester 1 2026/2027) --
            ("Lecture, Wks W1-W11 [=11]\nCourse: ACCT 6200", "W1-W11"),
            # Week token wrapped across rendered lines in a narrow block
            ("Lecture,\nWks W1-\nW11 [=11]\nCourse: ADRR 3001", "W1-W11"),
            # Comma-separated multi-range (a week skipped mid-semester)
            ("Lecture, Wks W1-W7, W9-W12 [=11]\nCourse: ACCT 1002", "W1-W7, W9-W12"),
            # Single relocated week uses the singular "Wk" label
            ("Lecture Relocated, Wk W8\nCourse: ACCT 1002", "W8"),
            # Fortnightly tutorials list individual weeks
            (
                "Tutorial, Wks W1, W3, W5, W7, W9, W11 [=6]\nCourse: CHEM 1170",
                "W1, W3, W5, W7, W9, W11",
            ),
            # ...and wrap across lines when the block is narrow
            (
                "Tutorial,\nWks W1,\nW3, W5,\nW7, W9,\nW11 [=6]\nCourse: CHEM 1170",
                "W1, W3, W5, W7, W9, W11",
            ),
            # -- Legacy formats, must keep working --
            ("Lecture, Wks S2W7-S2W12 [=6]\nCourse: COMP 2603", "S2W7-S2W12"),
            ("Lecture, Wks S2W7- S2W12 [=6]\nCourse: COMP 2603", "S2W7-S2W12"),
            ("Lab, Wks SUM W1-SUM W7 [=7]\nCourse: COMP 1600", "SUM W1-SUM W7"),
        ],
    )
    def test_week_formats(self, text: str, expected: str):
        assert parse_block_text(block(text))["weeks"] == expected

    def test_unlabelled_legacy_range_still_found(self):
        # Older blocks sometimes carried a range with no "Wks" label.
        assert parse_block_text(block("S2W7-S2W12 COMP 2603"))["weeks"] == "S2W7-S2W12"

    def test_no_weeks_present(self):
        assert parse_block_text(block("Course: COMP 2603\nRoom: Lab"))["weeks"] is None

    def test_week_count(self):
        assert parse_block_text(block("Wks W1-W11 [=11]"))["week_count"] == 11


class TestFields:
    def test_keyword_fields(self):
        result = parse_block_text(
            block("Lecture, Wks W1-W12 [=12]\nCourse: ACCT 1002\nStaff: SMITH,J\nRoom: TLC LT A1")
        )
        assert result["type"] == "Lecture"
        assert result["course"] == "ACCT 1002"
        assert result["staff"] == "SMITH,J"
        assert result["room"] == "TLC LT A1"

    def test_values_wrapped_across_lines(self):
        result = parse_block_text(
            block("Lecture,\nCourse:\nADRR 3001\nRoom:\nRemote\nTeaching")
        )
        assert result["course"] == "ADRR 3001"
        assert result["room"] == "Remote Teaching"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Lecture, Wks W1-W11", "Lecture"),
            ("Lab, Wks W1-W11", "Lab"),
            ("Tutorial, Wks W1-W11", "Tutorial"),
            ("Postgraduate, Wks W1-W11", "Postgraduate"),
            # Types beyond the four that used to be hardcoded
            ("Field Trip, Wks W3-W4", "Field Trip"),
            ("Lecture Relocated, Wk W8", "Lecture Relocated"),
            ("Practical, Wks W1-W11", "Practical"),
            ("Project Work, Wks W1-W11", "Project Work"),
            ("Lecture & Tutorial, Wks W1-W11", "Lecture & Tutorial"),
            ("Video Presentation / Screening, Wks W1-W11", "Video Presentation / Screening"),
            ("Tutorial (make-up/relocated), Wk W8", "Tutorial (make-up/relocated)"),
        ],
    )
    def test_activity_types(self, text: str, expected: str):
        assert parse_block_text(block(text))["type"] == expected

    @pytest.mark.parametrize(
        "split,expected",
        [
            ("Postgradua te", "Postgraduate"),
            ("Postgrad uate", "Postgraduate"),
            ("Examinatio n", "Examination"),
            ("RESERVE D", "Reserved"),
        ],
    )
    def test_type_split_across_narrow_lines(self, split: str, expected: str):
        # A narrow block wraps mid-word; the fragments must still resolve.
        assert parse_block_text(block(f"{split}, Wks W1-W11"))["type"] == expected

    def test_unknown_type_is_kept_verbatim(self):
        # A type CELCAT adds later should surface rather than vanish.
        assert parse_block_text(block("Fencing Practice, Wks W1-W11"))["type"] == (
            "Fencing Practice"
        )

    def test_block_without_a_type(self):
        assert parse_block_text(block("Wks W1-W2 [=2]\nCourse: MATH 0100"))["type"] is None


class TestNotes:
    """
    Timetablers append free-text notes to a block. They render as their own
    paragraph, and must not be glued onto the room or course.
    """

    @staticmethod
    def with_note(body: str, note: str) -> list[dict]:
        """Lay a note out as its own paragraph below the block's fields."""
        body_words = block(body)
        note_words = block(note)
        offset = max(w["top"] for w in body_words) + 100.0
        for w in note_words:
            w["top"] += offset
        return body_words + note_words

    def test_note_after_room_is_separated(self):
        result = parse_block_text(
            self.with_note(
                "Lecture,\nWks W1-W12\nCourse: AGLS 3000\nRoom: FFA W",
                "Lecture when\nthere is no\nLab/Field Trip",
            )
        )
        assert result["room"] == "FFA W"
        assert result["notes"] == "Lecture when there is no Lab/Field Trip"

    def test_note_after_course_is_separated(self):
        result = parse_block_text(
            self.with_note(
                "Field Trip, Wks W3-W4 [=2]\nCourse: AGLS 2004",
                "From 7:00am-Field trip date to be confirmed",
            )
        )
        assert result["course"] == "AGLS 2004"
        assert result["notes"] == "From 7:00am-Field trip date to be confirmed"

    def test_no_notes_when_block_is_plain(self):
        assert parse_block_text(block("Lecture, Wks W1-W12\nRoom: TLC LT B"))["notes"] is None


class TestPluralLabels:
    """A block shared by several courses or rooms uses the plural label."""

    def test_courses_label(self):
        result = parse_block_text(
            block("Chemistry Review Centre, Wks W3-W12 [=10]\nCourses: CHEM 1075; CHEM 1080")
        )
        assert result["type"] == "Chemistry Review Centre"
        assert result["course"] == "CHEM 1075; CHEM 1080"

    def test_rooms_label(self):
        result = parse_block_text(block("Lecture, Wks W1-W12\nRooms: FST 415; FST 416"))
        assert result["room"] == "FST 415; FST 416"

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("Lab (L2), Wks W1-W11", "L2"),
            ("Tutorial (T3), Wks W1-W11", "T3"),
            ("Lecture (G1), Wks W1-W11", "G1"),
        ],
    )
    def test_stream_label(self, text: str, expected: str):
        # Students choose one stream per course, so tutorial and group markers
        # matter as much as lab ones for resolving clashes.
        assert parse_block_text(block(text))["group_label"] == expected

    def test_stream_label_is_stripped_from_the_room(self):
        result = parse_block_text(block("Tutorial, Wks W1-W12\nRoom: FST 114 (T1)"))
        assert result["room"] == "FST 114"
        assert result["group_label"] == "T1"


class TestRoomNames:
    """
    Room names ending in a single letter are real, distinct rooms in CELCAT's
    room registry - "FSS 101 W" and "FSS 101 E" are the west and east wings,
    and "TLC LT B"/"TLC LT D" are different lecture theatres. Truncating that
    letter sends students to the wrong place.
    """

    @pytest.mark.parametrize(
        "room",
        ["FSS 101 W", "FSS 101 E", "FSS 102 W", "TLC LT B", "TLC LT D", "FFA A", "FFA C", "FFA B1"],
    )
    def test_trailing_letter_is_preserved(self, room: str):
        text = f"Lecture, Wks W1-W12 [=12]\nCourse: ACCT 1002\nRoom: {room}"
        assert parse_block_text(block(text))["room"] == room

    def test_bleed_from_neighbouring_block_is_trimmed(self):
        # Text from an adjacent block can bleed into a narrow block's words.
        text = "Lecture, Wks W1-W12 [=12]\nCourse: ACCT 1002\nRoom: FSS 103\nW1-W12 [=12]\n1002\nA1"
        assert parse_block_text(block(text))["room"] == "FSS 103"
