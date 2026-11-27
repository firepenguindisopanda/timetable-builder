"""
Loading a second term without disturbing the first.

Loaded as things stood on 26 Nov 2026, the semester 2 inspection copy would
have become the newest publication and so semester 1's replacement for every
student, overwritten 595 of semester 1's file records, and stored no semester
at all, its "Inspection_Sem_2_2026_2027" heading matching nothing. Pinned
here: the term is read from the index title, or the PDFs' headings without
one, and nothing is written without a term; the inspection copy's files and
resources are stored under their path from the root address; courses, rooms
and staff keep semester 1's values; and the previous publication, which the
diff and the carried weeks come from, is looked for inside the term.
SEMESTERS-SPEC.md sections 3, 6.1, 6.3 and 6.4.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from timetable_extractor.database import changes, loader
from timetable_extractor.database.weeks import expand_weeks, export_horizon
from timetable_extractor.extract import extract_timetable

FIXTURES = Path(__file__).parent / "fixtures" / "s2_inspection"
INSPECTION = "Inspection_Sem_2_2026_2027"
PREFIX = "Inspection Copy/Sem2INSPECTIONCOPY/"


# Where the term comes from


def test_the_index_title_names_the_term():
    html = (FIXTURES / "finder.html").read_text(encoding="utf-8")
    assert loader.finder_title(html) == INSPECTION


@pytest.mark.parametrize("html", [None, "", "<title>Timetable Finder - </title>", "<p>no title</p>"])
def test_a_page_without_a_label_has_no_title(html):
    assert loader.finder_title(html) is None


def test_the_title_wins_over_the_headings():
    term = loader.publication_term(INSPECTION, ["Semester_1_TT2026_2027"])
    assert (term.academic_year, term.semester, term.stage) == ("2026/2027", 2, "inspection")
    assert term.read_from == "the index title"


def test_without_a_title_the_commonest_heading_decides():
    """Root's finder.html was never kept before 27 Nov 2026."""
    term = loader.publication_term(
        None,
        ["Semester_1_TT2026_2027", "Semester_I_2026_2027", "Semester_1_TT2026_2027", None],
    )
    assert (term.academic_year, term.semester, term.stage) == ("2026/2027", 1, "final")
    assert term.label == "Semester_1_TT2026_2027"
    assert term.read_from == "the PDF headings"


def test_no_term_anywhere_is_none():
    assert loader.publication_term("Timetable", [None, "Course timetable"]) is None


@pytest.mark.parametrize("name", ["m1249.pdf", "m12211.pdf"])
def test_real_inspection_pdfs_give_their_term_and_13_weeks(name):
    """CELCAT's own output, not a hand-built string."""
    result = extract_timetable(str(FIXTURES / name))
    assert result["semester"] == INSPECTION
    assert export_horizon(result["course_title"]) == 1
    weeks = {w for e in result["entries"] for w in expand_weeks(e.get("weeks"))}
    assert max(weeks) == 13, "week 13 of semester 2 must survive extraction"


# Clipped codes are given back from the registry being loaded


def test_own_resources_come_from_the_registry_in_hand():
    own_course, own_room = loader.own_resources((FIXTURES / "finder.xml").read_bytes())
    assert own_course == {"m1249.pdf": "ACCT 1002", "m12211.pdf": "MGMT 3095"}
    assert own_room == {}


def test_own_rooms_are_written_as_the_loader_stores_them():
    xml = (
        b'<finder><resource id="9" type="room" link="r9.pdf">'
        b"<name>TLC  LT D, Teaching and Learning Complex</name></resource></finder>"
    )
    assert loader.own_resources(xml) == ({}, {"r9.pdf": "TLC LT D"})


# A database stand-in


class Cursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=()):
        self.conn.statements.append((" ".join(str(sql).split()), params))

    def executemany(self, sql, rows):
        self.conn.statements.append((" ".join(str(sql).split()), list(rows)))

    def fetchone(self):
        return self.conn.one

    def fetchall(self):
        return self.conn.all


class Connection:
    def __init__(self, one=(1,), all=()):
        self.statements: list[tuple[str, object]] = []
        self.one = one
        self.all = list(all)

    def cursor(self):
        return Cursor(self)

    def commit(self):
        return None

    def transaction(self):
        raise AssertionError("not expected")

    def sql_starting(self, start):
        return [(sql, params) for sql, params in self.statements if sql.startswith(start)]


# Files and resources under their path from the root


def test_pdfs_are_registered_under_their_path_from_the_root(tmp_path):
    pdf = tmp_path / "m1249.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    conn = Connection(all=[(PREFIX + "m1249.pdf", 41), ("m1249.pdf", 3)])

    ids = loader.register_pdfs(conn, [pdf], link_prefix=PREFIX)

    ((_, rows),) = conn.sql_starting("INSERT INTO pdf_files")
    assert rows[0][0] == PREFIX + "m1249.pdf"
    assert ids == {"m1249.pdf": 41}, "keyed by the bare name the records carry"


def test_root_pdfs_keep_their_bare_names(tmp_path):
    pdf = tmp_path / "m1249.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    conn = Connection(all=[("m1249.pdf", 3)])

    assert loader.register_pdfs(conn, [pdf]) == {"m1249.pdf": 3}
    ((_, rows),) = conn.sql_starting("INSERT INTO pdf_files")
    assert rows[0][0] == "m1249.pdf"


def test_an_inspection_resource_is_its_own_row(tmp_path):
    conn = Connection()
    loader.load_index(
        conn, (FIXTURES / "finder.xml").read_bytes(), 17, source="s2-inspection"
    )
    inserts = [params for sql, params in conn.sql_starting("INSERT INTO resources")]
    assert [p[2] for p in inserts] == [PREFIX + "m1249.pdf", PREFIX + "m12211.pdf"]
    assert {p[-1] for p in inserts} == {"s2-inspection"}


@pytest.mark.parametrize(
    ("source", "kept_first"),
    [("s2-inspection", True), ("root", False)],
)
def test_another_source_only_fills_what_a_course_lacks(source, kept_first):
    """
    Courses are one row across terms. Repointed at the inspection copy,
    semester 1's `resource_id` would empty the free rooms page, which counts
    a room as registered through it and the latest publication.
    """
    conn = Connection()
    loader.load_index(conn, (FIXTURES / "finder.xml").read_bytes(), 17, source=source)
    (sql, _), *_ = conn.sql_starting("INSERT INTO courses")
    kept = "COALESCE(courses.resource_id, EXCLUDED.resource_id)"
    replaced = "COALESCE(EXCLUDED.resource_id, courses.resource_id)"
    assert (kept in sql) is kept_first
    assert (replaced in sql) is not kept_first


# The publication row


def test_a_new_publication_is_filed_under_its_source_term_and_stage():
    conn = Connection()
    term = loader.publication_term(INSPECTION, [])
    # The SELECT finds nothing; the INSERT returns the new id.
    answers = iter([None, (17,)])
    conn.cursor = lambda: _Answering(conn, answers)

    publication_id, reused = loader.upsert_publication(
        conn, b"<finder/>", source="s2-inspection", term=term
    )

    assert (publication_id, reused) == (17, False)
    ((sql, params),) = conn.sql_starting("INSERT INTO publications")
    assert params[-4:] == ("s2-inspection", "2026/2027", 2, "inspection")


def test_a_reused_publication_keeps_its_term():
    conn = Connection(one=(16,))
    term = loader.publication_term("Semester_1_TT2026_2027", [])

    assert loader.upsert_publication(conn, b"<finder/>", term=term) == (16, True)
    ((sql, params),) = conn.sql_starting("UPDATE publications")
    assert "COALESCE(academic_year, %s)" in sql, "fills a gap, never moves it"
    assert params == ("root", "2026/2027", 1, "final", 16)


class _Answering(Cursor):
    def __init__(self, conn, answers):
        super().__init__(conn)
        self.answers = answers

    def fetchone(self):
        return next(self.answers)


# Diffs and carried weeks stay inside a term


def test_the_previous_publication_is_looked_for_inside_the_term():
    """Semester 1 against semester 2 would read as every class changing."""
    conn = Connection(one=None)
    assert changes.previous_publication(conn, 17) is None
    ((sql, params),) = conn.statements
    assert "p.academic_year IS NOT DISTINCT FROM this.academic_year" in sql
    assert "p.semester IS NOT DISTINCT FROM this.semester" in sql
    assert "p.load_revision > 0" in sql
    assert "source" not in sql, "across sources: the final diffs against the inspection copy"
    assert params == (17,)


def test_the_changes_pair_is_the_named_terms():
    conn = Connection(one=None)
    assert changes.current_pair(conn, ("2026/2027", 2)) == []
    sql, params = conn.statements[0]
    assert "FROM term_publication" in sql
    assert params == {"year": "2026/2027", "semester": 2}


# Nothing is written without a term


def _corpus(tmp_path, *, page=None):
    finder = tmp_path / "finder.xml"
    finder.write_bytes((FIXTURES / "finder.xml").read_bytes())
    if page is not None:
        (tmp_path / "finder.html").write_text(page, encoding="utf-8")
    pdfs = tmp_path / "pdfs"
    pdfs.mkdir()
    (pdfs / "m1249.pdf").write_bytes(b"%PDF-1.4")
    return finder, pdfs


def _fake_extraction(monkeypatch, heading):
    monkeypatch.setattr(
        loader,
        "extract_timetable",
        lambda path: {"course_title": "ACCT 1002 (Wks S2W1-S2W13)", "semester": heading, "entries": []},
    )
    monkeypatch.setattr(loader, "records_from_extraction", lambda result, source: [])


def test_a_corpus_with_no_term_is_refused_before_connecting(monkeypatch, tmp_path):
    finder, pdfs = _corpus(tmp_path)
    _fake_extraction(monkeypatch, None)

    def never():
        raise AssertionError("connected for a corpus that cannot be filed")

    with pytest.raises(loader.UnknownTerm):
        loader.load_all(never, finder_xml=finder, pdf_dirs=[pdfs], progress=False)


def test_the_inspection_copy_is_filed_by_its_index_title(monkeypatch, tmp_path):
    finder, pdfs = _corpus(tmp_path, page=(FIXTURES / "finder.html").read_text("utf-8"))
    _fake_extraction(monkeypatch, None)
    seen = {}

    class Stop(Exception):
        pass

    def fake_upsert(conn, xml_bytes, **kwargs):
        seen.update(kwargs)
        raise Stop

    class Opened:
        def __enter__(self):
            return Connection()

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(loader, "upsert_publication", fake_upsert)

    with pytest.raises(Stop):
        loader.load_all(
            Opened, finder_xml=finder, pdf_dirs=[pdfs], progress=False, source="s2-inspection"
        )

    assert seen["source"] == "s2-inspection"
    term = seen["term"]
    assert (term.academic_year, term.semester, term.stage) == ("2026/2027", 2, "inspection")
    assert term.read_from == "the index title"
