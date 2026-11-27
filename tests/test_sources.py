"""
More than one CELCAT publication at a time.

On 26 Nov 2026 UWI published the semester 2 inspection copy at a second
address beside the live semester 1 timetable. 595 of its 1,718 PDF names are
also semester 1 names with different contents, and `pdf_files.pdf_link` is
unique on the name, so pulled into the same folder and table it would have
overwritten semester 1's records file by file. Pinned here: each source keeps
its own address, folder and registry; root's are the paths everything used
before; files are recorded under their path from the root address; `check`
asks each source about its own publications; and a source that has gone is
reported as gone rather than as a failure. SEMESTERS-SPEC.md section 5.
"""

from __future__ import annotations

import io
import sys
import urllib.error
from pathlib import Path

import pytest

from timetable_extractor import sync
from timetable_extractor.constants import BASE_URL, SOURCES, Source

INSPECTION = SOURCES["s2-inspection"]


# The configuration


def test_root_keeps_the_paths_it_always_had():
    """The existing corpus, registry, withdrawn folder and runbook do not move."""
    root = SOURCES["root"]
    assert root.base_url == BASE_URL
    assert root.pdf_dir == "downloaded_pdfs"
    assert root.registry == "finder.xml"
    assert root.withdrawn_dir == "withdrawn_pdfs"
    assert root.link_prefix == ""
    assert sync.DEFAULT_REGISTRY == Path("finder.xml")


def test_the_inspection_copy_has_a_folder_and_registry_of_its_own():
    assert INSPECTION.finder_xml == (
        "https://mysta.uwi.edu/timetable/Inspection%20Copy/Sem2INSPECTIONCOPY/finder.xml"
    )
    paths = {INSPECTION.pdf_dir, INSPECTION.registry, INSPECTION.withdrawn_dir}
    assert all(p.startswith("sources/s2-inspection/") for p in paths)


def test_a_sources_files_are_named_by_their_path_from_the_root():
    """So its m1249.pdf is a row of its own, not semester 1's."""
    assert INSPECTION.link_prefix == "Inspection Copy/Sem2INSPECTIONCOPY/"


def test_a_source_outside_the_root_address_is_refused():
    elsewhere = Source("https://example.org/timetable/", "x", "x.xml", "y")
    with pytest.raises(ValueError):
        elsewhere.link_prefix


def test_finder_html_is_kept_beside_its_registry():
    assert sync.finder_page(Path("sources/s2-inspection/finder.xml")) == Path(
        "sources/s2-inspection/finder.html"
    )


# A database stand-in that keeps what was asked of it


class FakeCursor:
    def __init__(self, conn: FakeConnection) -> None:
        self.conn = conn

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.conn.statements.append((" ".join(sql.split()), params))

    def fetchone(self):
        return self.conn.row

    def fetchall(self) -> list[tuple]:
        return []


class FakeConnection:
    def __init__(self, row=None) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self.row = row

    def cursor(self) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        return None

    def params_of(self, start: str) -> list[tuple]:
        return [params for sql, params in self.statements if sql.startswith(start)]


# check


def test_check_asks_a_source_about_its_own_publications(monkeypatch):
    """Root's validators sent to the inspection address would read as a change."""
    asked = []

    def fake_fetch(url, *, etag=None, last_modified=None, method="GET"):
        asked.append(url)
        return sync.HeadResult(304, etag, last_modified)

    monkeypatch.setattr(sync, "fetch", fake_fetch)
    conn = FakeConnection(row=(7, '"etag"', None, None))

    assert sync.check(conn, "s2-inspection", verbose=False) == sync.UNCHANGED

    assert asked == [INSPECTION.finder_xml]
    lookup = next(sql for sql, _ in conn.statements if "FROM publications" in sql)
    assert "WHERE source = %s" in lookup
    assert conn.params_of("SELECT id, http_etag")[0] == ("s2-inspection",)


def test_each_check_is_recorded_under_its_source(monkeypatch):
    """The site's "update pending" flag reads root's checks only."""
    monkeypatch.setattr(
        sync, "fetch", lambda url, **kw: sync.HeadResult(304, None, None)
    )
    conn = FakeConnection(row=(7, '"etag"', None, None))

    sync.check(conn, "s2-inspection", verbose=False)

    (insert,) = conn.params_of("INSERT INTO sync_runs")
    assert insert == (False, "check only", "s2-inspection")


def test_a_source_that_answers_404_is_gone_not_failed(monkeypatch):
    """UWI taking the inspection copy down is its expected end, not an outage."""

    def gone(url, **kw):
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, io.BytesIO())

    monkeypatch.setattr(sync, "fetch", gone)
    conn = FakeConnection()

    assert sync.check(conn, "s2-inspection", verbose=False) == sync.GONE
    (insert,) = conn.params_of("INSERT INTO sync_runs")
    assert insert[0] is False and insert[2] == "s2-inspection"


def test_any_other_http_error_still_fails(monkeypatch):
    def broken(url, **kw):
        raise urllib.error.HTTPError(url, 500, "Server Error", {}, io.BytesIO())

    monkeypatch.setattr(sync, "fetch", broken)
    with pytest.raises(urllib.error.HTTPError):
        sync.check(FakeConnection(), "root", verbose=False)


@pytest.mark.parametrize(
    ("argv", "found", "code"),
    [
        (["check"], {"root": sync.UNCHANGED, "s2-inspection": sync.CHANGED}, 10),
        (["check"], {"root": sync.UNCHANGED, "s2-inspection": sync.GONE}, 0),
        (["check", "--source", "root"], {"root": sync.UNCHANGED}, 0),
    ],
)
def test_check_with_no_source_checks_every_one(monkeypatch, argv, found, code):
    """Exit 10 if any source changed, so the schedule needs no list of its own."""
    checked = []

    class Opened:
        def __enter__(self):
            return FakeConnection()

        def __exit__(self, *exc):
            return False

    def fake_check(conn, source, *, verbose=True):
        checked.append(source)
        return found[source]

    monkeypatch.setattr(sync, "connect", lambda: Opened())
    monkeypatch.setattr(sync, "apply_schema", lambda conn: None)
    monkeypatch.setattr(sync, "check", fake_check)
    monkeypatch.setattr(sys, "argv", ["sync", *argv, "--quiet"])

    assert sync.main() == code
    assert checked == list(found)


# pull


def test_pull_records_a_sources_files_under_their_path_from_the_root(
    monkeypatch, tmp_path
):
    """The inspection copy's m1249.pdf must not overwrite semester 1's row."""
    fetched = []
    index = (
        b'<?xml version="1.0" encoding="UTF-8"?><finder>'
        b"<footer>Published 26-Nov-26 2:15:05 PM - UWI</footer>"
        b'<resource link="m1249.pdf" /></finder>'
    )
    page = b"<title>Timetable Finder - Inspection_Sem_2_2026_2027</title>"

    def fake_fetch(url, *, etag=None, last_modified=None, method="GET"):
        fetched.append(url)
        if url == INSPECTION.finder_xml:
            return sync.HeadResult(200, None, None, index)
        if url == INSPECTION.finder_html:
            return sync.HeadResult(200, None, None, page)
        return sync.HeadResult(200, '"abc"', None, b"%PDF-1.4 fake")

    monkeypatch.setattr(sync, "fetch", fake_fetch)
    monkeypatch.setattr(sync, "DELAY_SEC", 0)
    root = tmp_path / "pdfs"
    registry = tmp_path / "finder.xml"
    conn = FakeConnection(row=(1,))

    result = sync.pull(
        conn,
        {"course": root, "staff": root / "staff", "room": root / "rooms"},
        registry=registry,
        source="s2-inspection",
    )

    assert result["registry_written"] is True
    assert INSPECTION.base_url + "m1249.pdf" in fetched
    assert (root / "m1249.pdf").exists(), "the file keeps its own name on disk"
    (row,) = conn.params_of("INSERT INTO pdf_files")
    assert row[0] == "Inspection Copy/Sem2INSPECTIONCOPY/m1249.pdf"
    assert conn.params_of("INSERT INTO sync_runs")[0][2] == "s2-inspection"
    # The term the loader files the publication under comes from this page.
    assert (tmp_path / "finder.html").read_bytes() == page
