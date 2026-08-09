"""
Tests for course-code resolution.

Every corrupted form below came from a real PDF. Each one had created its own
course row, splitting a genuine course's timetable in two.

Note that a parenthetical suffix is often part of the real code: UWI publishes
both "FOUN 1001 (ALJGSB)" and "FOUN 1001 (FULL & PART-TIME)" as separate
courses. Only the mid-word wrap needs repairing there, not the qualifier.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database.courses import (
    build_code_index,
    code_key,
    resolve_course_code,
)

CANONICAL = [
    "FOUN 1001 (ALJGSB)",
    "FOUN 1001 (FULL & PART-TIME)",
    "IENG 3017",
    "ENGR 1001",
    "CLL PORTUGUESE 1A",
    "CAPE BIOL",
    "COMP 2601",
    "WW101",
]


@pytest.fixture
def index() -> dict[str, str]:
    return build_code_index(CANONICAL)


class TestResolveCourseCode:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Wrapped mid-word by a narrow column
            ("CLL PORTUGU ESE 1A", "CLL PORTUGUESE 1A"),
            # Wrapped inside a qualifier that is part of the real code
            ("FOUN 1001 (FULL & PART- TIME)", "FOUN 1001 (FULL & PART-TIME)"),
            # Trailing text swallowed from the same line
            ("IENG 3017 LALLA,TERRENCE", "IENG 3017"),
            ("ENGR 1001 MECH AND CHEM ENGINEERING -", "ENGR 1001"),
            # Already clean
            ("COMP 2601", "COMP 2601"),
            ("WW101", "WW101"),
        ],
    )
    def test_variants_resolve(self, raw: str, expected: str, index):
        assert resolve_course_code(raw, index) == expected

    def test_multi_word_code_is_not_truncated(self):
        # "CAPE BIOL" must survive: a greedy prefix walk could cut it to "CAPE".
        index = build_code_index(["CAPE BIOL", "CAPE"])
        assert resolve_course_code("CAPE BIOL", index) == "CAPE BIOL"

    def test_longest_matching_prefix_wins(self):
        index = build_code_index(["ENGR 1001", "ENGR 1001 A"])
        assert resolve_course_code("ENGR 1001 A MECH AND CHEM", index) == "ENGR 1001 A"

    def test_qualifier_distinguishes_two_real_courses(self, index):
        # These are different courses; resolution must not collapse them.
        assert resolve_course_code("FOUN 1001 (ALJGSB)", index) == "FOUN 1001 (ALJGSB)"
        assert (
            resolve_course_code("FOUN 1001 (FULL & PART-TIME)", index)
            == "FOUN 1001 (FULL & PART-TIME)"
        )

    def test_unknown_code_is_left_alone(self, index):
        # A course absent from the index must not be silently rewritten.
        assert resolve_course_code("ZZZZ 9999", index) == "ZZZZ 9999"

    def test_code_key_ignores_spacing_and_case(self):
        assert code_key("CLL PORTUGU ESE 1A") == code_key("cllportuguese1a")
