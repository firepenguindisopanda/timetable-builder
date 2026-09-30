"""
Regression tests for class block detection.

A class block is found as a cluster of shaded header bars with words under it.
On 29 Sep 2026 PHPP 0301 (m111089.pdf) arrived in a different CELCAT template
whose time axis is shaded too and labels every hour cell with its start *and*
end time. Each of those cells then read as a class: about 56 untyped entries
per PDF, every one with an impossible "09:00 AM-09:00 AM" time range.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from timetable_extractor.blocks import identify_class_blocks
from timetable_extractor.extract import extract_timetable

FIXTURE = Path(__file__).parent / "fixtures" / "m111089_paired_time_axis.pdf"


def shaded(x0: float, x1: float, top: float) -> dict:
    return {"fill": True, "x0": x0, "x1": x1, "width": x1 - x0, "top": top, "bottom": top + 4}


def word(text: str, x0: float, top: float) -> dict:
    return {"text": text, "x0": x0, "x1": x0 + 30, "top": top, "bottom": top + 8}


class TestHeaderCellsAreNotClasses:
    def test_a_shaded_time_axis_cell_is_not_a_class_block(self):
        rects = [shaded(100, 160, 92)]
        words = [word("08:00AM", 102, 95), word("09:00AM", 128, 95)]

        assert identify_class_blocks(words, rects) == []

    def test_a_class_block_beside_the_time_axis_is_kept(self):
        rects = [shaded(100, 160, 92), shaded(100, 220, 130)]
        words = [
            word("08:00AM", 102, 95),
            word("09:00AM", 128, 95),
            word("Lecture,", 102, 134),
            word("Wks", 135, 134),
            word("W1-W12", 102, 144),
        ]

        blocks = identify_class_blocks(words, rects)

        assert len(blocks) == 1
        assert [w["text"] for w in blocks[0]["words"]] == ["Lecture,", "Wks", "W1-W12"]


@pytest.mark.skipif(not FIXTURE.exists(), reason="PHPP 0301 fixture PDF is missing")
class TestPairedTimeAxisTemplate:
    """The real PDF: only its classes come out, on the right day and hours."""

    @pytest.fixture(scope="class")
    def result(self):
        return extract_timetable(FIXTURE)

    def test_no_entry_is_untyped(self, result):
        assert [e for e in result["entries"] if not e.get("type")] == []

    def test_no_entry_ends_where_it_starts(self, result):
        assert [e for e in result["entries"] if e["start_time"] == e["end_time"]] == []

    def test_the_lectures_are_friday_noon_to_three(self, result):
        # The same three lectures the 17 Sep publication carried from the usual
        # template, plus the relocated sitting this republish added.
        assert sorted((e["day"], e["start_time"], e["end_time"], e["type"]) for e in result["entries"]) == [
            ("Friday", "12:00 PM", "03:00 PM", "Lecture"),
            ("Friday", "12:00 PM", "03:00 PM", "Lecture"),
            ("Friday", "12:00 PM", "03:00 PM", "Lecture"),
            ("Friday", "12:00 PM", "03:00 PM", "Lecture Relocated"),
        ]

    def test_no_day_is_guessed(self, result):
        findings = result["diagnostics"]["findings"]
        assert "day_label_unmatched" not in findings
        assert "day_fallback_used" not in findings
