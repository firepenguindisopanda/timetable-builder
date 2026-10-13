"""
One room, one row, however finder.xml spaces its code.

The registry writes "FHE CLL  Room  9" and the PDFs "FHE CLL Room 9". The
loader stored both as given, so the `rooms` table held 22 rooms twice: the
registry's row owning the resource and the bookings' row owning every class.
The free rooms page found no bookings for those rooms until it compared codes
with their whitespace collapsed. These pin the loader-side fix: both spellings
normalise to one code, and the duplicates already stored fold together.
"""

from __future__ import annotations

import psycopg
import pytest

from timetable_extractor.database import loader
from timetable_extractor.database.loader import plan_room_merges
from timetable_extractor.database.records import normalise_room_code, split_rooms


class TestNormaliseRoomCode:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("FHE CLL  Room  9", "FHE CLL Room 9"),
            ("  TLC LT A1 ", "TLC LT A1"),
            ("FSS 101 W", "FSS 101 W"),
            (None, ""),
        ],
    )
    def test_collapses_whitespace_and_keeps_case(self, raw, expected):
        assert normalise_room_code(raw) == expected

    def test_bookings_split_to_the_same_spelling(self):
        assert split_rooms("FHE CLL  Room  9;  FST 415") == ["FHE CLL Room 9", "FST 415"]


class TestPlanRoomMerges:
    def test_keeps_the_row_the_bookings_point_at(self):
        # The registry row is older, but the single-spaced one holds the classes.
        assert plan_room_merges([(59, "FHE CLL  Room  9"), (536, "FHE CLL Room 9")]) == [
            (536, [59], "FHE CLL Room 9")
        ]

    def test_a_lone_padded_code_is_renamed(self):
        assert plan_room_merges([(7, "FHE  Archive")]) == [(7, [], "FHE Archive")]

    def test_two_padded_spellings_keep_the_oldest(self):
        assert plan_room_merges([(9, "A   B"), (4, "A  B")]) == [(4, [9], "A B")]

    def test_clean_rooms_need_nothing(self):
        assert plan_room_merges([(1, "TLC LT A1"), (2, "FSS 101 W"), (3, "FSS 101 E")]) == []


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        statement = " ".join(str(sql).split())
        self.conn.log.append((statement.split(" SET")[0].split(" WHERE")[0], params))
        if self.conn.collide and statement.startswith("UPDATE sessions"):
            raise psycopg.errors.UniqueViolation("sessions_natural_key")

    def fetchall(self):
        return self.conn.rooms


class FakeTransaction:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *exc):
        self.conn.log.append(("rollback" if exc_type else "release", None))
        return False


class FakeConn:
    def __init__(self, rooms, collide=False):
        self.rooms = rooms
        self.collide = collide
        self.log = []

    def cursor(self):
        return FakeCursor(self)

    def transaction(self):
        return FakeTransaction(self)


class TestMergeRoomSpellings:
    def test_moves_classes_then_drops_the_duplicate(self):
        conn = FakeConn([(59, "FHE CLL  Room  9"), (536, "FHE CLL Room 9")])

        assert loader.merge_room_spellings(conn) == 1
        assert conn.log == [
            ("SELECT id, code FROM rooms", None),
            ("UPDATE sessions", (536, 59)),
            ("UPDATE rooms keep", (536, 59)),
            ("DELETE FROM rooms", (59,)),
            ("UPDATE rooms", ("FHE CLL Room 9", 536)),
            ("release", None),
        ]

    def test_a_collision_leaves_both_rows_and_carries_on(self):
        conn = FakeConn([(59, "FHE CLL  Room  9"), (536, "FHE CLL Room 9")], collide=True)

        assert loader.merge_room_spellings(conn) == 0
        assert ("DELETE FROM rooms", (59,)) not in conn.log
        assert conn.log[-1] == ("rollback", None)

    def test_nothing_to_merge_touches_nothing(self):
        conn = FakeConn([(1, "TLC LT A1")])

        assert loader.merge_room_spellings(conn) == 0
        assert conn.log == [("SELECT id, code FROM rooms", None)]


def test_the_registry_spelling_is_stored_collapsed(monkeypatch):
    finder = b"""<?xml version="1.0" encoding="utf-8"?>
<finder>
  <resource id="9" type="room" link="r9.pdf"><name>FHE CLL  Room  9, Centre for Language Learning Room 9</name></resource>
</finder>
"""
    inserted = []

    class Cursor(FakeCursor):
        def execute(self, sql, params=None):
            if "INSERT INTO rooms" in str(sql):
                inserted.append(params[0])

        def fetchone(self):
            return (1,)

    class Conn(FakeConn):
        def cursor(self):
            return Cursor(self)

        def commit(self):
            pass

    monkeypatch.setattr(loader, "merge_room_spellings", lambda conn: 0)
    loader.load_index(Conn([]), finder, publication_id=1)

    assert inserted == ["FHE CLL Room 9"]
