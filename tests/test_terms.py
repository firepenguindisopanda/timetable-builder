"""
Every read names its term (SEMESTERS-SPEC.md section 7.2, phase 2).

The warehouse holds semester 1 and the semester 2 inspection copy side by
side, so "the current publication" no longer exists on its own. These pin the
term's spelling in URLs, that the queries restrict themselves to the term
they were given, and that nothing still reads the single-term views.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from timetable_extractor.database import changes, explore_queries, free_rooms, queries
from timetable_extractor.database import terms as tm
from timetable_extractor.database.weeks import TERMS

ROOT = Path(__file__).resolve().parents[1]
S1 = ("2026/2027", 1)
S2 = ("2026/2027", 2)


# The term in a URL


@pytest.mark.parametrize(
    ("term", "slug"),
    [(S1, "2026-27-s1"), (S2, "2026-27-s2"), (("2099/2100", 3), "2099-00-s3")],
)
def test_a_term_round_trips_through_its_slug(term, slug):
    assert tm.slug(term) == slug
    assert tm.parse_slug(slug) == term


@pytest.mark.parametrize(
    "value", ["", None, "s2", "2026-27", "2026-28-s1", "2026/27-s1", "2026-27-s", "x2026-27-s1"]
)
def test_anything_else_is_not_a_term(value):
    assert tm.parse_slug(value) is None


def test_a_slug_is_read_whatever_its_case():
    assert tm.parse_slug(" 2026-27-S2 ") == S2


def test_labels_name_the_inspection_copy():
    assert tm.label(S1, "final") == "Semester 1 2026/27"
    assert tm.label(S2, "inspection") == "Semester 2 2026/27 (inspection copy)"


def test_weeks_come_from_the_terms_dates():
    assert tm.total_weeks(S1) == 12
    assert tm.total_weeks(S2) == 13
    assert tm.total_weeks(("2030/2031", 1)) == tm.FALLBACK_WEEKS == 12


def test_the_default_term_is_the_one_latest_publication_is_pinned_to():
    """The two must move together in phase 3, or /changes and pages disagree."""
    sql = (ROOT / "timetable_extractor" / "database" / "schema.sql").read_text(encoding="utf-8")
    view = sql[sql.index("CREATE OR REPLACE VIEW latest_publication"):]
    view = view[: view.index(";")]
    year, semester = tm.DEFAULT_TERM
    assert f"academic_year = '{year}' AND semester = {semester}" in view
    assert tm.DEFAULT_TERM in TERMS


def test_the_filter_names_the_view_columns():
    assert tm.in_term() == "academic_year = %(year)s AND term_semester = %(semester)s"
    assert tm.in_term("cs").startswith("cs.academic_year = ")
    assert "cs.term_semester" in tm.in_term("cs")
    assert tm.params(S2, code="X") == {"year": "2026/2027", "semester": 2, "code": "X"}


# Nothing reads the single-term views


@pytest.mark.parametrize("module", [explore_queries, free_rooms, queries, changes])
def test_no_query_reads_the_default_terms_views(module):
    """
    `current_sessions` and `latest_publication` are the default term's. A
    query reading them answers semester 1 whatever term the page asked for,
    and nothing fails: the reason the term is an argument at all.
    """
    source = Path(module.__file__).read_text(encoding="utf-8")
    assert not re.search(r"\b(current_sessions|latest_publication)\b", source)


# The queries restrict themselves to their term


class Cursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = ()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.statements.append((" ".join(str(sql).split()), params))

    def fetchall(self):
        return self.conn.rows.pop(0) if self.conn.rows else []

    def fetchone(self):
        return None


class Connection:
    def __init__(self, *rows):
        self.statements: list[tuple[str, object]] = []
        self.rows = list(rows)

    def cursor(self):
        return Cursor(self)


def test_course_codes_reads_the_term_asked_for():
    conn = Connection([("ACCT 1002",)])
    assert explore_queries.course_codes(conn, S2) == ["ACCT 1002"]
    sql, params = conn.statements[0]
    assert "FROM term_sessions" in sql
    assert params == {"year": "2026/2027", "semester": 2}


def test_week_13_survives_the_bitmask_in_semester_2():
    assert explore_queries.weeks_to_mask([12, 13], tm.total_weeks(S2)) == 0b1100000000000
    assert explore_queries.weeks_to_mask([12, 13]) == 0b100000000000


def test_the_heat_grid_takes_its_median_over_the_terms_weeks():
    """
    A class in six weeks is half of semester 1, which the median rounds up
    to typical, and under half of semester 2's 13, which it does not.
    """
    row = {"id": 1, "day": "Monday", "start_min": 540, "end_min": 600,
           "raw_text": None, "room": "FST C1", "weeks": list(range(1, 7))}
    assert explore_queries.heat_matrix([row], 12) == {("Monday", 9): 1}
    assert explore_queries.heat_matrix([row], 13) == {}


def test_free_rooms_reads_the_terms_own_registry():
    """
    Semester 2's registry is the rooms its own index listed. Through
    `rooms.resource_id` it reached only the 14 rooms new in semester 2,
    because a room shared with semester 1 keeps semester 1's resource.
    """
    conn = Connection(
        [("FHE CLL  Room  9, Centre for Language Learning",), ("FST C1, Lecture Room",)],
        [("FHE CLL Room 9",), ("FST C1",), ("Venue to be advised",), ("JFK AUD",)],
    )
    assert free_rooms.study_rooms(conn, S2) == ["FHE CLL Room 9", "FST C1"]
    registry_sql, registry_params = conn.statements[0]
    assert "FROM resources" in registry_sql and "kind = 'room'" in registry_sql
    assert "FROM term_publication" in registry_sql
    assert registry_params == {"year": "2026/2027", "semester": 2}
    assert "FROM term_sessions" in conn.statements[1][0]


def test_a_since_from_another_term_is_not_diffed_across_terms():
    conn = Connection()
    assert changes._publication_in_term(conn, 16, S2) is False
    sql, params = conn.statements[0]
    assert "academic_year = %(year)s AND semester = %(semester)s" in sql
    assert params == {"year": "2026/2027", "semester": 2, "id": 16}
