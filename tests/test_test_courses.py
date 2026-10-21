"""
Timetable Unit test entries never reach the site.

The 19 Oct 2026 publication carried "TEST 1001, TEST 1001": four sessions in
weeks 8-12, no room, no staff, from its own PDF. It went into the course list
students search. The loader now leaves test entries out at every step: no
course row from the registry, no sessions from any PDF, and no row left over
from a load made before the rule existed.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database import loader
from timetable_extractor.database.courses import is_test_course
from timetable_extractor.database.records import SessionRecord
from timetable_extractor.observability import Diagnostics


@pytest.mark.parametrize("code", ["TEST 1001", "test1001", " TEST  2000 ", "TEST"])
def test_test_entries_are_recognised(code):
    assert is_test_course(code)


@pytest.mark.parametrize(
    "code", ["COMP 2601", "TESL 1001", "STAT 2001", "ATEST 1001", "", None,
             "FOUN 1001 (FULL & PART-TIME)"],
)
def test_real_courses_are_not(code):
    assert not is_test_course(code)


def record(code):
    return SessionRecord(course_code=code, day="Monday", start_min=540, end_min=720)


def test_test_records_are_dropped_and_named():
    diagnostics = Diagnostics(source="finder.xml")
    kept = loader.drop_test_records(
        [record("COMP 2601"), record("TEST 1001"), record("TEST 1001")], diagnostics
    )
    assert [r.course_code for r in kept] == ["COMP 2601"]
    assert diagnostics.findings["test_course_skipped"] == 1
    assert diagnostics.samples["test_course_skipped"] == [{"course": "TEST 1001"}]


def test_nothing_to_drop_names_nothing():
    diagnostics = Diagnostics(source="finder.xml")
    assert len(loader.drop_test_records([record("COMP 2601")], diagnostics)) == 1
    assert "test_course_skipped" not in diagnostics.findings


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.conn.log.append((" ".join(str(sql).split())[:40], params))

    def fetchone(self):
        return (1,)

    def fetchall(self):
        return self.conn.orphans


class Conn:
    def __init__(self, orphans=()):
        self.orphans = list(orphans)
        self.log = []
        self.committed = False

    def cursor(self):
        return Cursor(self)

    def commit(self):
        self.committed = True


def test_the_registry_entry_makes_no_course_row(monkeypatch):
    finder = b"""<?xml version="1.0" encoding="utf-8"?>
<finder>
  <resource id="1" type="module" link="m1.pdf"><name>COMP 2601, Computer Architecture</name></resource>
  <resource id="2" type="module" link="m113531.pdf"><name>TEST 1001, TEST 1001</name></resource>
</finder>
"""
    monkeypatch.setattr(loader, "merge_room_spellings", lambda conn: 0)
    conn = Conn()
    counts = loader.load_index(conn, finder, publication_id=12)

    course_inserts = [params for sql, params in conn.log if sql.startswith("INSERT INTO courses")]
    assert [p[0] for p in course_inserts] == ["COMP 2601"]
    assert counts == {"resources": 2, "courses": 1, "staff": 0, "rooms": 0}


def test_a_leftover_test_course_row_is_removed():
    """Loaded before the rule existed: its sessions go on reload, then its row."""
    conn = Conn(orphans=[(7, "TEST 1001"), (8, "COMP 9999")])
    assert loader.drop_orphaned_test_courses(conn) == 1
    assert ("DELETE FROM courses WHERE id = ANY(%s)", ([7],)) in conn.log
    assert conn.committed


def test_no_leftovers_deletes_nothing():
    conn = Conn(orphans=[(8, "COMP 9999")])
    assert loader.drop_orphaned_test_courses(conn) == 0
    assert not any(sql.startswith("DELETE") for sql, _ in conn.log)
