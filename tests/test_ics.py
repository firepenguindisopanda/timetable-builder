"""
The subscription feed's calendar writer, held to the browser's download.

`tests/fixtures/ics_golden.ics` is what `assets/js/ics-export.js` makes from
`ics_golden_input.json` (tests/js/ics-golden.test.js). The feed is written in
Python because calendar servers run no JavaScript, and a class must not read
one way in a downloaded file and another in a subscribed calendar, so the
port reproduces that file byte for byte.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from timetable_extractor import ics
from timetable_extractor.subscription import Note

FIXTURES = Path(__file__).parent / "fixtures"
INPUT = json.loads((FIXTURES / "ics_golden_input.json").read_text(encoding="utf-8"))
GOLDEN = (FIXTURES / "ics_golden.ics").read_bytes().decode("utf-8")


def _build(**extra):
    meta = INPUT["meta"]
    return ics.build_calendar(
        INPUT["placed"],
        INPUT["dated"],
        week_one=date.fromisoformat(meta["weekOne"]),
        now=datetime.fromisoformat(meta["now"].replace("Z", "+00:00")),
        publication_id=meta["publicationId"],
        published_label=meta["publishedLabel"],
        page_url=meta["pageUrl"],
        **extra,
    )


def test_the_feed_writes_the_browsers_calendar_byte_for_byte():
    assert _build().text == GOLDEN


def test_the_golden_kept_its_crlf_endings():
    # .gitattributes marks *.ics -text; a checkout that converted them would
    # make the comparison above meaningless rather than failing.
    assert "\r\n" in GOLDEN and "\n" not in GOLDEN.replace("\r\n", "")


def test_a_class_with_no_weeks_is_left_out_and_named():
    assert _build().skipped == ["COMP 2601 Seminar"]


def test_the_feed_names_itself_and_asks_to_be_refetched():
    text = _build(name="UWI timetable", refresh_hours=6).text
    assert "X-WR-CALNAME:UWI timetable\r\n" in text
    assert "REFRESH-INTERVAL;VALUE=DURATION:PT6H\r\n" in text
    assert "X-PUBLISHED-TTL:PT6H\r\n" in text


def test_a_note_is_an_all_day_event_with_a_stable_uid():
    note = Note("COMP 2602", "pick:0a1b2c3d", "Your COMP 2602 Lab changed", "It was Tue 08:00.")
    first = _build(notes=[note], today=date(2026, 10, 13)).text
    later = _build(notes=[note], today=date(2026, 10, 14)).text

    assert "DTSTART;VALUE=DATE:20261013\r\n" in first
    assert "DTEND;VALUE=DATE:20261014\r\n" in first
    uid = next(line for line in first.split("\r\n") if line.startswith("UID:note-"))
    assert uid in later, "the next fetch updates the note rather than adding one"


def test_every_line_is_within_75_octets():
    text = _build(notes=[Note("X", "k", "s" * 200, "d")]).text
    for line in text.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75


def test_escaping_matches_rfc_5545():
    assert ics.escape("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"
