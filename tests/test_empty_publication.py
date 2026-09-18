"""
A publication must never be served before its sessions exist.

`latest_publication` is the newest publication and `current_sessions` reads
only that one, so a publication becomes the live timetable the instant its row
is committed - sessions or no sessions. The loader used to create that row
first and then spend twenty minutes extracting, which left the site serving an
empty timetable for the whole extraction.

On 17 September 2026 that window stayed open: the database connection dropped
mid-extraction, the load never reached `write_sessions`, and
`/explore/ops.json` reported `"sessions":0,"courses":0` until the publication
was loaded again. The `--replace` path had already been fixed for the same
hazard (`loader.load_all`); the new-publication path had not.

Two things now hold the guarantee, and both are pinned here. The loader
extracts before it writes anything, so a crash during extraction leaves no row
behind - tested by the ordering tests, which fail against the old ordering.
The `latest_publication` view then refuses to name a publication that has no
sessions, which closes the remaining gap between the row committing and the
insert committing, wherever a load stops.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from timetable_extractor.database import loader

FINDER_XML = """<?xml version="1.0" encoding="utf-8"?>
<finder>
  <resource id="1" type="module" link="m1.pdf"><name>COMP 1601, Intro</name></resource>
  <resource id="2" type="module" link="m2.pdf"><name>COMP 2601, Systems</name></resource>
</finder>
"""


class FakeCursor:
    """Records every statement so the test can see what touched the database."""

    def __init__(self, log):
        self.log = log
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self.log.append(("sql", " ".join(str(sql).split())[:30]))

    def executemany(self, sql, rows):
        self.log.append(("sql", "executemany"))

    def fetchone(self):
        return (None,)

    def fetchall(self):
        return []


class FakeConn:
    def __init__(self, log):
        self.log = log

    def cursor(self):
        return FakeCursor(self.log)

    def commit(self):
        self.log.append(("commit", ""))


@pytest.fixture
def corpus(tmp_path):
    """A finder.xml and two PDFs, enough for `load_all` to walk."""
    finder = tmp_path / "finder.xml"
    finder.write_text(FINDER_XML, encoding="utf-8")
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    for name in ("m1.pdf", "m2.pdf"):
        (pdfs / name).write_bytes(b"%PDF-1.4")
    return finder, pdfs


def run_load(monkeypatch, corpus, log, *, extract=None):
    """Run `load_all` against fakes, appending each step to `log` in order."""
    finder, pdfs = corpus

    def fake_extract(path):
        log.append(("extract", Path(path).name))
        return {"course_title": "COMP 1601 (Wks W3-W12)", "entries": []}

    monkeypatch.setattr(loader, "extract_timetable", extract or fake_extract)
    monkeypatch.setattr(loader, "records_from_extraction", lambda result, source: [])
    monkeypatch.setattr(loader, "merge_records", lambda raw: [])

    def fake_upsert(conn, xml_bytes, **kwargs):
        log.append(("upsert_publication", ""))
        return 9, False

    def fake_index(conn, xml_bytes, publication_id):
        log.append(("load_index", ""))
        return {"resources": 2, "courses": 2, "staff": 0, "rooms": 0}

    def fake_register(conn, paths):
        log.append(("register_pdfs", ""))
        return {}

    def fake_write(conn, publication_id, merged, pdf_ids):
        log.append(("write_sessions", ""))
        return 0, 0, 0

    monkeypatch.setattr(loader, "upsert_publication", fake_upsert)
    monkeypatch.setattr(loader, "load_index", fake_index)
    monkeypatch.setattr(loader, "register_pdfs", fake_register)
    monkeypatch.setattr(loader, "write_sessions", fake_write)
    monkeypatch.setattr(loader, "previous_publication", lambda conn, pid: None)
    monkeypatch.setattr(loader, "build_name_index", lambda names: {})
    monkeypatch.setattr(loader, "build_code_index", lambda codes: {})

    return loader.load_all(
        FakeConn(log),
        finder_xml=finder,
        pdf_dirs=[pdfs],
        progress=False,
    )


def test_every_pdf_is_read_before_the_publication_row_exists(monkeypatch, corpus):
    """The row that makes a publication current comes after the last PDF."""
    log = []
    run_load(monkeypatch, corpus, log)

    steps = [step for step, _ in log]
    assert "upsert_publication" in steps, "the publication was never created"

    last_extract = max(i for i, (step, _) in enumerate(log) if step == "extract")
    first_write = steps.index("upsert_publication")
    assert last_extract < first_write, (
        "the publication row was created while PDFs were still being read, so "
        "current_sessions would serve an empty timetable for the whole extraction"
    )


def test_nothing_touches_the_database_during_extraction(monkeypatch, corpus):
    """Not just the publication row - no write and no query at all."""
    log = []
    run_load(monkeypatch, corpus, log)

    last_extract = max(i for i, (step, _) in enumerate(log) if step == "extract")
    before = [step for step, _ in log[:last_extract]]
    assert before == ["extract"] * len(before), (
        f"the database was used before extraction finished: {before}"
    )


def test_a_dead_connection_fails_before_any_session_is_written(monkeypatch, corpus):
    """
    The 17 Sep 2026 failure, in the order that now applies.

    The connection is opened before the load and sits idle for the whole
    extraction, so the server can close it while no query is in flight. The
    first statement afterwards is the one that raises. What matters is that
    the load stops there rather than carrying on, because a publication whose
    sessions never arrive is the empty timetable this module exists to avoid.
    """
    log = []

    def dead_connection(conn, xml_bytes, **kwargs):
        log.append(("upsert_publication", ""))
        raise RuntimeError("SSL connection has been closed unexpectedly")

    finder, pdfs = corpus
    monkeypatch.setattr(loader, "extract_timetable", lambda path: (
        log.append(("extract", Path(path).name)) or
        {"course_title": "COMP 1601 (Wks W3-W12)", "entries": []}
    ))
    monkeypatch.setattr(loader, "records_from_extraction", lambda result, source: [])
    monkeypatch.setattr(loader, "merge_records", lambda raw: [])
    monkeypatch.setattr(loader, "upsert_publication", dead_connection)
    monkeypatch.setattr(loader, "write_sessions", lambda *a: log.append(("write_sessions", "")))

    with pytest.raises(RuntimeError):
        loader.load_all(
            FakeConn(log),
            finder_xml=finder,
            pdf_dirs=[pdfs],
            progress=False,
        )

    steps = [step for step, _ in log]
    assert steps.count("extract") == 2, "the PDFs should already have been read"
    assert "write_sessions" not in steps, "the load continued past a dead connection"


# --- the view half of the guarantee ---

SCHEMA = Path(__file__).resolve().parents[1] / "timetable_extractor" / "database" / "schema.sql"


def view_body(name: str) -> str:
    """The text of one CREATE OR REPLACE VIEW, without its trailing views."""
    sql = SCHEMA.read_text(encoding="utf-8")
    start = sql.index(f"CREATE OR REPLACE VIEW {name} AS")
    return sql[start : sql.index(";", start)]


def test_latest_publication_ignores_a_publication_with_no_sessions():
    """
    Without this the row alone makes a publication live.

    The loader commits the publication before the sessions, so between those
    two commits the newest publication is empty. Every student-facing query
    scopes to this view, and `/explore` caches for five minutes, so a single
    request landing in that gap serves an empty timetable well past it.
    """
    body = view_body("latest_publication")
    assert "sessions" in body, (
        "latest_publication no longer checks for sessions, so a half-loaded "
        "publication would become the live timetable"
    )
    assert "EXISTS" in body.upper()


def test_current_sessions_still_reads_latest_publication():
    """The guard only reaches students through this view."""
    assert "latest_publication" in view_body("current_sessions")
