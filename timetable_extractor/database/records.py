"""
Turn raw extraction output into normalised session records.

The same class is published in up to three PDFs - the course's, the room's and
each teacher's - and each view carries different detail. Course PDFs name the
room but usually omit staff; room PDFs name the staff. Merging the three is
what produces a complete record, so this module is deliberately pure and
testable: no database, no filesystem.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from timetable_extractor.database.weeks import expand_weeks

DAY_ORDER = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)
VALID_DAYS = set(DAY_ORDER)

_TIME = re.compile(r"^(\d{1,2}):(\d{2})\s*(AM|PM)$", re.I)
# CELCAT separates several courses or rooms sharing one block with semicolons.
_LIST_SEPARATOR = re.compile(r"\s*;\s*")
# A trailing "(*)" annotates a staff entry; it is not part of the name.
_STAFF_MARKER = re.compile(r"\s*\(\*\)\s*$")


def time_to_minutes(label: str | None) -> int | None:
    """'09:00 AM' -> 540. Returns None for the extractor's '?' placeholder."""
    match = _TIME.match((label or "").strip())
    if not match:
        return None
    hours, minutes, meridiem = int(match.group(1)), int(match.group(2)), match.group(3).upper()
    if meridiem == "PM" and hours != 12:
        hours += 12
    if meridiem == "AM" and hours == 12:
        hours = 0
    return hours * 60 + minutes


def normalise_course_code(raw: str | None) -> str | None:
    """'COMP  2601' -> 'COMP 2601'. Codes must match across PDF sources."""
    if not raw:
        return None
    return " ".join(raw.upper().split()) or None


def split_courses(raw: str | None) -> list[str]:
    """A shared block lists every course it serves."""
    if not raw:
        return []
    codes = (normalise_course_code(part) for part in _LIST_SEPARATOR.split(raw))
    return [c for c in codes if c]


def split_rooms(raw: str | None) -> list[str]:
    """A class can occupy more than one room at once (overflow venues)."""
    if not raw:
        return []
    return [part.strip() for part in _LIST_SEPARATOR.split(raw) if part.strip()]


def split_staff(raw: str | None) -> list[str]:
    """'HULME, Mark; PUSTAM, Anil' -> two names, in listed order."""
    if not raw:
        return []
    names = []
    for part in _LIST_SEPARATOR.split(raw):
        name = _STAFF_MARKER.sub("", part).strip()
        if name:
            names.append(name)
    return names


@dataclass
class SessionRecord:
    """One class, as described by one or more PDFs."""

    course_code: str
    day: str
    start_min: int
    end_min: int
    room_code: str | None = None
    activity_type: str | None = None
    stream_label: str | None = None
    weeks_raw: str | None = None
    weeks: list[int] = field(default_factory=list)
    week_count: int | None = None
    semester: str | None = None
    notes: str | None = None
    raw_text: str | None = None
    staff: list[str] = field(default_factory=list)
    sources: set[str] = field(default_factory=set)

    @property
    def identity(self) -> tuple:
        """
        What makes two descriptions the same real class.

        The room is part of the identity on purpose: a course can run parallel
        tutorial streams at the same hour in different rooms with no stream
        label to tell them apart, and collapsing those would hide a choice the
        student needs to make.
        """
        return (
            self.course_code,
            self.day,
            self.start_min,
            self.end_min,
            self.room_code,
            self.activity_type,
            self.stream_label,
            self.weeks_raw,
        )

    @property
    def core_identity(self) -> tuple:
        """
        The part of the identity every source agrees on.

        Room and stream are excluded because they are the two fields a given
        PDF may simply not mention - a staff timetable often omits the stream
        marker that the course timetable prints.
        """
        return (
            self.course_code,
            self.day,
            self.start_min,
            self.end_min,
            self.activity_type,
            self.weeks_raw,
        )

    def compatible_with(self, other: "SessionRecord") -> bool:
        """
        Whether this record could be a less detailed view of `other`.

        Only fields this record leaves blank may differ; a stated room that
        disagrees means these are genuinely different classes.
        """
        for mine, theirs in (
            (self.room_code, other.room_code),
            (self.stream_label, other.stream_label),
        ):
            if mine is not None and mine != theirs:
                return False
        return True

    def absorb(self, other: "SessionRecord") -> None:
        """Fold another description of this class into this record."""
        for name in other.staff:
            if name not in self.staff:
                self.staff.append(name)
        self.sources |= other.sources
        self.room_code = self.room_code or other.room_code
        self.stream_label = self.stream_label or other.stream_label
        self.activity_type = self.activity_type or other.activity_type
        self.week_count = self.week_count or other.week_count
        self.semester = self.semester or other.semester
        self.notes = self.notes or other.notes


def records_from_extraction(
    result: dict[str, Any],
    source: str,
) -> list[SessionRecord]:
    """
    Convert one PDF's extraction output into session records.

    A block naming several courses or rooms becomes one record per
    course/room pair - each of those courses really does hold that class, and
    each of those rooms really is occupied.
    """
    semester = result.get("semester")
    records: list[SessionRecord] = []

    for entry in result.get("entries", []):
        day = entry.get("day")
        start = time_to_minutes(entry.get("start_time"))
        end = time_to_minutes(entry.get("end_time"))

        # A session that cannot be placed on a calendar is not worth storing.
        if day not in VALID_DAYS or start is None or end is None or end <= start:
            continue

        courses = split_courses(entry.get("course"))
        if not courses:
            continue

        rooms: list[str | None] = list(split_rooms(entry.get("room"))) or [None]
        staff = split_staff(entry.get("staff"))
        weeks_raw = entry.get("weeks")

        for code in courses:
            for room in rooms:
                records.append(
                    SessionRecord(
                        course_code=code,
                        day=day,
                        start_min=start,
                        end_min=end,
                        room_code=room,
                        activity_type=entry.get("type"),
                        stream_label=entry.get("group_label"),
                        weeks_raw=weeks_raw,
                        weeks=expand_weeks(weeks_raw),
                        week_count=entry.get("week_count"),
                        semester=semester,
                        notes=entry.get("notes"),
                        raw_text=entry.get("raw_text"),
                        staff=list(staff),
                        sources={source},
                    )
                )
    return records


def merge_records(records: Iterable[SessionRecord]) -> list[SessionRecord]:
    """
    Collapse descriptions of the same class into one record.

    Runs in two passes. The first merges exact identities, unioning staff and
    provenance. The second lets a record with no room adopt one from another
    source, but only when exactly one candidate matches - an ambiguous match
    would risk inventing a room the class never had.
    """
    merged: dict[tuple, SessionRecord] = {}

    for record in records:
        existing = merged.get(record.identity)
        if existing is None:
            merged[record.identity] = record
        else:
            existing.absorb(record)

    # -- Second pass: fold partial descriptions into their fuller sibling --
    # A record missing a room or a stream marker is absorbed by the one that
    # has them, but only when exactly one sibling is compatible. With two
    # candidates the record could belong to either, and guessing would invent
    # a fact - so it stays as its own row.
    by_core: dict[tuple, list[SessionRecord]] = {}
    for record in merged.values():
        by_core.setdefault(record.core_identity, []).append(record)

    for identity, record in list(merged.items()):
        if record.room_code and record.stream_label:
            continue  # already fully specified
        candidates = [
            other
            for other in by_core.get(record.core_identity, [])
            if other is not record and record.compatible_with(other)
        ]
        if len(candidates) != 1:
            continue
        candidates[0].absorb(record)
        by_core[record.core_identity].remove(record)
        del merged[identity]

    return sorted(
        merged.values(),
        key=lambda r: (
            r.course_code,
            DAY_ORDER.index(r.day),
            r.start_min,
            r.room_code or "",
        ),
    )
