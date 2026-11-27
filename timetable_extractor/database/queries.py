"""
Ready-made queries over the timetable warehouse.

Each is a plain function returning rows, so they can back an API endpoint, a
CLI, or ad-hoc analysis. Each reads one term's current publication, named by
the caller (`terms.py`); the CLI passes the default term unless `--term`
names another.
"""

from __future__ import annotations

from typing import Any

import psycopg

from timetable_extractor.database.courses import find_published_code
from timetable_extractor.database.terms import (
    IN_TERM,
    TERM_PUBLICATION,
    TermKey,
    in_term,
    params,
)
from timetable_extractor.database.weeks import expand_weeks


def course_timetable(
    conn: psycopg.Connection, term: TermKey, code: str
) -> list[dict[str, Any]]:
    """
    Every session for a course, in week order.

    The code is resolved rather than upper-cased, because upper-casing alone
    finds nothing for "COMP2601", which is how the README spells the command.
    """
    with conn.cursor() as cur:
        published = find_published_code(cur, code)
        if published is None:
            return []

        cur.execute(
            f"""
            SELECT day, start_time, end_time, activity_type, stream_label,
                   room, staff, weeks_raw, notes
              FROM term_sessions
             WHERE {IN_TERM} AND course_code = %(code)s
             ORDER BY day, start_min
            """,
            params(term, code=published),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def free_rooms(
    conn: psycopg.Connection,
    term: TermKey,
    day: str,
    start_min: int,
    end_min: int,
    week: int | None = None,
) -> list[str]:
    """
    Rooms with nothing booked over a time range.

    A room is free if no session overlaps the window. When `week` is given,
    bookings in other teaching weeks are ignored - a room booked only in W8 is
    free in W3.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT r.code
              FROM rooms r
             WHERE NOT EXISTS (
                   SELECT 1
                     FROM sessions s
                    WHERE s.room_id = r.id
                      AND s.publication_id = {TERM_PUBLICATION}
                      AND s.day = %(day)s::day_of_week
                      AND s.start_min < %(end)s
                      AND s.end_min   > %(start)s
                      AND (%(week)s::smallint IS NULL OR %(week)s::smallint = ANY (s.weeks))
             )
             ORDER BY r.code
            """,
            params(term, day=day, start=start_min, end=end_min, week=week),
        )
        return [row[0] for row in cur.fetchall()]


def room_occupancy(
    conn: psycopg.Connection, term: TermKey, room_code: str
) -> list[dict[str, Any]]:
    """What is booked in a room, across every course."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT day, start_time, end_time, course_code, activity_type, weeks_raw, staff
              FROM term_sessions
             WHERE {IN_TERM} AND room = %(room)s
             ORDER BY day, start_min
            """,
            params(term, room=room_code),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def staff_load(
    conn: psycopg.Connection, term: TermKey, limit: int = 20
) -> list[dict[str, Any]]:
    """Contact hours per teacher, weighted by how many weeks each class runs."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT st.name,
                   count(*)                                        AS sessions,
                   count(DISTINCT s.course_id)                     AS courses,
                   round(sum((s.end_min - s.start_min) / 60.0), 1) AS hours_per_week,
                   round(sum((s.end_min - s.start_min) / 60.0
                             * COALESCE(array_length(s.weeks, 1), 1)), 1) AS total_hours
              FROM sessions s
              JOIN session_staff ss ON ss.session_id = s.id
              JOIN staff st         ON st.id = ss.staff_id
             WHERE s.publication_id = {TERM_PUBLICATION}
             GROUP BY st.name
             ORDER BY total_hours DESC
             LIMIT %(limit)s
            """,
            params(term, limit=limit),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def clashes(
    conn: psycopg.Connection, term: TermKey, codes: list[str]
) -> list[dict[str, Any]]:
    """
    Genuine clashes among a set of courses.

    Two sessions only clash if they overlap in time *and* share a teaching
    week, which is why the expanded `weeks` array matters: a class in W1-W7
    and one in W9-W12 look identical on a calendar but never collide.
    """
    if not codes:
        return []

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT a.course_code, a.activity_type, a.stream_label, a.day,
                   a.start_time, a.end_time, a.room,
                   b.course_code, b.activity_type, b.stream_label,
                   b.start_time, b.end_time, b.room,
                   ARRAY(SELECT unnest(a.weeks) INTERSECT SELECT unnest(b.weeks)
                         ORDER BY 1) AS shared_weeks
              FROM term_sessions a
              JOIN term_sessions b
                ON a.publication_id = b.publication_id
               AND a.day = b.day
               AND a.id < b.id
               AND a.course_code <> b.course_code
               AND a.start_min < b.end_min
               AND b.start_min < a.end_min
             WHERE {in_term("a")}
               AND a.course_code = ANY(%(codes)s)
               AND b.course_code = ANY(%(codes)s)
               AND a.weeks && b.weeks
             ORDER BY a.day, a.start_min
            """,
            params(term, codes=[c.upper() for c in codes]),
        )
        columns = [
            "course_a", "type_a", "stream_a", "day", "start_a", "end_a", "room_a",
            "course_b", "type_b", "stream_b", "start_b", "end_b", "room_b",
            "shared_weeks",
        ]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def busiest_hours(conn: psycopg.Connection, term: TermKey) -> list[dict[str, Any]]:
    """Sessions per weekday hour - where the timetable is most congested."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT day, start_min / 60 AS hour, count(*) AS sessions
              FROM sessions
             WHERE publication_id = {TERM_PUBLICATION}
             GROUP BY day, hour
             ORDER BY sessions DESC
             LIMIT 15
            """,
            params(term),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def coverage_summary(conn: psycopg.Connection, term: TermKey) -> dict[str, Any]:
    """Row counts and field coverage for the term's current publication."""
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT count(*)                                              AS sessions,
                   count(DISTINCT course_id)                             AS courses,
                   count(room_id)                                        AS with_room,
                   count(*) FILTER (WHERE stream_label IS NOT NULL)      AS with_stream,
                   count(*) FILTER (WHERE notes IS NOT NULL)             AS with_notes,
                   count(*) FILTER (WHERE cardinality(weeks) > 0)        AS with_weeks
              FROM sessions
             WHERE publication_id = {TERM_PUBLICATION}
            """,
            params(term),
        )
        row = cur.fetchone()
        summary = dict(zip([c.name for c in cur.description], row or ()))

        cur.execute(
            f"""
            SELECT count(DISTINCT session_id)
              FROM session_staff
             WHERE session_id IN (
                   SELECT id FROM sessions
                    WHERE publication_id = {TERM_PUBLICATION})
            """,
            params(term),
        )
        summary["with_staff"] = (cur.fetchone() or [0])[0]

        cur.execute(
            """
            SELECT count(*) FROM (
                SELECT session_id FROM session_sources
                 GROUP BY session_id HAVING count(*) > 1
            ) t
            """
        )
        summary["confirmed_by_multiple_pdfs"] = (cur.fetchone() or [0])[0]

    return summary


__all__ = [
    "course_timetable",
    "free_rooms",
    "room_occupancy",
    "staff_load",
    "clashes",
    "busiest_hours",
    "coverage_summary",
    "expand_weeks",
]
