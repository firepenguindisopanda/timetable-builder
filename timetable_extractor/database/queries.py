"""
Ready-made queries over the timetable warehouse.

Each is a plain function returning rows, so they can back an API endpoint, a
CLI, or ad-hoc analysis. They all read `current_sessions`, the view scoped to
the most recent publication.
"""

from __future__ import annotations

from typing import Any

import psycopg

from timetable_extractor.database.courses import find_published_code
from timetable_extractor.database.weeks import expand_weeks


def course_timetable(conn: psycopg.Connection, code: str) -> list[dict[str, Any]]:
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
            """
            SELECT day, start_time, end_time, activity_type, stream_label,
                   room, staff, weeks_raw, notes
              FROM current_sessions
             WHERE course_code = %s
             ORDER BY day, start_min
            """,
            (published,),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def free_rooms(
    conn: psycopg.Connection, day: str, start_min: int, end_min: int, week: int | None = None
) -> list[str]:
    """
    Rooms with nothing booked over a time range.

    A room is free if no session overlaps the window. When `week` is given,
    bookings in other teaching weeks are ignored - a room booked only in W8 is
    free in W3.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.code
              FROM rooms r
             WHERE NOT EXISTS (
                   SELECT 1
                     FROM sessions s
                    WHERE s.room_id = r.id
                      AND s.publication_id = (SELECT id FROM latest_publication)
                      AND s.day = %s::day_of_week
                      AND s.start_min < %s
                      AND s.end_min   > %s
                      AND (%s::smallint IS NULL OR %s::smallint = ANY (s.weeks))
             )
             ORDER BY r.code
            """,
            (day, end_min, start_min, week, week),
        )
        return [row[0] for row in cur.fetchall()]


def room_occupancy(conn: psycopg.Connection, room_code: str) -> list[dict[str, Any]]:
    """What is booked in a room, across every course."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT day, start_time, end_time, course_code, activity_type, weeks_raw, staff
              FROM current_sessions
             WHERE room = %s
             ORDER BY day, start_min
            """,
            (room_code,),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def staff_load(conn: psycopg.Connection, limit: int = 20) -> list[dict[str, Any]]:
    """Contact hours per teacher, weighted by how many weeks each class runs."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT st.name,
                   count(*)                                        AS sessions,
                   count(DISTINCT s.course_id)                     AS courses,
                   round(sum((s.end_min - s.start_min) / 60.0), 1) AS hours_per_week,
                   round(sum((s.end_min - s.start_min) / 60.0
                             * COALESCE(array_length(s.weeks, 1), 1)), 1) AS total_hours
              FROM sessions s
              JOIN session_staff ss ON ss.session_id = s.id
              JOIN staff st         ON st.id = ss.staff_id
             WHERE s.publication_id = (SELECT id FROM latest_publication)
             GROUP BY st.name
             ORDER BY total_hours DESC
             LIMIT %s
            """,
            (limit,),
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def clashes(conn: psycopg.Connection, codes: list[str]) -> list[dict[str, Any]]:
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
            """
            SELECT a.course_code, a.activity_type, a.stream_label, a.day,
                   a.start_time, a.end_time, a.room,
                   b.course_code, b.activity_type, b.stream_label,
                   b.start_time, b.end_time, b.room,
                   ARRAY(SELECT unnest(a.weeks) INTERSECT SELECT unnest(b.weeks)
                         ORDER BY 1) AS shared_weeks
              FROM current_sessions a
              JOIN current_sessions b
                ON a.day = b.day
               AND a.id < b.id
               AND a.course_code <> b.course_code
               AND a.start_min < b.end_min
               AND b.start_min < a.end_min
             WHERE a.course_code = ANY(%s)
               AND b.course_code = ANY(%s)
               AND a.weeks && b.weeks
             ORDER BY a.day, a.start_min
            """,
            ([c.upper() for c in codes], [c.upper() for c in codes]),
        )
        columns = [
            "course_a", "type_a", "stream_a", "day", "start_a", "end_a", "room_a",
            "course_b", "type_b", "stream_b", "start_b", "end_b", "room_b",
            "shared_weeks",
        ]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def busiest_hours(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Sessions per weekday hour - where the timetable is most congested."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT day, start_min / 60 AS hour, count(*) AS sessions
              FROM sessions
             WHERE publication_id = (SELECT id FROM latest_publication)
             GROUP BY day, hour
             ORDER BY sessions DESC
             LIMIT 15
            """
        )
        return [
            dict(zip([c.name for c in cur.description], row)) for row in cur.fetchall()
        ]


def coverage_summary(conn: psycopg.Connection) -> dict[str, Any]:
    """Row counts and field coverage for the current publication."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)                                              AS sessions,
                   count(DISTINCT course_id)                             AS courses,
                   count(room_id)                                        AS with_room,
                   count(*) FILTER (WHERE stream_label IS NOT NULL)      AS with_stream,
                   count(*) FILTER (WHERE notes IS NOT NULL)             AS with_notes,
                   count(*) FILTER (WHERE cardinality(weeks) > 0)        AS with_weeks
              FROM sessions
             WHERE publication_id = (SELECT id FROM latest_publication)
            """
        )
        row = cur.fetchone()
        summary = dict(zip([c.name for c in cur.description], row or ()))

        cur.execute(
            """
            SELECT count(DISTINCT session_id)
              FROM session_staff
             WHERE session_id IN (
                   SELECT id FROM sessions
                    WHERE publication_id = (SELECT id FROM latest_publication))
            """
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
