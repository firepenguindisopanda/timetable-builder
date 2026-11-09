"""
A course code CELCAT cut off at the edge of its block goes back to its course.

The 6 Nov 2026 publication printed one Tuesday postgraduate block, an hour
long, as "Courses: GEND 3501; GEND 5001; GEND 6002; GEND 7001; GEND". The cell
had no room for the last number, and the text is not in the PDF. Loaded as it
stood, the bare "GEND" became a course of its own, and GEND 8001, whose own PDF
the block was read from, lost the class.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database import loader
from timetable_extractor.database.courses import clipped_subject, published_subjects
from timetable_extractor.database.records import SessionRecord, merge_records
from timetable_extractor.observability import Diagnostics

CANONICAL = {"GEND 3501", "GEND 5001", "GEND 6002", "GEND 7001", "GEND 8001",
             "CAPE BIOL", "MHC", "COMP 2601"}

#: Which course each PDF is the timetable of, as `resources.pdf_link` says.
OWN_COURSE = {
    "m19801.pdf": "GEND 3501",
    "m19804.pdf": "GEND 8001",
    "m1000.pdf": "COMP 2601",
}


def test_subjects_come_from_published_codes():
    assert published_subjects(CANONICAL) == {"GEND", "CAPE", "COMP"}


@pytest.mark.parametrize("code", ["GEND", "gend", " GEND "])
def test_a_bare_subject_is_a_clipped_code(code):
    assert clipped_subject(code, published_subjects(CANONICAL)) == "GEND"


@pytest.mark.parametrize("code", ["GEND 8001", "XYZW", "GEND 80", "MHC", "", "2601"])
def test_anything_else_is_not(code):
    assert clipped_subject(code, published_subjects(CANONICAL)) is None


def record(code, source):
    return SessionRecord(
        course_code=code, day="Tuesday", start_min=1080, end_min=1140,
        activity_type="Postgraduate", sources={source},
    )


def block(source):
    """The GEND block as one PDF describes it: one record per code named."""
    codes = ["GEND 3501", "GEND 5001", "GEND 6002", "GEND 7001", "GEND"]
    return [record(code, source) for code in codes]


def test_the_clipped_code_becomes_the_course_whose_pdf_it_is():
    diagnostics = Diagnostics(source="finder.xml")
    kept = loader.repair_clipped_codes(block("m19804.pdf"), OWN_COURSE, CANONICAL, diagnostics)

    assert [r.course_code for r in kept] == [
        "GEND 3501", "GEND 5001", "GEND 6002", "GEND 7001", "GEND 8001",
    ]
    assert diagnostics.findings["course_code_clipped"] == 1
    assert diagnostics.samples["course_code_clipped"] == [
        {"code": "GEND", "course": "GEND 8001", "source": "m19804.pdf"}
    ]


def test_every_course_has_the_class_once_and_no_bare_subject_is_left():
    diagnostics = Diagnostics(source="finder.xml")
    raw = block("m19801.pdf") + block("m19804.pdf")
    merged = merge_records(loader.repair_clipped_codes(raw, OWN_COURSE, CANONICAL, diagnostics))

    assert sorted(r.course_code for r in merged) == [
        "GEND 3501", "GEND 5001", "GEND 6002", "GEND 7001", "GEND 8001",
    ]


def test_a_clipped_code_read_from_another_subjects_pdf_is_dropped():
    diagnostics = Diagnostics(source="finder.xml")
    raw = [record("COMP 2601", "m1000.pdf"), record("GEND", "m1000.pdf")]
    kept = loader.repair_clipped_codes(raw, OWN_COURSE, CANONICAL, diagnostics)

    assert [r.course_code for r in kept] == ["COMP 2601"]
    assert diagnostics.samples["course_code_clipped"] == [
        {"code": "GEND", "course": None, "source": "m1000.pdf"}
    ]


def test_a_clipped_code_read_from_a_room_pdf_is_dropped():
    diagnostics = Diagnostics(source="finder.xml")
    kept = loader.repair_clipped_codes(
        [record("GEND", "r3480.pdf")], OWN_COURSE, CANONICAL, diagnostics,
    )
    assert kept == []
    assert diagnostics.findings["course_code_clipped"] == 1


def test_published_codes_and_unknown_codes_are_left_alone():
    diagnostics = Diagnostics(source="finder.xml")
    raw = [record("MHC", "m1000.pdf"), record("CAPE BIOL", "m1000.pdf"),
           record("XYZW 1001", "m1000.pdf")]
    kept = loader.repair_clipped_codes(raw, OWN_COURSE, CANONICAL, diagnostics)

    assert [r.course_code for r in kept] == ["MHC", "CAPE BIOL", "XYZW 1001"]
    assert not diagnostics.findings
