"""
Which publication is current, per term.

`latest_publication` used to be the newest publication of all. The semester 2
inspection copy of 26 Nov 2026 is newer than every semester 1 publication, so
loading it would have made it current for every student, told every saved
timetable its classes had changed, and listed semester 1 against semester 2
on `/explore/changes` as thousands of changes. The suite has no database, so
these read the view definitions in schema.sql; the behaviour was checked
against the warehouse inside a rolled-back transaction before the migration
ran. SEMESTERS-SPEC.md 6.1 and 6.2.
"""

from __future__ import annotations

import re
from pathlib import Path

from timetable_extractor.database import weeks

SCHEMA = (
    Path(__file__).parent.parent / "timetable_extractor" / "database" / "schema.sql"
).read_text(encoding="utf-8")


def view_body(name: str) -> str:
    start = SCHEMA.index(f"CREATE OR REPLACE VIEW {name} AS")
    return " ".join(SCHEMA[start : SCHEMA.index(";", start)].split())


def test_one_current_publication_per_term():
    body = view_body("term_publication")
    assert "DISTINCT ON (academic_year, semester)" in body


def test_an_unloaded_publication_never_counts():
    """Its row is committed before its sessions; until then it is empty."""
    assert "WHERE load_revision > 0" in view_body("term_publication")


def test_final_outranks_inspection_whatever_the_dates():
    """The final timetable replaces the draft even if UWI touches the draft later."""
    order = view_body("term_publication").split("ORDER BY", 1)[1]
    stage = order.index("(stage = 'final') DESC")
    newest = order.index("COALESCE(published_at, discovered_at) DESC")
    assert order.index("semester") < stage < newest


def test_students_stay_on_semester_1_until_the_switch():
    """Pinned until phase 3, so loading the inspection copy changes nothing they see."""
    body = view_body("latest_publication")
    assert "FROM term_publication" in body
    assert "academic_year = '2026/2027' AND semester = 1" in body


def test_current_sessions_is_still_the_default_terms():
    assert "FROM latest_publication" in view_body("current_sessions")


def test_term_sessions_says_which_term_each_row_is():
    body = view_body("term_sessions")
    assert "JOIN term_publication tp ON tp.id = s.publication_id" in body
    for column in ("AS publication_id", "tp.academic_year", "AS term_semester", "tp.stage"):
        assert column in body
    # CELCAT's label keeps its name, as in current_sessions.
    assert "s.semester," in body


def test_the_backfill_reads_labels_as_semester_key_does():
    """Two copies of one pattern; a label one reads and the other misses would
    leave a publication with no term, and so never current."""
    pattern = re.search(r"regexp_match\(\s*mode\(\).*?'(.+?)',\s*'i'", SCHEMA, re.S)
    assert pattern, "the backfill no longer reads the label with regexp_match"
    assert pattern.group(1) == weeks._SEMESTER.pattern
    assert weeks._SEMESTER.flags & re.I


def test_the_backfill_only_touches_rows_still_unset():
    """schema.sql runs on every load and sync; a second run must change nothing."""
    assert "WHERE source IS NULL" in SCHEMA
    assert "WHERE stage  IS NULL" in SCHEMA
    assert "p.academic_year IS NULL" in SCHEMA


def test_celcat_ids_are_unique_per_source():
    """The inspection copy's module 1249 is not semester 1's."""
    assert "UNIQUE (source, kind, celcat_id)" in SCHEMA
    assert "DROP CONSTRAINT IF EXISTS resources_kind_celcat_id_key" in SCHEMA
    assert "UNIQUE (kind, celcat_id)" not in SCHEMA


def test_every_check_says_which_source_it_asked():
    assert (
        "ALTER TABLE sync_runs ADD COLUMN IF NOT EXISTS source TEXT NOT NULL DEFAULT 'root'"
        in SCHEMA
    )
