"""
Resolving a subscribed timetable against whatever UWI has published since.

The resolution cases are shared with tests/js/slot-identity.test.js through
tests/fixtures/slot_resolution.json, so the feed and the browser read a
student's choice the same way after a republish. The rest pins what only the
feed does: reading the link strictly, and saying in the calendar what it
could not place instead of guessing.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from timetable_extractor.subscription import (
    MAX_TOKEN_LENGTH,
    Token,
    TokenCourse,
    TokenError,
    decode_token,
    encode_token,
    fnv1a_hex,
    plan_feed,
    resolve_slot,
    slot_hash,
    slot_key,
)

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "slot_resolution.json").read_text(encoding="utf-8")
)


# Shared with the browser


def test_fnv_matches_the_reference_vectors():
    assert fnv1a_hex("") == "811c9dc5"
    assert fnv1a_hex("a") == "e40c292c"


@pytest.mark.parametrize("case", FIXTURE["hashes"], ids=lambda c: c["key"][:40])
def test_slot_hash_matches_the_browser(case):
    assert slot_key(case["session"]) == case["key"]
    assert slot_hash(case["session"]) == case["hash"]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_resolution_matches_the_browser(case):
    got = resolve_slot(case["old"], case["oldOfType"], case["newOfType"])
    index = None if got is None else case["newOfType"].index(got)
    assert index == case["expected"], case["rule"]


# The token


def _raw(payload: str) -> str:
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def test_a_token_round_trips():
    token = Token(
        11,
        (
            TokenCourse("COMP 2601", ("02572c9c", "eb11d4ee")),
            TokenCourse("FOUN 1001 (FULL & PART-TIME)", ("7c94d459",), ("Tutorial",)),
        ),
    )
    raw = encode_token(token)
    assert "=" not in raw and "+" not in raw and "/" not in raw
    assert decode_token(raw) == token


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "x" * (MAX_TOKEN_LENGTH + 1),
        "not base64!",
        _raw("2|11|COMP 2601:02572c9c"),  # a newer format than this server
        _raw("1|eleven|COMP 2601:02572c9c"),
        _raw("1|11|"),  # no courses
        _raw("1|11|COMP 2601"),  # no colon
        _raw("1|11|COMP 2601:nothex!!"),
        _raw("1|11|COMP 2601:02572c9c;COMP 2601:eb11d4ee"),  # the same course twice
        _raw("1|11|" + ";".join(f"C{i}:02572c9c" for i in range(41))),
        _raw("1|11|COMP 2601:" + ",".join(["02572c9c"] * 33)),
        base64.urlsafe_b64encode(b"\xff\xfe|11|x").decode().rstrip("="),
    ],
)
def test_a_malformed_token_is_refused(raw):
    with pytest.raises(TokenError):
        decode_token(raw)


# Planning a feed


def _s(sid, type_, day, start, end, room="FST C1", stream=None, weeks=None):
    return {
        "sessionId": sid,
        "type": type_,
        "day": day,
        "startTime": start,
        "endTime": end,
        "room": room,
        "streamLabel": stream,
        "weeks": weeks or list(range(1, 13)),
        "weeksRaw": "W1-W12",
        "staff": [],
    }


OLD = [
    _s(100, "Lecture", "Monday", "10:00", "11:00"),
    _s(101, "Lab", "Tuesday", "08:00", "10:00", "CSL 1"),
    _s(102, "Lab", "Thursday", "13:00", "15:00", "CSL 1"),
]


def _course(sessions, code="COMP 2601"):
    return {"code": code, "title": "Computer Architecture", "sessions": sessions}


def _token(*hashes, dismissed=(), code="COMP 2601", publication=10):
    return Token(publication, (TokenCourse(code, tuple(hashes), tuple(dismissed)),))


def _slots(plan):
    return sorted(f"{e['type']} {e['day']} {e['startTime']}" for e in plan.weekly)


def test_an_unchanged_timetable_resolves_under_new_ids():
    new = [{**s, "sessionId": s["sessionId"] + 4000} for s in OLD]
    plan = plan_feed(
        _token(slot_hash(OLD[0]), slot_hash(OLD[2])),
        {"COMP 2601": _course(new)},
        {"COMP 2601": OLD},
    )
    assert _slots(plan) == ["Lab Thursday 13:00", "Lecture Monday 10:00"]
    assert plan.notes == []


def test_a_moved_lab_is_followed_through_the_old_publication():
    new = [OLD[0], OLD[1], _s(203, "Lab", "Friday", "13:00", "15:00", "CSL 1")]
    plan = plan_feed(
        _token(slot_hash(OLD[0]), slot_hash(OLD[2])),
        {"COMP 2601": _course(new)},
        {"COMP 2601": OLD},
    )
    assert _slots(plan) == ["Lab Friday 13:00", "Lecture Monday 10:00"]
    assert plan.followed == 1


def test_a_choice_that_cannot_be_told_apart_becomes_a_note_not_a_guess():
    new = [OLD[0], _s(201, "Lab", "Monday", "13:00", "15:00"), _s(202, "Lab", "Friday", "13:00", "15:00")]
    plan = plan_feed(
        _token(slot_hash(OLD[0]), slot_hash(OLD[2])),
        {"COMP 2601": _course(new)},
        {"COMP 2601": OLD},
    )
    assert _slots(plan) == ["Lecture Monday 10:00"]
    assert [n.summary for n in plan.notes] == ["Your COMP 2601 Lab changed"]
    assert "Thu 13:00" in plan.notes[0].detail


def test_without_the_old_publication_only_exact_picks_resolve():
    new = [OLD[0], OLD[1], _s(203, "Lab", "Friday", "13:00", "15:00", "CSL 1")]
    plan = plan_feed(
        _token(slot_hash(OLD[0]), slot_hash(OLD[2])),
        {"COMP 2601": _course(new)},
        None,
    )
    assert _slots(plan) == ["Lecture Monday 10:00"]
    assert [n.summary for n in plan.notes] == ["One of your COMP 2601 classes changed"]


def test_a_new_type_with_one_class_is_placed_and_one_with_several_is_noted():
    new = [
        *OLD,
        _s(300, "Tutorial", "Friday", "09:00", "10:00"),
        _s(301, "Practical", "Monday", "14:00", "16:00"),
        _s(302, "Practical", "Wednesday", "14:00", "16:00"),
    ]
    plan = plan_feed(
        _token(slot_hash(OLD[0]), slot_hash(OLD[1])),
        {"COMP 2601": _course(new)},
        {"COMP 2601": OLD},
    )
    assert "Tutorial Friday 09:00" in _slots(plan)
    assert [n.summary for n in plan.notes] == ["COMP 2601 has a Practical to choose"]


def test_a_class_the_student_removed_is_not_announced_as_new():
    plan = plan_feed(
        _token(slot_hash(OLD[0]), dismissed=("Lab",)),
        {"COMP 2601": _course(OLD)},
        {"COMP 2601": OLD},
    )
    assert _slots(plan) == ["Lecture Monday 10:00"]
    assert plan.notes == []


def test_every_exam_arrives_including_ones_published_after_subscribing():
    exam = _s(400, "Examination", "Thursday", "09:00", "11:00", "JFK AUD", weeks=[12])
    plan = plan_feed(
        _token(slot_hash(OLD[0]), slot_hash(OLD[1])),
        {"COMP 2601": _course([*OLD, exam])},
        {"COMP 2601": OLD},
    )
    assert [e["sessionId"] for e in plan.dated] == [400]
    assert all(e["type"] != "Examination" for e in plan.weekly)


def test_a_withdrawn_course_is_noted():
    plan = plan_feed(_token(slot_hash(OLD[0])), {}, {"COMP 2601": OLD})
    assert plan.weekly == []
    assert [n.summary for n in plan.notes] == ["COMP 2601 is not in UWI's latest timetable"]


def test_events_carry_what_the_calendar_writer_needs():
    plan = plan_feed(_token(slot_hash(OLD[0])), {"COMP 2601": _course(OLD)}, None)
    event = plan.weekly[0]
    assert event["courseKey"] == "COMP 2601"
    assert event["courseTitle"] == "Computer Architecture"


# A link the browser made


def test_the_server_reads_the_link_the_browser_made():
    made = json.loads(
        (Path(__file__).parent / "fixtures" / "subscription_token.json").read_text(encoding="utf-8")
    )
    token = decode_token(made["token"])

    assert token.publication_id == made["publicationId"]
    assert [
        {"code": c.code, "picks": list(c.picks), "dismissed": list(c.dismissed)}
        for c in token.courses
    ] == made["courses"]


def test_the_browsers_hashes_name_real_sessions_when_python_hashes_them():
    """End to end: the browser hashed the warehouse fixture; so does Python."""
    made = json.loads(
        (Path(__file__).parent / "fixtures" / "subscription_token.json").read_text(encoding="utf-8")
    )
    warehouse = json.loads(
        (Path(__file__).parent / "fixtures" / "warehouse_sessions.json").read_text(encoding="utf-8")
    )
    courses = {c["code"]: c for c in warehouse["courses"]}
    for wanted in decode_token(made["token"]).courses:
        hashes = {slot_hash(s) for s in courses[wanted.code]["sessions"]}
        assert set(wanted.picks) <= hashes, wanted.code
