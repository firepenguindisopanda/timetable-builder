"""
Tests for the corpus validator's pass/fail gate.

The gate is what makes the script usable in CI, so it needs to actually fail
on the conditions it claims to catch - a green run that ignores a real defect
is worse than no check at all.
"""

from __future__ import annotations

from collections import Counter

import pytest

import validate_corpus


def report_input(**stats) -> dict:
    """A minimal clean report, overridden per test."""
    base = {
        "sessions": 0,
        "entries": 100,
        "files": 10,
        "has_day": 100,
        "has_start_time": 100,
        "has_end_time": 100,
        "course_codes_seen": 100,
    }
    base.update(stats)
    return {
        "elapsed_sec": 1.0,
        "pdf_count": 10,
        "stats": base,
        "semesters": {},
        "types": {},
        "days": {},
        "crashes": [],
        "empty": [],
        "bad_times": [],
        "course_mismatch": [],
        "multi_session": [],
        "unknown_codes": [],
        "repaired_codes": [],
        "unknown_rooms": [],
        "room_registry_size": 0,
    }


BALANCED_WEEK = {
    "Monday": 749, "Tuesday": 700, "Wednesday": 690,
    "Thursday": 567, "Friday": 548,
}

# The corpus as it actually looked while "Wed" reversed was unrecognised:
# Wednesday's classes filed under Tuesday.
SKEWED_WEEK = {
    "Monday": 749, "Tuesday": 1294, "Wednesday": 567,
    "Thursday": 567, "Friday": 548,
}


class TestDaySkew:
    """
    The corpus-level histogram is the only place a lost day label shows up.

    Each PDF still parses cleanly and every field is populated - the classes
    are simply on the wrong row - so coverage checks cannot see it.
    """

    def test_a_balanced_week_is_not_skewed(self):
        skew = validate_corpus.day_skew(Counter(BALANCED_WEEK))

        assert skew["skewed"] is False
        assert skew["busiest"] == "Monday"

    def test_the_wednesday_bug_is_caught(self):
        skew = validate_corpus.day_skew(Counter(SKEWED_WEEK))

        assert skew["skewed"] is True
        assert skew["busiest"] == "Tuesday"
        assert skew["ratio"] == pytest.approx(2.28, abs=0.01)

    def test_an_empty_corpus_does_not_divide_by_zero(self):
        skew = validate_corpus.day_skew(Counter())

        assert skew["ratio"] is None
        assert skew["skewed"] is False

    def test_weekend_classes_do_not_count_towards_the_median(self):
        """Saturday and Sunday are legitimately near-empty and would drag it down."""
        weekdays_only = validate_corpus.day_skew(Counter(BALANCED_WEEK))
        with_weekend = validate_corpus.day_skew(
            Counter({**BALANCED_WEEK, "Saturday": 4, "Sunday": 1})
        )

        assert with_weekend["median"] == weekdays_only["median"]
        assert with_weekend["skewed"] is False


class TestGate:
    def test_skewed_days_fail_the_gate(self, capsys):
        report = report_input()
        report["days"] = SKEWED_WEEK

        assert validate_corpus.report(report, fail_under=99.0) == 1
        assert "2.28x" in capsys.readouterr().out

    def test_corrupting_findings_fail_the_gate(self, capsys):
        """An unmatched day label never crashes, so the gate must catch it."""
        report = report_input()
        report["findings"] = {"day_label_unmatched": 22}

        assert validate_corpus.report(report, fail_under=99.0) == 1
        assert "day_label_unmatched" in capsys.readouterr().out

    def test_non_corrupting_findings_do_not_fail_the_gate(self, capsys):
        report = report_input()
        report["findings"] = {"day_bands_without_rules": 5}

        assert validate_corpus.report(report, fail_under=99.0) == 0
        assert "PASSED" in capsys.readouterr().out

    def test_a_report_without_the_new_keys_still_runs(self):
        """Older --json reports predate these checks and must still print."""
        report = report_input()
        report["days"] = BALANCED_WEEK
        for key in ("day_skew", "findings", "finding_samples"):
            report.pop(key, None)

        # The skew is recomputed from `days` rather than demanded of the file.
        assert validate_corpus.report(report, fail_under=99.0) == 0

    def test_clean_report_passes(self, capsys):
        assert validate_corpus.report(report_input(), fail_under=99.0) == 0
        assert "PASSED" in capsys.readouterr().out

    def test_unknown_course_code_fails(self, capsys):
        # The defect that split a real course's timetable across two rows.
        result = report_input(unknown_course_code=3)
        assert validate_corpus.report(result, fail_under=99.0) == 1
        assert "absent from the registry" in capsys.readouterr().out

    def test_repaired_codes_alone_do_not_fail(self):
        # A repairable code is a warning: the loader resolves it correctly.
        assert validate_corpus.report(report_input(repaired_course_code=57), 99.0) == 0

    @pytest.mark.parametrize(
        "stat", ["bad_day", "bad_start", "end_before_start"]
    )
    def test_sanity_violations_fail(self, stat: str):
        assert validate_corpus.report(report_input(**{stat: 1}), 99.0) == 1

    def test_missing_required_field_fails(self):
        assert validate_corpus.report(report_input(has_day=50), 99.0) == 1

    def test_crash_fails(self):
        result = report_input()
        result["crashes"] = [{"file": "m1.pdf", "error": "boom"}]
        assert validate_corpus.report(result, 99.0) == 1

    def test_empty_extraction_fails(self):
        result = report_input()
        result["empty"] = ["m1.pdf"]
        assert validate_corpus.report(result, 99.0) == 1
