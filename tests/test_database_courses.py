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
    find_published_code,
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


class FakeCursor:
    """
    Answers `find_published_code`'s lookup out of a list of published codes.

    It also records the keys it was asked for, because the order of the two
    attempts is the behaviour under test rather than an implementation detail.
    """

    def __init__(self, published: list[str]) -> None:
        self._published = published
        self._row: tuple[str] | None = None
        self.keys_tried: list[str] = []

    def execute(self, sql: str, params: tuple) -> None:
        (key,) = params
        self.keys_tried.append(key)
        self._row = next(
            ((code,) for code in self._published if code_key(code) == key), None
        )

    def fetchone(self) -> tuple[str] | None:
        return self._row


class TestFindPublishedCode:
    """
    Matching a code a student typed against what the university published.

    Normalising alone answered 404 for two real shapes: it splits "WW101" at
    the digit, and it eats the hyphen inside
    "FOUN 1001 (FULL & PART-TIME)". Both are published courses, and the second
    is one most of the campus takes.
    """

    @pytest.fixture
    def cursor(self) -> FakeCursor:
        return FakeCursor(CANONICAL)

    @pytest.mark.parametrize("code", CANONICAL)
    def test_a_published_code_finds_itself(self, code, cursor):
        assert find_published_code(cursor, code) == code

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("comp2601", "COMP 2601"),
            ("COMP2601", "COMP 2601"),
            ("  comp   2601  ", "COMP 2601"),
            # The hyphen-separated form the explorer's URLs accept.
            ("comp-2601", "COMP 2601"),
        ],
    )
    def test_spacing_and_case_do_not_matter(self, raw, expected, cursor):
        assert find_published_code(cursor, raw) == expected

    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("WW101", "WW101"),
            ("ww101", "WW101"),
            ("WW 101", "WW101"),
            ("FOUN 1001 (FULL & PART-TIME)", "FOUN 1001 (FULL & PART-TIME)"),
            ("foun 1001 (full & part-time)", "FOUN 1001 (FULL & PART-TIME)"),
        ],
    )
    def test_the_shapes_normalising_alone_would_lose(self, raw, expected, cursor):
        assert find_published_code(cursor, raw) == expected

    def test_what_the_caller_wrote_is_tried_before_the_normalised_form(self, cursor):
        """
        The hyphen in "FOUN 1001 (FULL & PART-TIME)" is only survivable this
        way round: once normalising has turned it into a space, no amount of
        ignoring spacing gets it back.
        """
        find_published_code(cursor, "FOUN 1001 (FULL & PART-TIME)")

        assert cursor.keys_tried == [code_key("FOUN 1001 (FULL & PART-TIME)")]

    def test_a_code_already_in_its_published_form_costs_one_query(self, cursor):
        find_published_code(cursor, "COMP 2601")

        assert len(cursor.keys_tried) == 1

    def test_an_unknown_code_is_not_found(self, cursor):
        assert find_published_code(cursor, "ZZZZ 9999") is None

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_an_empty_code_is_not_found_and_costs_no_query(self, raw, cursor):
        assert find_published_code(cursor, raw) is None
        assert cursor.keys_tried == []
