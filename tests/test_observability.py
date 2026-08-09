"""
Tests for structured logging and extraction diagnostics.

The diagnostics exist because of a specific failure: an unrecognised day label
left no row for that day, and every class in it was silently filed under the
day above. These tests pin the signals that make that visible next time.
"""

from __future__ import annotations

import json
import logging

import pytest

from timetable_extractor.day_map import build_day_y_map, y_to_day
from timetable_extractor.observability import (
    CORRUPTING_FINDINGS,
    Diagnostics,
    JsonFormatter,
    correlated,
    correlation_id,
)


def margin_word(text: str, top: float) -> dict:
    """A rotated day label as pdfplumber reports it: far left, reversed text."""
    return {"text": text, "x0": 37.3, "x1": 53.3, "top": top, "bottom": top + 40}


def rule(y: float) -> dict:
    """A full-width horizontal grid rule."""
    return {"top": y, "bottom": y, "x0": 30.0, "x1": 780.0}


# Diagnostics collector


class TestDiagnostics:
    def test_counts_repeated_findings(self):
        diag = Diagnostics(source="m1.pdf")
        diag.add("day_label_unmatched", text="deW")
        diag.add("day_label_unmatched", text="deW")

        assert diag.findings["day_label_unmatched"] == 2

    def test_keeps_a_bounded_number_of_examples(self):
        """A badly broken PDF must not balloon a 1,600-file batch run."""
        diag = Diagnostics(sample_limit=2)
        for i in range(50):
            diag.add("day_fallback_used", y=i)

        assert diag.findings["day_fallback_used"] == 50
        assert len(diag.samples["day_fallback_used"]) == 2

    def test_corrupting_counts_only_misplacement_findings(self):
        diag = Diagnostics()
        diag.add("day_label_unmatched", text="deW")
        diag.add("no_entries")

        # no_entries is worth knowing but does not put a class on a wrong day.
        assert "no_entries" not in CORRUPTING_FINDINGS
        assert diag.corrupting == 1

    def test_clean_extraction_reports_nothing(self):
        diag = Diagnostics()
        assert diag.corrupting == 0
        assert diag.as_dict()["findings"] == {}

    def test_emit_logs_one_warning_per_finding(self, caplog):
        diag = Diagnostics(source="m1.pdf")
        diag.add("day_label_unmatched", text="deW")
        diag.add("day_band_missing", after="Tuesday", before="Thursday")

        logger = logging.getLogger("test.emit")
        with caplog.at_level(logging.WARNING, logger="test.emit"):
            diag.emit(logger)

        events = {r.event for r in caplog.records}
        assert events == {"extract.day_label_unmatched", "extract.day_band_missing"}
        assert all(r.source == "m1.pdf" for r in caplog.records)


# The signals that would have caught the Wednesday bug


class TestDayMapDiagnostics:
    def test_unrecognised_day_label_is_recorded(self):
        """The one signal that turns a silent misfiling into a warning."""
        diag = Diagnostics()
        build_day_y_map([margin_word("deWzz", 250)], diagnostics=diag)

        assert diag.findings["day_label_unmatched"] == 1
        assert diag.samples["day_label_unmatched"][0]["text"] == "deWzz"
        assert diag.corrupting == 1

    def test_recognised_labels_on_a_ruled_grid_record_nothing(self):
        diag = Diagnostics()
        build_day_y_map(
            [margin_word("yadnoM", 110)],
            page_width=800,
            lines=[rule(100), rule(210)],
            diagnostics=diag,
        )

        assert diag.findings == {}

    def test_a_page_without_grid_rules_is_flagged_but_not_corrupting(self):
        """
        No rules means every block is placed by proximity rather than by a row.

        Worth counting - it says how much of the corpus rests on a guess - but
        it is not itself evidence that anything was misplaced.
        """
        diag = Diagnostics()
        build_day_y_map([margin_word("yadnoM", 100)], diagnostics=diag)

        assert diag.findings["day_bands_without_rules"] == 1
        assert diag.corrupting == 0

    def test_a_missing_row_between_two_days_is_recorded(self):
        """
        A day the parser cannot name leaves a row-sized hole in the grid.

        Monday and Tuesday resolve, the third label does not, so the rules
        still describe four rows but only two are claimed.
        """
        diag = Diagnostics()
        words = [
            margin_word("yadnoM", 110),
            margin_word("yadseuT", 220),
            margin_word("deWzz", 330),  # unrecognised
            margin_word("yadsruhT", 440),
        ]
        lines = [rule(100), rule(210), rule(320), rule(430), rule(540)]

        build_day_y_map(words, page_width=800, lines=lines, diagnostics=diag)

        assert diag.findings["day_band_missing"] == 1
        gap = diag.samples["day_band_missing"][0]
        assert gap["after"] == "Tuesday"
        assert gap["before"] == "Thursday"

    def test_contiguous_rows_report_no_gap(self):
        diag = Diagnostics()
        words = [margin_word("yadnoM", 110), margin_word("yadseuT", 220)]
        lines = [rule(100), rule(210), rule(320)]

        build_day_y_map(words, page_width=800, lines=lines, diagnostics=diag)

        assert "day_band_missing" not in diag.findings

    def test_block_placed_by_fallback_is_recorded(self):
        """
        A block that lands in no row still gets a day, but by proximity.

        That guess is exactly how Wednesday's classes became Tuesday's, so it
        is counted rather than made silently.
        """
        diag = Diagnostics()
        day_map = [(100.0, 200.0, "Monday"), (200.0, 300.0, "Tuesday")]

        assert y_to_day(450, day_map, diagnostics=diag) == "Tuesday"
        assert diag.findings["day_fallback_used"] == 1
        assert diag.samples["day_fallback_used"][0]["assigned"] == "Tuesday"

    def test_block_inside_a_row_is_not_a_fallback(self):
        diag = Diagnostics()
        day_map = [(100.0, 200.0, "Monday")]

        assert y_to_day(150, day_map, diagnostics=diag) == "Monday"
        assert diag.findings == {}

    def test_no_day_map_at_all_is_recorded(self):
        diag = Diagnostics()

        assert y_to_day(150, [], diagnostics=diag) == "Unknown"
        assert diag.findings["day_unknown"] == 1

    def test_diagnostics_stay_optional(self):
        """Existing callers must keep working without passing a collector."""
        assert build_day_y_map([margin_word("yadnoM", 100)])[0][2] == "Monday"
        assert y_to_day(150, [(100.0, 200.0, "Monday")]) == "Monday"


# Structured logging


class TestJsonFormatter:
    def _format(self, **extra) -> dict:
        record = logging.LogRecord(
            "t", logging.WARNING, __file__, 1, "message", (), None
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return json.loads(JsonFormatter().format(record))

    def test_extra_fields_are_top_level_and_queryable(self):
        payload = self._format(event="extract.day_band_missing", count=3, source="m1.pdf")

        assert payload["event"] == "extract.day_band_missing"
        assert payload["count"] == 3
        assert payload["source"] == "m1.pdf"
        assert payload["level"] == "warning"

    def test_message_is_the_event_when_none_is_given(self):
        assert self._format()["event"] == "message"

    def test_correlation_id_is_attached_when_set(self):
        with correlated("abc123"):
            payload = self._format(event="request")
        assert payload["correlation_id"] == "abc123"

    def test_no_correlation_id_outside_a_context(self):
        assert "correlation_id" not in self._format(event="request")

    def test_output_is_one_json_object_per_line(self):
        record = logging.LogRecord("t", logging.INFO, __file__, 1, "hi", (), None)
        line = JsonFormatter().format(record)

        assert "\n" not in line
        json.loads(line)


class TestCorrelationContext:
    def test_id_is_restored_after_the_block(self):
        with correlated("outer"):
            with correlated("inner"):
                assert correlation_id.get() == "inner"
            assert correlation_id.get() == "outer"
        assert correlation_id.get() is None

    def test_an_id_is_generated_when_none_is_supplied(self):
        with correlated() as cid:
            assert cid and correlation_id.get() == cid
