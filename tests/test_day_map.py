"""
Regression tests for day-label detection.

CELCAT renders the day label rotated in the left margin, so pdfplumber reads
it reversed ("Monday" -> "yadnoM"). Both the abbreviated and full-word forms
appear, depending on how tall that day's row is. A label that fails to resolve
does not merely go missing: y_to_day falls through to the previous label, so
those classes are silently reported on the wrong day.
"""

from __future__ import annotations

import pytest

from timetable_extractor.constants import REVERSED_DAYS
from timetable_extractor.day_map import build_day_y_map, horizontal_rules, y_to_day

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def margin_word(text: str, top: float) -> dict:
    """A rotated day label as pdfplumber reports it: far left, reversed text."""
    return {"text": text, "x0": 37.3, "x1": 53.3, "top": top, "bottom": top + 40}


class TestReversedDayLabels:
    @pytest.mark.parametrize("day", DAYS)
    def test_full_word_label_resolves(self, day: str):
        # The full-word label is literally the day name reversed.
        label = day[::-1]
        found = build_day_y_map([margin_word(label, 100)])
        assert found and found[0][2] == day, f"{label!r} did not resolve to {day}"

    def test_wednesday_full_word(self):
        # Regression: this key was stored as "yadsendew" (lowercase w), so every
        # full-word Wednesday label silently fell through to the adjacent day.
        assert build_day_y_map([margin_word("yadsendeW", 251.2)])[0][2] == "Wednesday"

    @pytest.mark.parametrize(
        "label,day",
        [
            ("noM", "Monday"),
            ("euT", "Tuesday"),
            ("eW", "Wednesday"),
            ("uhT", "Thursday"),
            ("irF", "Friday"),
            ("taS", "Saturday"),
            ("nuS", "Sunday"),
        ],
    )
    def test_abbreviated_label_resolves(self, label: str, day: str):
        assert build_day_y_map([margin_word(label, 100)])[0][2] == day

    def test_every_configured_key_resolves(self):
        """No entry in the table may be unreachable through the lookup."""
        for key, expected in REVERSED_DAYS.items():
            found = build_day_y_map([margin_word(key, 100)])
            assert found, f"REVERSED_DAYS key {key!r} does not resolve"
            assert found[0][2] == expected

    def test_labels_outside_left_margin_are_ignored(self):
        # A block body word that happens to match must not be read as a label.
        word = {"text": "yadnoM", "x0": 300.0, "x1": 340.0, "top": 100, "bottom": 140}
        assert build_day_y_map([word]) == []


class TestYToDay:
    def test_maps_block_to_nearest_label_above(self):
        day_map = build_day_y_map(
            [
                margin_word("yadnoM", 100),
                margin_word("yadseuT", 300),
                margin_word("yadsendeW", 500),
            ]
        )
        assert y_to_day(120, day_map) == "Monday"
        assert y_to_day(320, day_map) == "Tuesday"
        assert y_to_day(520, day_map) == "Wednesday"

    def test_unknown_when_page_has_no_labels(self):
        assert y_to_day(200, []) == "Unknown"


def rule(top: float, width: float = 700.0) -> dict:
    """A full-width horizontal grid rule as pdfplumber reports it."""
    return {"top": top, "bottom": top, "x0": 28.4, "x1": 28.4 + width}


class TestGridRows:
    """
    Day rows come from the timetable's own horizontal rules. Labels are
    centred in their row, so a tall row's label sits far from the row edges -
    inferring the row from the label alone puts blocks in the wrong day.
    """

    # Real geometry from COMP 2601: Wednesday's row is 120pt tall and the
    # Thursday block starts at 345.6, above Thursday's label but below the
    # 339.4 rule that starts Thursday's row.
    RULES = [113.6, 166.2, 218.8, 339.4, 478.0]
    LABELS = [
        margin_word("yadnoM", 121.7),
        margin_word("yadseuT", 176.0),
        margin_word("yadsendeW", 229.2),
        margin_word("yadsruhT", 368.2),
    ]

    def build(self):
        return build_day_y_map(
            self.LABELS,
            page_width=792.0,
            lines=[rule(top) for top in self.RULES],
        )

    def test_rows_snap_to_grid_rules(self):
        rows = self.build()
        assert [(lo, hi, day) for lo, hi, day in rows] == [
            (113.6, 166.2, "Monday"),
            (166.2, 218.8, "Tuesday"),
            (218.8, 339.4, "Wednesday"),
            (339.4, 478.0, "Thursday"),
        ]

    def test_block_below_a_tall_row_belongs_to_the_next_day(self):
        # 345.6 is past Wednesday's row despite being above Thursday's label.
        assert y_to_day(345.6, self.build()) == "Thursday"

    def test_block_inside_a_tall_row_stays_put(self):
        assert y_to_day(225.0, self.build()) == "Wednesday"

    def test_block_starting_just_above_its_rule(self):
        # The highlight bar may sit a hair above the row's top rule.
        assert y_to_day(112.0, self.build()) == "Monday"

    def test_narrow_lines_are_not_grid_rules(self):
        lines = [rule(100.0, width=50.0), rule(200.0, width=700.0)]
        assert horizontal_rules(lines, 792.0) == [200.0]

    def test_vertical_lines_are_not_grid_rules(self):
        lines = [{"top": 100.0, "bottom": 400.0, "x0": 28.4, "x1": 728.4}]
        assert horizontal_rules(lines, 792.0) == []

    def test_falls_back_to_labels_without_rules(self):
        rows = build_day_y_map(self.LABELS, page_width=792.0, lines=[])
        assert [day for _, _, day in rows] == [
            "Monday", "Tuesday", "Wednesday", "Thursday",
        ]
        assert y_to_day(225.0, rows) == "Wednesday"
