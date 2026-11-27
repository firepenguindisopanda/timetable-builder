"""
`GET /api/timetable/publication`: which publication is current, and whether
the data behind it has changed (PUBLICATION-ENDPOINT-SPEC.md).

A client that keeps its own copy of the timetable reads `(id, revision)` as
the identity of the data. The id alone was not enough: publication 16 was
reloaded with `--replace` three times on 13 Nov 2026, and every session id and
several slots changed under the same number. The revision is bumped in the
same transaction that writes the sessions, so the two cannot disagree.

The warehouse is faked, as in test_changes_api.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explore_router
import main
from timetable_extractor.database import changes, loader
from timetable_extractor.database.records import SessionRecord

URL = "/api/timetable/publication"
FIXTURE = Path(__file__).parent / "fixtures" / "publication.json"
SCHEMA = (
    Path(__file__).resolve().parents[1] / "timetable_extractor" / "database" / "schema.sql"
)

NOV_12 = datetime(2026, 11, 12, 18, 43, 6, tzinfo=timezone.utc)
NOV_13 = datetime(2026, 11, 13, 7, 58, 0, tzinfo=timezone.utc)
NOV_26 = datetime(2026, 11, 26, 10, 0, 2, tzinfo=timezone.utc)


def identity(**overrides):
    row = {
        "publication_id": 16,
        "revision": 4,
        "published_at": NOV_12,
        "loaded_at": NOV_13,
        "resource_count": 1617,
        "checked_at": NOV_26,
        "update_pending": False,
    }
    row.update(overrides)
    return row


class FakeWarehouse:
    """Answers the two queries the route makes, and counts them."""

    def __init__(self):
        self.identity = identity()
        self.semester = "Semester_1_TT2026_2027"
        self.calls: list[str] = []

    def __call__(self, fn, *args):
        self.calls.append(fn.__name__)
        if fn.__name__ == "publication_identity":
            return self.identity
        if fn.__name__ == "current_semester":
            return self.semester
        raise AssertionError(f"unexpected query {fn.__name__}")


@pytest.fixture
def warehouse(monkeypatch):
    fake = FakeWarehouse()
    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    yield fake
    explore_router.clear_cache()


@pytest.fixture
def client():
    return TestClient(main.app)


# --- the response ---


def _shape(value):
    """A JSON value reduced to its types, so a fixture pins shape, not data."""
    if isinstance(value, dict):
        return {key: _shape(item) for key, item in value.items()}
    return type(value).__name__


def test_shape_matches_the_fixture(client, warehouse):
    response = client.get(URL)
    assert response.status_code == 200
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _shape(response.json()) == _shape(expected)


def test_values(client, warehouse):
    body = client.get(URL).json()
    assert body["apiVersion"] == 1
    assert body["publication"] == {
        "id": 16,
        "revision": 4,
        "publishedAt": NOV_12.isoformat(),
        "loadedAt": NOV_13.isoformat(),
        "resourceCount": 1617,
    }
    assert body["semester"] == {
        "label": "Semester_1_TT2026_2027",
        "academicYear": "2026/2027",
        "number": 1,
        "weekOne": "2026-08-31",
        "totalWeeks": 12,
    }
    assert body["sync"] == {"checkedAt": NOV_26.isoformat(), "updatePending": False}


def test_unknown_semester_has_no_week_one(client, warehouse):
    """A semester missing from weeks.TERMS is not guessed at."""
    warehouse.semester = "Semester_1_TT2027_2028"
    semester = client.get(URL).json()["semester"]
    assert semester["academicYear"] == "2027/2028"
    assert semester["number"] == 1
    assert semester["weekOne"] is None


def test_unparseable_semester_label(client, warehouse):
    warehouse.semester = None
    semester = client.get(URL).json()["semester"]
    assert semester == {
        "label": None,
        "academicYear": None,
        "number": None,
        "weekOne": None,
        "totalWeeks": 12,
    }


def test_never_checked(client, warehouse):
    warehouse.identity = identity(checked_at=None, published_at=None)
    body = client.get(URL).json()
    assert body["sync"]["checkedAt"] is None
    assert body["publication"]["publishedAt"] is None


def test_not_cached(client, warehouse):
    """A reload shows on the very next request, with no cache to clear."""
    first = client.get(URL)
    assert first.headers["cache-control"] == "no-store"
    assert "etag" not in first.headers
    warehouse.identity = identity(revision=5)
    assert client.get(URL).json()["publication"]["revision"] == 5
    assert warehouse.calls.count("publication_identity") == 2


def test_no_loaded_publication(client, warehouse):
    warehouse.identity = None
    response = client.get(URL)
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "detail": "No timetable has been loaded yet.",
    }


def test_warehouse_unreachable_says_nothing_internal(client, monkeypatch):
    def broken(fn, *args):
        raise explore_router.ExplorerUnavailable("connection to 10.0.0.5 refused")

    monkeypatch.setattr(explore_router, "query", broken)
    explore_router.clear_cache()
    response = client.get(URL)
    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "detail": "The timetable database is unavailable.",
    }
    assert "10.0.0.5" not in response.text


def test_get_only(client, warehouse):
    assert client.post(URL).status_code == 405


def test_documented_with_a_response_model(client):
    """The first /api/timetable route whose shape shows in /docs."""
    spec = client.get("/openapi.json").json()
    ok = spec["paths"][URL]["get"]["responses"]["200"]["content"]["application/json"]
    assert "$ref" in ok["schema"]


# --- the revision ---


def test_schema_adds_and_backfills_the_revision():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "ADD COLUMN IF NOT EXISTS load_revision INTEGER NOT NULL DEFAULT 0" in sql
    assert "ADD COLUMN IF NOT EXISTS loaded_at" in sql
    backfill = sql[sql.index("SET load_revision = 1") :]
    backfill = backfill[: backfill.index(";")]
    assert "WHERE p.load_revision = 0" in backfill
    assert "EXISTS (SELECT 1 FROM sessions" in backfill


class RecordingConnection:
    """Enough of a psycopg connection for write_sessions, recording the order."""

    def __init__(self, revision_after: int):
        self.log: list[str] = []
        self.revision_after = revision_after
        self._last = ""

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._last = " ".join(str(sql).split())
        self.log.append(self._last)

    def executemany(self, sql, rows):
        self.log.append(" ".join(str(sql).split()))

    def fetchall(self):
        if self._last.startswith("SELECT code, id FROM courses"):
            return [("COMP 1601", 1)]
        return []

    def fetchone(self):
        if "RETURNING load_revision" in self._last:
            return (self.revision_after,)
        return (0,)

    def commit(self):
        self.log.append("COMMIT")


def _record():
    return SessionRecord(course_code="COMP 1601", day="Monday", start_min=540, end_min=600)


def test_write_sessions_bumps_the_revision_inside_its_commit():
    """
    Readers must see old sessions with the old revision, or new with new.

    So the bump runs on the same connection before the one commit that
    publishes the sessions, never after it and never in a commit of its own.
    """
    conn = RecordingConnection(revision_after=2)
    loader.write_sessions(conn, 16, [_record()], {})

    bumps = [i for i, s in enumerate(conn.log) if s.startswith("UPDATE publications")]
    commits = [i for i, s in enumerate(conn.log) if s == "COMMIT"]
    inserts = [i for i, s in enumerate(conn.log) if s.startswith("INSERT INTO sessions")]
    assert len(bumps) == 1 and len(commits) == 1
    assert inserts[0] < bumps[0] < commits[0]
    bump = conn.log[bumps[0]]
    assert "load_revision = load_revision + 1" in bump
    assert "loaded_at = now()" in bump


def test_no_records_writes_no_revision():
    """Nothing written means nothing to call a new revision."""
    conn = RecordingConnection(revision_after=1)
    loader.write_sessions(conn, 16, [], {})
    assert not any(s.startswith("UPDATE publications") for s in conn.log)


# --- /changes only names loaded publications (H1) ---


class PairCursor:
    """Records the publication-pair query and returns no publications."""

    def __init__(self, seen):
        self.seen = seen

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.seen.append(" ".join(str(sql).split()))

    def fetchall(self):
        return []

    def fetchone(self):
        return None


class PairConnection:
    def __init__(self):
        self.seen: list[str] = []

    def cursor(self):
        return PairCursor(self.seen)


@pytest.mark.parametrize(
    "call",
    [
        lambda conn: changes.changes_for_page(conn),
        lambda conn: changes.changes_for_courses(conn, ["COMP 1601"]),
    ],
    ids=["page", "api"],
)
def test_changes_ignores_unloaded_publications(call):
    """
    A publication row is committed before its sessions. Until they land, it
    must not become `toPublicationId`, or a client diffs against nothing.
    """
    conn = PairConnection()
    assert call(conn) is None
    pair = conn.seen[0]
    # Within the default term, through the view that skips unloaded
    # publications (test_empty_publication.py pins its `load_revision > 0`).
    assert "FROM latest_publication" in pair
