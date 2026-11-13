"""
A room CELCAT cut off at the edge of its block goes back to its full name.

CHEM 1370's Friday 08:00 lecture has been stored in room "TLC" since at least
publication 14. The block ends "Room: TLC" and the second line, "LT D", is cut
off at the cell's bottom edge, even in TLC LT D's own room PDF. "TLC" is not a
room; it became one, with no resource, and the class was listed under it.
Publication 16 held 19 sessions in seven such rooms ("FST", "TLC", "Daaga",
"FHE", "FHE SOE", "ENG", "TCB"). This is the room-side twin of the clipped
course codes in test_clipped_codes.py.
"""

from __future__ import annotations

from timetable_extractor.database import loader
from timetable_extractor.database.records import SessionRecord, merge_records
from timetable_extractor.observability import Diagnostics

REGISTERED = {"TLC LT D", "TLC LT B", "TLC TR3", "TCB 31", "TCB 32",
              "FHE SOE 219", "FHE SOE 228", "Daaga Auditorium"}

#: Which room each room PDF is the timetable of, as `resources.pdf_link` says.
OWN_ROOM = {"r37469.pdf": "TLC LT D", "r3608.pdf": "TCB 32", "r9228.pdf": "FHE SOE 228"}


def lecture(room, source, **over):
    fields = dict(course_code="CHEM 1370", day="Friday", start_min=480, end_min=540,
                  activity_type="Lecture", weeks_raw="W11-W12", room_code=room,
                  sources={source})
    fields.update(over)
    return SessionRecord(**fields)


def repair(records):
    diagnostics = Diagnostics(source="test")
    kept = loader.repair_clipped_rooms(records, OWN_ROOM, REGISTERED, diagnostics)
    return kept, diagnostics.findings


def test_a_clipped_room_in_a_rooms_own_pdf_is_that_room():
    (fixed,), findings = repair([lecture("TLC", "r37469.pdf")])
    assert fixed.room_code == "TLC LT D"
    assert findings == {"room_code_clipped": 1}


def test_the_course_and_staff_pdfs_take_the_room_from_the_room_pdf():
    """All three descriptions of CHEM 1370's lecture said "TLC". After the
    repair they agree on TLC LT D and merge into one class."""
    records = [lecture("TLC", "r37469.pdf"), lecture("TLC", "m110876.pdf"),
               lecture("TLC", "s97895.pdf")]
    kept, _ = repair(records)
    (merged,) = merge_records(kept)
    assert merged.room_code == "TLC LT D"
    assert merged.sources == {"r37469.pdf", "m110876.pdf", "s97895.pdf"}


def test_a_full_name_printed_elsewhere_resolves_it_without_a_room_pdf():
    """m110876.pdf printed one copy of the lecture with "LT D" intact."""
    kept, _ = repair([lecture("TLC LT D", "m110876.pdf"), lecture("TLC", "s97895.pdf")])
    assert {r.room_code for r in kept} == {"TLC LT D"}


def test_two_rooms_that_could_be_meant_resolve_neither():
    """Parallel tutorials in TCB 31 and TCB 32, and a staff PDF saying "TCB":
    either could be meant, and guessing would put a class in the wrong room."""
    tut = dict(activity_type="Tutorial")
    records = [lecture("TCB 31", "m1.pdf", **tut), lecture("TCB 32", "m1.pdf", **tut),
               lecture("TCB", "s1.pdf", **tut)]
    kept, findings = repair(records)
    assert sorted(r.room_code for r in kept) == ["TCB", "TCB 31", "TCB 32"]
    assert findings == {"room_clipped_unresolved": 1}


def test_a_different_class_at_the_same_hour_is_no_evidence():
    """Another course's lecture in TLC LT B at 08:00 says nothing about where
    CHEM 1370's is."""
    records = [lecture("TLC LT B", "m2.pdf", course_code="BIOL 1262"),
               lecture("TLC", "s97895.pdf")]
    kept, findings = repair(records)
    assert {r.course_code: r.room_code for r in kept}["CHEM 1370"] == "TLC"
    assert findings == {"room_clipped_unresolved": 1}


def test_a_room_pdf_whose_room_is_printed_in_full_does_not_claim_the_clipped_one():
    """
    "Rooms: FHE SOE 228; FHE" read from FHE SOE 228's own PDF. The room the
    PDF is about is already there, so the clipped one is a second room, and
    calling it FHE SOE 228 would invent a duplicate.
    """
    records = [lecture("FHE SOE 228", "r9228.pdf"), lecture("FHE", "r9228.pdf")]
    kept, findings = repair(records)
    assert sorted(r.room_code for r in kept) == ["FHE", "FHE SOE 228"]
    assert findings == {"room_clipped_unresolved": 1}


def test_registered_rooms_unknown_rooms_and_no_room_are_left_alone():
    records = [lecture("TLC LT D", "m1.pdf"), lecture("FHE CLL Room 9", "m1.pdf"),
               lecture("Remote Teaching", "m1.pdf"), lecture(None, "m1.pdf")]
    kept, findings = repair(records)
    assert [r.room_code for r in kept] == ["TLC LT D", "FHE CLL Room 9", "Remote Teaching", None]
    assert findings == {}


def test_a_prefix_must_end_on_a_word():
    """"TCB 3" is not a clipped "TCB 32": the cut falls on a line break,
    and CELCAT breaks lines between words."""
    kept, findings = repair([lecture("TCB 3", "r3608.pdf")])
    assert kept[0].room_code == "TCB 3"
    assert findings == {}
