"""
Tests for staff-name resolution.

Narrow columns wrap names mid-word and the fragments come back joined by a
space, so the same person arrives spelled several ways. All of the variants
below are taken from real PDFs.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database.people import (
    build_name_index,
    name_key,
    resolve_name,
    tidy_name,
)

CANONICAL = [
    "ADEYANJU,Anthony",
    "ALEXANDER,Rhea",
    "ARMSTRONG-RICHARDSON,Althea",
    "RAGBIR-SHRIPAT,Diana",
]


@pytest.fixture
def index() -> dict[str, str]:
    return build_name_index(CANONICAL)


class TestResolveName:
    @pytest.mark.parametrize(
        "variant,expected",
        [
            ("ADEYANJU ,Anthony", "ADEYANJU,Anthony"),
            ("ADEYANJU, Anthony", "ADEYANJU,Anthony"),
            ("ADEYANJU,Anthony", "ADEYANJU,Anthony"),
            # Wrapped mid-word by a narrow column
            ("ALEXANDE R,Rhea", "ALEXANDER,Rhea"),
            ("ARMSTRO NG- RICHARDS ON,Althea", "ARMSTRONG-RICHARDSON,Althea"),
            ("RAGBIR- SHRIPAT, Diana", "RAGBIR-SHRIPAT,Diana"),
        ],
    )
    def test_variants_collapse_to_canonical(self, variant, expected, index):
        assert resolve_name(variant, index) == expected

    def test_unknown_name_is_kept_tidied(self, index):
        # A visiting lecturer absent from the index must not be dropped.
        assert resolve_name("VISITOR ,Sam", index) == "VISITOR,Sam"

    def test_distinct_people_are_not_merged(self, index):
        assert resolve_name("ALEXANDER,Vivian", index) == "ALEXANDER,Vivian"
        assert resolve_name("ALEXANDER,Rhea", index) == "ALEXANDER,Rhea"


class TestHelpers:
    def test_name_key_ignores_spacing_and_case(self):
        assert name_key("ALEXANDE R,Rhea") == name_key("alexander, rhea")

    def test_tidy_name_removes_space_before_comma(self):
        assert tidy_name("ADEYANJU  ,Anthony") == "ADEYANJU,Anthony"

    def test_build_index_keeps_first_spelling_on_collision(self):
        built = build_name_index(["SMITH,J", "SMITH, J"])
        assert built[name_key("SMITH,J")] == "SMITH,J"
