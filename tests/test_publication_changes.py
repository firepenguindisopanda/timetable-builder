"""
Tests for the publication diff.

`diff_sessions` is pure - rows in, changes out - so the whole classification
is pinned here without a database. What matters is not that it produces
changes but that it produces the *right kind*: a student reading "your lecture
moved" when the venue was merely confirmed, or "moved twice" when it moved and
moved back, stops trusting the page.
"""

from __future__ import annotations

import pytest

from timetable_extractor.database.changes import (
    CLASS_ADDED,
    CLASS_MOVED,
    CLASS_REMOVED,
    CLASS_VENUE_CONFIRMED,
    COURSE_ADDED,
    COURSE_DROPPED,
    COURSE_RENAMED,
    SITTING_ADDED,
    SITTING_REMOVED,
    diff_sessions,
    display_kind,
    slot_delta,
    summarise,
)


def slot(day="Monday", start="09:00", end="10:00", room="FST CSL1", weeks="W1-W12"):
    return {"day": day, "startTime": start, "endTime": end, "room": room, "weeks": weeks}


def session(
    code="COMP 1601",
    day="Monday",
    start=540,
    end=600,
    activity_type="Lecture",
    stream_label=None,
    room="FST CSL1",
    weeks="W1-W12",
    title="Introduction to Computing",
    resource_id=None,
):
    return {
        "code": code,
        "title": title,
        "resource_id": resource_id,
        "activity_type": activity_type,
        "stream_label": stream_label,
        "day": day,
        "start_min": start,
        "end_min": end,
        "room": room,
        "weeks_raw": weeks,
    }


def kinds(changes):
    return [c.change_type for c in changes]


# Nothing happening


def test_identical_publications_produce_no_changes():
    rows = [session(), session(day="Wednesday", activity_type="Lab")]
    assert diff_sessions(rows, rows) == []


def test_row_order_does_not_matter():
    """Publications are loaded by separate runs; row order is not meaningful."""
    a = [session(), session(day="Friday", activity_type="Lab")]
    assert diff_sessions(a, list(reversed(a))) == []


def test_first_publication_has_nothing_to_compare_against():
    assert diff_sessions([], []) == []


# Classes moving


def test_a_class_changing_day_has_moved():
    before = [session(day="Wednesday")]
    after = [session(day="Friday")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_MOVED
    assert change.before["slots"][0]["day"] == "Wednesday"
    assert change.after["slots"][0]["day"] == "Friday"


def test_a_class_changing_only_its_room_has_still_moved():
    (change,) = diff_sessions([session(room="ENG 101")], [session(room="TLC TR3")])
    assert change.change_type == CLASS_MOVED


def test_a_class_changing_only_its_weeks_has_changed():
    """OPTM 3011 went from every week to alternating ones without moving."""
    before = [session(weeks="W1-W12")]
    after = [session(weeks="W1, W3, W5, W7, W9, W11")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_MOVED
    assert change.after["slots"][0]["weeks"] == "W1, W3, W5, W7, W9, W11"


def test_times_are_rendered_for_the_page():
    (change,) = diff_sessions([session(start=540, end=600)], [session(start=780, end=840)])
    assert change.before["slots"][0]["startTime"] == "09:00"
    assert change.after["slots"][0]["startTime"] == "13:00"
    assert change.after["slots"][0]["endTime"] == "14:00"


def test_a_class_that_moved_and_moved_back_has_not_moved():
    """
    The reason diffs compare endpoints instead of replaying hops. Composing
    publication 1 -> 2 -> 3 would report two moves; the honest answer is none.
    """
    publication_1 = [session(day="Monday")]
    publication_3 = [session(day="Monday")]
    assert diff_sessions(publication_1, publication_3) == []


# Venue confirmation


@pytest.mark.parametrize(
    "placeholder",
    ["Venue to be advised", "venue not confirmed", "TBA", None, "", "   "],
)
def test_a_placeholder_room_becoming_real_is_a_confirmation(placeholder):
    before = [session(room=placeholder)]
    after = [session(room="FHE 314 A")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_VENUE_CONFIRMED


def test_a_confirmation_that_also_changes_time_is_a_move():
    """Changing when it runs is not good news, whatever happened to the room."""
    before = [session(room="Venue to be advised", day="Monday")]
    after = [session(room="FHE 314 A", day="Thursday")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_MOVED


def test_a_real_room_becoming_a_placeholder_is_a_move_not_a_confirmation():
    before = [session(room="FHE 314 A")]
    after = [session(room="Venue to be advised")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_MOVED


def test_a_multi_room_class_is_a_move_even_if_one_room_was_a_placeholder():
    """COCR 1034 moved three rooms at once; that is not a confirmation."""
    before = [session(room="Venue to be advised"), session(room="FHE CLL Room 1")]
    after = [session(room="TLC TR3"), session(room="TLC TR4")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_MOVED


# Classes arriving and leaving


def test_a_new_class_on_an_existing_course_is_an_addition():
    before = [session(activity_type="Lecture")]
    after = [session(activity_type="Lecture"), session(activity_type="Tutorial")]
    changes = diff_sessions(before, after)
    assert kinds(changes) == [CLASS_ADDED]
    assert changes[0].activity_type == "Tutorial"
    assert changes[0].before is None


def test_a_class_disappearing_from_a_surviving_course_is_a_removal():
    before = [session(activity_type="Lecture"), session(activity_type="Tutorial")]
    after = [session(activity_type="Tutorial")]
    changes = diff_sessions(before, after)
    assert kinds(changes) == [CLASS_REMOVED]
    assert changes[0].activity_type == "Lecture"
    assert changes[0].after is None


def test_a_removal_that_takes_the_last_of_its_type_is_flagged():
    """
    FREN 3401 lost its Lecture entirely. The option group id contains the
    activity type, so this is the case that strands a saved placement, and the
    page says so rather than listing a removal.
    """
    before = [session(activity_type="Lecture"), session(activity_type="Tutorial")]
    after = [session(activity_type="Tutorial")]
    (change,) = diff_sessions(before, after)
    assert change.before["lastOfType"] is True


def test_a_removal_leaving_other_sittings_of_the_type_is_not_flagged():
    before = [
        session(activity_type="Lecture", day="Monday"),
        session(activity_type="Lecture", day="Tuesday", stream_label="L2"),
    ]
    after = [session(activity_type="Lecture", day="Tuesday", stream_label="L2")]
    (change,) = diff_sessions(before, after)
    assert change.change_type == CLASS_REMOVED
    assert change.before["lastOfType"] is False


# Courses arriving and leaving


def test_a_new_course_is_reported_once_not_per_class():
    after = [
        session(code="PORT 2001", activity_type="Lecture"),
        session(code="PORT 2001", activity_type="Tutorial"),
    ]
    changes = diff_sessions([], after)
    assert kinds(changes) == [COURSE_ADDED]
    assert changes[0].course_code == "PORT 2001"


def test_a_withdrawn_course_is_reported_once_not_per_class():
    before = [
        session(code="LING 2304", activity_type="Lecture"),
        session(code="LING 2304", activity_type="Tutorial"),
    ]
    changes = diff_sessions(before, [])
    assert kinds(changes) == [COURSE_DROPPED]


# Renames


def test_a_code_change_sharing_a_resource_is_a_rename():
    """
    `EDMA 11**` became `EDMA 1142`: the same published resource under a real
    code instead of a placeholder. Diffing on code alone reads that as a
    withdrawal plus an arrival, which is two alarming entries for a course
    that never went anywhere.
    """
    before = [session(code="EDMA 11**", title="Teaching Numeracy", resource_id=77)]
    after = [session(code="EDMA 1142", title="Teaching Numeracy", resource_id=77)]
    changes = diff_sessions(before, after)
    assert kinds(changes) == [COURSE_RENAMED]
    assert changes[0].before["code"] == "EDMA 11**"
    assert changes[0].after["code"] == "EDMA 1142"
    assert changes[0].course_code == "EDMA 1142"


def test_a_withdrawal_and_an_arrival_with_different_resources_stay_separate():
    """`BEDP 22XX` was withdrawn outright; `PORT 2001` is unrelated."""
    before = [session(code="BEDP 22XX", resource_id=11)]
    after = [session(code="PORT 2001", resource_id=22)]
    changes = diff_sessions(before, after)
    assert sorted(kinds(changes)) == [COURSE_ADDED, COURSE_DROPPED]


def test_a_rename_does_not_also_report_its_classes_as_added_and_removed():
    before = [
        session(code="EDMA 11**", activity_type="Lecture", resource_id=77),
        session(code="EDMA 11**", activity_type="Tutorial", resource_id=77),
    ]
    after = [
        session(code="EDMA 1142", activity_type="Lecture", resource_id=77),
        session(code="EDMA 1142", activity_type="Tutorial", resource_id=77),
    ]
    assert kinds(diff_sessions(before, after)) == [COURSE_RENAMED]


def test_courses_without_a_resource_are_never_treated_as_renames():
    """
    A course that appears only in a room's timetable has no resource of its
    own. Two such courses must not be paired up on a null.
    """
    before = [session(code="TOUR 5101", resource_id=None)]
    after = [session(code="FILM 2100", resource_id=None)]
    assert sorted(kinds(diff_sessions(before, after))) == [COURSE_ADDED, COURSE_DROPPED]


# Determinism and shape


def test_output_order_is_stable():
    before = [session(code="ZOOL 1001"), session(code="ACCT 2021", day="Tuesday")]
    after = [session(code="ZOOL 1001", day="Friday"), session(code="ACCT 2021")]
    first = diff_sessions(before, after)
    second = diff_sessions(list(reversed(before)), list(reversed(after)))
    assert [(c.change_type, c.course_code) for c in first] == [
        (c.change_type, c.course_code) for c in second
    ]


# What the reader is shown
#
# The stored change type records what happened to the class. These decide what
# the page says about it, and the two are not always the same.


def test_unchanged_slots_are_not_shown_on_either_side():
    """
    ACCT 2021's Tutorial kept both its sittings and gained a third. Printing
    the two unchanged rows twice makes the reader find the one that moved.
    """
    before = [slot(start="09:00"), slot(start="10:00")]
    after = [slot(start="09:00"), slot(start="10:00"), slot(start="11:00", room="FSS MLT")]
    before_only, after_only = slot_delta(before, after)
    assert before_only == []
    assert [s["startTime"] for s in after_only] == ["11:00"]


def test_a_genuine_move_keeps_both_sides():
    before_only, after_only = slot_delta([slot(day="Wednesday")], [slot(day="Friday")])
    assert [s["day"] for s in before_only] == ["Wednesday"]
    assert [s["day"] for s in after_only] == ["Friday"]


def test_slot_delta_ignores_order():
    a = [slot(start="09:00"), slot(start="10:00")]
    assert slot_delta(a, list(reversed(a))) == ([], [])


def test_a_class_that_only_gained_a_sitting_has_not_moved():
    """Labelling this "moved" sends a student looking for a change that is
    not there. It is an extra sitting, and the headline count must not
    include it."""
    assert display_kind(CLASS_MOVED, [], [slot()]) == SITTING_ADDED


def test_a_class_that_only_lost_a_sitting_has_not_moved():
    assert display_kind(CLASS_MOVED, [slot()], []) == SITTING_REMOVED


def test_a_class_that_gained_and_lost_has_moved():
    assert display_kind(CLASS_MOVED, [slot(day="Monday")], [slot(day="Friday")]) == CLASS_MOVED


@pytest.mark.parametrize(
    "stored", [CLASS_ADDED, CLASS_REMOVED, CLASS_VENUE_CONFIRMED]
)
def test_other_kinds_are_shown_as_they_were_stored(stored):
    assert display_kind(stored, [], [slot()]) == stored


def test_summarise_counts_each_kind():
    changes = diff_sessions(
        [session(activity_type="Lecture"), session(code="LING 2304")],
        [session(activity_type="Lecture", day="Friday"), session(code="PORT 2001")],
    )
    counts = summarise(changes)
    assert counts[CLASS_MOVED] == 1
    assert counts[COURSE_ADDED] == 1
    assert counts[COURSE_DROPPED] == 1
    assert counts[CLASS_VENUE_CONFIRMED] == 0
