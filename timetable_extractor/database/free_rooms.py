"""
Rooms with nothing timetabled in a window: somewhere to study between classes.

`queries.free_rooms` answered this for the CLI and was wrong for students in
three ways, each of which this module exists to fix:

* It listed every room ever seen, including "Remote Teaching" and "Venue to
  be advised", which are not places anyone can sit.
* It listed rooms that have no room timetable of their own. A room only named
  in course PDFs is busy whenever a course we happen to hold says so, and
  free otherwise, which is not the same as free. Only a room in the registry
  has its own PDF, and so a complete list of its bookings.
* It listed registry rooms nobody timetables at all, such as the ENG
  Undercroft and the Pan Theatre. A room UWI never books a class in is not one we can vouch for.

A registry room's code and its bookings' room can differ in spacing: the
registry writes "FHE CLL  Room  9" and the sessions "FHE CLL Room 9". Matching
on the exact code dropped 22 rooms, most of them the Centre for Language
Learning's, so codes are compared with their whitespace collapsed.

Free here means *not timetabled*, never *open*: the page says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

import psycopg

from timetable_extractor.database.changes import is_placeholder_room

#: Buildings by the start of a room code, longest first so "UWI Couva" wins
#: over a bare "UWI". The short codes mirror `MY_WEEK_BUILDINGS` in
#: assets/js/my-week.js, which uses the same labels for back-to-back warnings;
#: tests/test_free_rooms.py holds the two together. Off-campus rooms are kept
#: apart, because a student between classes cannot walk to Couva.
BUILDINGS: tuple[tuple[str, str, bool], ...] = (
    ("UWI Couva", "Couva Teaching Facility (off campus)", False),
    ("UWI SPEC", "Sport and Physical Education Centre", True),
    ("DAAGA", "Daaga Auditorium", True),
    ("IGDS", "IGDS", True),
    ("FHE", "Humanities & Education", True),
    ("FST", "Science & Technology", True),
    ("ENG", "Engineering", True),
    ("TLC", "Teaching & Learning Complex", True),
    ("FSS", "Social Sciences", True),
    ("FFA", "Food & Agriculture", True),
    ("TCB", "TCB", True),
    ("LRC", "Learning Resource Centre", True),
    ("JFK", "JFK Quad", True),
    ("LAW", "Law", True),
)

#: Where a room whose code names no building is listed.
OTHER_BUILDING = "Other rooms"


def normalise_room(code: str | None) -> str:
    return re.sub(r"\s+", " ", code or "").strip()


def building_of(code: str) -> tuple[str, bool]:
    """The building's label and whether it is on the St. Augustine campus."""
    upper = normalise_room(code).upper()
    for prefix, label, on_campus in BUILDINGS:
        p = prefix.upper()
        if upper == p or upper.startswith(p + " "):
            return label, on_campus
    return OTHER_BUILDING, True


def is_study_space(code: str | None) -> bool:
    """Not a placeholder and not remote teaching: somewhere a person can sit."""
    if is_placeholder_room(code):
        return False
    return not normalise_room(code).lower().startswith("remote")


@dataclass(frozen=True)
class FreeRoom:
    code: str
    building: str
    on_campus: bool
    #: Minutes from midnight of the room's next booking that day, or None
    #: when nothing else is timetabled in it that day.
    free_until: int | None


def free_in_window(
    rooms: Iterable[str],
    bookings: Iterable[tuple[str, int, int]],
    start_min: int,
    end_min: int,
) -> list[FreeRoom]:
    """
    The rooms with no booking overlapping [start, end), and until when.

    Pure, so the overlap rule is tested without a database. `bookings` are
    (room, start, end) for one day of one teaching week.
    """
    by_room: dict[str, list[tuple[int, int]]] = {}
    for room, start, end in bookings:
        by_room.setdefault(normalise_room(room), []).append((start, end))

    free = []
    for code in sorted({normalise_room(r) for r in rooms}):
        booked = by_room.get(code, [])
        if any(start < end_min and end > start_min for start, end in booked):
            continue
        later = [start for start, _ in booked if start >= end_min]
        label, on_campus = building_of(code)
        free.append(FreeRoom(code, label, on_campus, min(later) if later else None))
    return free


def group_by_building(free: Iterable[FreeRoom]) -> list[tuple[str, list[FreeRoom]]]:
    """Campus buildings by name, then rooms with no building, then off campus."""
    groups: dict[str, list[FreeRoom]] = {}
    for room in free:
        groups.setdefault(room.building, []).append(room)

    def order(item: tuple[str, list[FreeRoom]]) -> tuple[int, str]:
        label, rooms = item
        if not rooms[0].on_campus:
            return (2, label)
        return (1 if label == OTHER_BUILDING else 0, label)

    return sorted(groups.items(), key=order)


def study_rooms(conn: psycopg.Connection) -> list[str]:
    """
    Registry rooms with at least one class this publication, codes as the
    bookings spell them.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT cs.room
              FROM current_sessions cs
             WHERE cs.room IS NOT NULL
               AND regexp_replace(cs.room, '\\s+', ' ', 'g') IN (
                   SELECT regexp_replace(r.code, '\\s+', ' ', 'g')
                     FROM rooms r
                     JOIN resources res ON res.id = r.resource_id
                    WHERE res.kind = 'room'
                      AND res.last_seen_publication = (SELECT id FROM latest_publication)
               )
            """
        )
        return [row[0] for row in cur.fetchall() if is_study_space(row[0])]


def day_bookings(
    conn: psycopg.Connection, day: str, week: int
) -> list[tuple[str, int, int]]:
    """Every booking on one day of one teaching week, room by room."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT room, start_min, end_min
              FROM current_sessions
             WHERE room IS NOT NULL
               AND day = %s::day_of_week
               AND %s::smallint = ANY (weeks)
            """,
            (day, week),
        )
        return [(row[0], row[1], row[2]) for row in cur.fetchall()]


def free_rooms_page(
    conn: psycopg.Connection, day: str, week: int
) -> dict[str, Any]:
    """What the page needs for one day and week; the window is applied later."""
    return {"rooms": study_rooms(conn), "bookings": day_bookings(conn, day, week)}


# The window asked about

#: Teaching runs from 8am; nobody hunts for a free room at 3am.
EARLIEST_MIN = 8 * 60
LATEST_MIN = 21 * 60

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


@dataclass(frozen=True)
class Window:
    day: str
    start_min: int
    end_min: int
    week: int


def parse_clock(text: str | None) -> int | None:
    """ "14:00" to minutes, or None for anything that is not a time of day."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", (text or "").strip())
    if not match:
        return None
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        return None
    return hours * 60 + minutes


def default_window(now: Any, week_one: Any, total_weeks: int) -> Window:
    """
    The hour starting now, on today's teaching week, as the page opens.

    Evenings roll to 8am the next day and Sunday to Monday, so the first
    thing a student sees is a window worth asking about. Before term starts
    it is week 1; after it ends, the last week.
    """
    day = now.date()
    start = max(EARLIEST_MIN, now.hour * 60)
    if start >= LATEST_MIN - 60:
        day = day.fromordinal(day.toordinal() + 1)
        start = EARLIEST_MIN
    if day.weekday() == 6:
        day = day.fromordinal(day.toordinal() + 1)
        start = EARLIEST_MIN
    week = 1
    if week_one is not None:
        week = (day - week_one).days // 7 + 1
    week = min(max(week, 1), total_weeks)
    return Window(DAYS[day.weekday()], start, start + 60, week)


def window_from(
    default: Window,
    total_weeks: int,
    day: str | None = None,
    start: str | None = None,
    end: str | None = None,
    week: str | None = None,
) -> tuple[Window, bool]:
    """
    The window a query string asks for, and whether any of it was refused.

    A value that does not parse falls back to the default rather than
    erroring: this is a form, and the student should see rooms, with a line
    saying what was ignored.
    """
    refused = False
    chosen_day = default.day
    if day:
        match = next((d for d in DAYS if d.lower() == day.strip().lower()), None)
        refused |= match is None
        chosen_day = match or default.day

    start_min, end_min = default.start_min, default.end_min
    if start or end:
        s, e = parse_clock(start), parse_clock(end)
        if s is not None and e is not None and e > s:
            start_min, end_min = s, e
        elif s is not None and not end:
            start_min, end_min = s, s + 60
        else:
            refused = True

    chosen_week = default.week
    if week:
        if week.strip().isdigit() and 1 <= int(week) <= total_weeks:
            chosen_week = int(week)
        else:
            refused = True
    return Window(chosen_day, start_min, end_min, chosen_week), refused
