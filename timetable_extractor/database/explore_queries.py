"""
Read-only queries backing the public timetable explorer.

Everything here reads `current_sessions` (the latest publication) and never
writes. The explorer is the student-facing view of the warehouse, so these
queries are shaped for display rather than analysis: they pre-join names,
pre-format times, and collapse the 12 teaching weeks into a bitmask that the
front end can render as a week meter without shipping 12 booleans per row.

On the week bitmask: `weeks` in the database is SMALLINT[] holding week numbers
1-12. On the wire that becomes a single integer where bit 0 is week 1, so
"W1-W7, W9-W12" is 0b111101111111. It keeps the course index payload small and
makes "does this run in week 8" a bit test in JavaScript.
"""

from __future__ import annotations

from typing import Any

import psycopg

# Course-code matching lives with the rest of the course-code handling. It is
# re-exported below because the explorer and the timetable API both reach for
# it through this module.
from timetable_extractor.database.courses import (
    build_code_index,
    normalise_course_code,
    published_code_candidates,
    resolve_published_code,
)

# The teaching semester CELCAT publishes: weeks 1 through 12.
TOTAL_WEEKS = 12

# Declaration order of the day_of_week enum, so Monday sorts first.
DAY_ORDER = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]

# Earliest and latest hour any class starts or ends, from the corpus. Used to
# bound the campus heat grid so it does not render 24 mostly-empty rows.
DAY_START_HOUR = 8
DAY_END_HOUR = 20


def weeks_to_mask(weeks: list[int] | None) -> int:
    """Pack week numbers into a bitmask; bit 0 is week 1."""
    if not weeks:
        return 0
    mask = 0
    for week in weeks:
        if 1 <= week <= TOTAL_WEEKS:
            mask |= 1 << (week - 1)
    return mask


def week_layout(sessions: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Turn a list of sessions into a positioned week grid.

    Two things a naive hour-per-cell grid gets wrong, both of which matter on a
    timetable: a four-hour lab has to *look* four hours long, and parallel
    streams in different rooms have to sit side by side rather than on top of
    one another. So each session is given a vertical offset and height in
    minutes, and overlapping sessions are packed into lanes across the width of
    their day.
    """
    if not sessions:
        return {"days": [], "hours": [], "first_min": 0, "total_min": 0}

    first_min = min(s["start_min"] for s in sessions) // 60 * 60
    last_min = -(-max(s["end_min"] for s in sessions) // 60) * 60

    days = []
    for day in DAY_ORDER:
        in_day = sorted(
            (s for s in sessions if s["day"] == day),
            key=lambda s: (s["start_min"], s["end_min"]),
        )
        if not in_day:
            continue

        # Width is decided per cluster of overlapping classes, not per day.
        # Otherwise one crowded hour - five parallel lectures at 16:00 - would
        # narrow every other class that day down with it.
        placed: list[dict[str, Any]] = []
        cluster: list[dict[str, Any]] = []
        lane_ends: list[int] = []
        cluster_end = -1
        widest = 1

        def close_cluster() -> None:
            nonlocal widest
            if not cluster:
                return
            lanes = len(lane_ends)
            widest = max(widest, lanes)
            for entry in cluster:
                entry["left_pct"] = round(entry["lane"] * 100 / lanes, 4)
                entry["width_pct"] = round(100 / lanes, 4)
            placed.extend(cluster)

        for session in in_day:
            if session["start_min"] >= cluster_end:
                close_cluster()
                cluster, lane_ends, cluster_end = [], [], -1

            lane = next(
                (i for i, end in enumerate(lane_ends) if end <= session["start_min"]),
                len(lane_ends),
            )
            if lane == len(lane_ends):
                lane_ends.append(session["end_min"])
            else:
                lane_ends[lane] = session["end_min"]

            cluster.append(
                {
                    "session": session,
                    "lane": lane,
                    "top_min": session["start_min"] - first_min,
                    "height_min": session["end_min"] - session["start_min"],
                }
            )
            cluster_end = max(cluster_end, session["end_min"])

        close_cluster()
        days.append({"day": day, "lanes": widest, "blocks": placed})

    return {
        "days": days,
        "hours": list(range(first_min // 60, last_min // 60)),
        "first_min": first_min,
        "total_min": last_min - first_min,
    }


def course_codes(conn: psycopg.Connection) -> list[str]:
    """Every course code in the current publication, as published."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT course_code
              FROM current_sessions
             ORDER BY course_code
            """
        )
        return [row[0] for row in cur.fetchall()]


def _rows(cur: psycopg.Cursor) -> list[dict[str, Any]]:
    """Cursor rows as dicts, using the column names the query declared."""
    columns = [c.name for c in cur.description or ()]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


# Provenance


def freshness(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Everything needed to tell a student whether the timetable is current.

    Three timestamps matter and they mean different things:

    * `published_at`  - when UWI last republished the timetable
    * `imported_at`   - when we last loaded that publication into the warehouse
    * `checked_at`    - when we last asked the server whether anything changed

    A page that shows only the first cannot distinguish "UWI has not changed
    it" from "we stopped looking three weeks ago", which is exactly the failure
    a freshness indicator exists to prevent.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, published_at, http_last_modified,
                   discovered_at AS imported_at, resource_count
              FROM latest_publication
            """
        )
        publication = (_rows(cur) or [{}])[0]

        cur.execute(
            """
            SELECT started_at AS checked_at, index_changed, publication_id,
                   pdfs_changed, note
              FROM sync_runs
             ORDER BY started_at DESC
             LIMIT 1
            """
        )
        last_check = (_rows(cur) or [{}])[0]

        cur.execute("SELECT count(*) FROM sync_runs")
        check_count = (cur.fetchone() or [0])[0]

        cur.execute("SELECT count(*) FROM publications")
        publication_count = (cur.fetchone() or [0])[0]

    # A check that saw a new index but did not attach a publication means the
    # site changed and we have not pulled it yet. Worth saying out loud: the
    # data on screen is provably behind.
    update_pending = bool(
        last_check.get("index_changed")
        and last_check.get("publication_id") != publication.get("id")
    )

    return {
        # The builder saves this alongside a student's timetable so it can tell
        # them the warehouse moved underneath it rather than silently serving
        # last semester's rooms.
        "publication_id": publication.get("id"),
        "published_at": publication.get("published_at"),
        "http_last_modified": publication.get("http_last_modified"),
        "imported_at": publication.get("imported_at"),
        "resource_count": publication.get("resource_count") or 0,
        "checked_at": last_check.get("checked_at"),
        "update_pending": update_pending,
        "check_count": check_count,
        "publication_count": publication_count,
    }


def overview(conn: psycopg.Connection) -> dict[str, Any]:
    """Headline counts for the current publication."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)                                    AS sessions,
                   count(DISTINCT course_code)                 AS courses,
                   count(DISTINCT room)  FILTER (WHERE room IS NOT NULL)
                                                               AS rooms,
                   count(DISTINCT faculty) FILTER (WHERE faculty IS NOT NULL)
                                                               AS faculties,
                   count(DISTINCT department) FILTER (WHERE department IS NOT NULL)
                                                               AS departments
              FROM current_sessions
            """
        )
        stats = (_rows(cur) or [{}])[0]

        cur.execute(
            """
            SELECT count(DISTINCT st.name)
              FROM session_staff ss
              JOIN staff st ON st.id = ss.staff_id
              JOIN sessions s ON s.id = ss.session_id
             WHERE s.publication_id = (SELECT id FROM latest_publication)
            """
        )
        stats["staff"] = (cur.fetchone() or [0])[0]

        # How many sessions more than one PDF agreed on. The merge across
        # course, room and staff timetables is what makes this dataset richer
        # than any single view of it, so it is worth surfacing.
        cur.execute(
            """
            SELECT count(*) FROM (
                SELECT ss.session_id
                  FROM session_sources ss
                  JOIN sessions s ON s.id = ss.session_id
                 WHERE s.publication_id = (SELECT id FROM latest_publication)
                 GROUP BY ss.session_id
                HAVING count(*) > 1
            ) t
            """
        )
        stats["cross_confirmed"] = (cur.fetchone() or [0])[0]

    return stats


#: A weekday carrying this many times the median weekday's classes is not a
#: busy Tuesday, it is a parsing fault. Calibrated against the "deW" bug, where
#: unrecognised Wednesday labels pushed that day's classes onto Tuesday and
#: produced a ratio of 2.3.
DAY_SKEW_THRESHOLD = 1.8


def day_distribution(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Classes per weekday, with a skew check.

    This is the cheapest possible smoke test for the failure mode that hurt
    most: a day label the parser does not recognise leaves no row for that day,
    and every class in it silently lands on the day above. The counts stay
    plausible per-PDF and only the corpus-wide histogram gives it away.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT day::text AS day, count(*) AS sessions
              FROM current_sessions
             GROUP BY day
             ORDER BY day
            """
        )
        counts = {r["day"]: r["sessions"] for r in _rows(cur)}

    weekdays = DAY_ORDER[:5]
    weekday_counts = sorted(counts.get(d, 0) for d in weekdays)
    median = weekday_counts[len(weekday_counts) // 2] if weekday_counts else 0

    busiest = max(weekdays, key=lambda d: counts.get(d, 0), default=None)
    quietest = min(weekdays, key=lambda d: counts.get(d, 0), default=None)
    ratio = round(counts.get(busiest, 0) / median, 2) if median else None

    return {
        "counts": {day: counts.get(day, 0) for day in DAY_ORDER},
        "weekday_median": median,
        "busiest_weekday": busiest,
        "quietest_weekday": quietest,
        "skew_ratio": ratio,
        "skewed": bool(ratio and ratio > DAY_SKEW_THRESHOLD),
    }


def campus_heat(conn: psycopg.Connection) -> dict[str, Any]:
    """
    Sessions per weekday hour across the whole campus.

    Returned as a dense day x hour matrix so the front end can render it
    without filling gaps itself. A slot counts a session if the session is
    running at any point during that hour.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT day::text AS day, h AS hour, count(*) AS sessions
              FROM current_sessions,
                   generate_series(start_min / 60, (end_min - 1) / 60) AS h
             WHERE h BETWEEN %s AND %s
             GROUP BY day, h
            """,
            (DAY_START_HOUR, DAY_END_HOUR),
        )
        counts = {(r["day"], r["hour"]): r["sessions"] for r in _rows(cur)}

    hours = list(range(DAY_START_HOUR, DAY_END_HOUR + 1))
    matrix = [[counts.get((day, hour), 0) for hour in hours] for day in DAY_ORDER]
    peak = max((max(row) for row in matrix if row), default=0)

    # Five discrete bands rather than a continuous ramp, so a reader can
    # compare two slots by eye instead of guessing at a gradient.
    def level(value: int) -> int:
        if not value or not peak:
            return 0
        return max(1, min(5, -(-value * 5 // peak)))

    rows = [
        {
            "day": day,
            "cells": [
                {"hour": hour, "count": count, "level": level(count)}
                for hour, count in zip(hours, row)
            ],
        }
        for day, row in zip(DAY_ORDER, matrix)
    ]

    return {"days": DAY_ORDER, "hours": hours, "rows": rows, "peak": peak}


# Course index and detail


def course_index(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Every course with the aggregates the explorer filters and searches on.

    The whole index is small enough (about 1,100 rows) to ship to the browser
    once, which is why searching and filtering the list needs no server round
    trip. Rooms and staff are included so one search box can match a course
    code, a room, or a lecturer's name.
    """
    publication = "(SELECT id FROM latest_publication)"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.code,
                   c.title,
                   f.name AS faculty,
                   d.name AS department,
                   count(s.id)                                   AS sessions,
                   array_agg(DISTINCT s.day::text)               AS days,
                   array_remove(array_agg(DISTINCT s.activity_type), NULL)
                                                                 AS types,
                   array_remove(array_agg(DISTINCT r.code), NULL) AS rooms,
                   min(s.start_min)                              AS first_start,
                   max(s.end_min)                                AS last_end,
                   COALESCE((
                       SELECT array_agg(DISTINCT w ORDER BY w)
                         FROM sessions sw, unnest(sw.weeks) AS w
                        WHERE sw.course_id = c.id
                          AND sw.publication_id = {publication}
                   ), '{{}}')                                    AS weeks,
                   COALESCE((
                       SELECT array_agg(DISTINCT st.name ORDER BY st.name)
                         FROM sessions ss2
                         JOIN session_staff sst ON sst.session_id = ss2.id
                         JOIN staff st         ON st.id = sst.staff_id
                        WHERE ss2.course_id = c.id
                          AND ss2.publication_id = {publication}
                   ), '{{}}')                                    AS staff,
                   -- Every (day, hour) the course occupies, packed as
                   -- day_index * 24 + hour. Lets the campus heat grid filter
                   -- to an exact slot without a second request.
                   COALESCE((
                       SELECT array_agg(DISTINCT
                                  (array_position(enum_range(NULL::day_of_week),
                                                  s3.day) - 1) * 24 + h)
                         FROM sessions s3,
                              generate_series(s3.start_min / 60,
                                              (s3.end_min - 1) / 60) AS h
                        WHERE s3.course_id = c.id
                          AND s3.publication_id = {publication}
                   ), '{{}}')                                    AS slots
              FROM courses c
              JOIN sessions s        ON s.course_id = c.id
                                    AND s.publication_id = {publication}
              LEFT JOIN rooms r      ON r.id = s.room_id
              LEFT JOIN departments d ON d.id = c.department_id
              LEFT JOIN faculties f   ON f.id = c.faculty_id
             GROUP BY c.id, c.code, c.title, f.name, d.name
             ORDER BY c.code
            """
        )
        courses = _rows(cur)

    for course in courses:
        course["weeks"] = weeks_to_mask(course.pop("weeks"))
        # Keep days in timetable order rather than the arbitrary order
        # array_agg(DISTINCT ...) produces.
        course["days"] = [d for d in DAY_ORDER if d in (course["days"] or [])]
    return courses


def course_detail(conn: psycopg.Connection, code: str) -> dict[str, Any] | None:
    """A course, its sessions, and who teaches them."""
    with conn.cursor() as cur:
        # Resolved rather than normalised: normalising alone 404s "WW101" and
        # "FOUN 1001 (FULL & PART-TIME)", which are published courses. The
        # match is folded into this query rather than done by
        # `find_published_code` first, so a course page still costs two round
        # trips and not three.
        course = None
        for key in published_code_candidates(code):
            cur.execute(
                """
                SELECT c.code, c.title, f.name AS faculty, d.name AS department
                  FROM courses c
                  LEFT JOIN departments d ON d.id = c.department_id
                  LEFT JOIN faculties f   ON f.id = c.faculty_id
                 WHERE upper(regexp_replace(c.code, '\\s', '', 'g')) = %s
                 ORDER BY c.code
                 LIMIT 1
                """,
                (key,),
            )
            course = (_rows(cur) or [None])[0]
            if course is not None:
                break
        if course is None:
            return None
        code = course["code"]

        cur.execute(
            """
            SELECT id, day::text AS day, start_time, end_time,
                   start_min, end_min, activity_type, stream_label,
                   room, staff, weeks, weeks_raw, notes, source_count
              FROM current_sessions
             WHERE course_code = %s
             ORDER BY day, start_min, end_min
            """,
            (code,),
        )
        sessions = _rows(cur)

    for session in sessions:
        session["weeks_mask"] = weeks_to_mask(session["weeks"])
        session["staff"] = list(session["staff"] or [])

    course["sessions"] = sessions
    course["weeks_mask"] = weeks_to_mask(
        sorted({w for s in sessions for w in (s["weeks"] or [])})
    )
    course["rooms"] = sorted({s["room"] for s in sessions if s["room"]})
    course["staff"] = sorted({name for s in sessions for name in s["staff"]})
    course["contact_hours"] = round(
        sum((s["end_min"] - s["start_min"]) / 60 for s in sessions), 1
    )
    return course


def sessions_for_courses(
    conn: psycopg.Connection, codes: list[str]
) -> list[dict[str, Any]]:
    """
    Sessions for many courses at once, shaped for the timetable builder.

    Two queries regardless of how many codes are asked for. The builder's usual
    request is a whole semester's worth of courses at once, and a per-course
    round trip would make adding six courses six times slower than adding one
    for no reason.

    Field names are camelCase here and nowhere else in this module, because
    these rows are handed to `computeStreamId` in the browser unchanged. A
    class picked from the warehouse and the same class extracted from a PDF
    have to compute the same stream id or they become two courses.

    `codes` must already be resolved to published spellings by
    `resolve_published_code`; anything unrecognised is the caller's to report.
    """
    if not codes:
        return []

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.code, c.title, f.name AS faculty, d.name AS department
              FROM courses c
              LEFT JOIN departments d ON d.id = c.department_id
              LEFT JOIN faculties f   ON f.id = c.faculty_id
             WHERE c.code = ANY(%s)
             ORDER BY c.code
            """,
            (codes,),
        )
        courses = _rows(cur)

        cur.execute(
            """
            SELECT cs.id            AS "sessionId",
                   cs.course_code,
                   cs.activity_type AS type,
                   cs.day::text     AS day,
                   cs.start_time    AS "startTime",
                   cs.end_time      AS "endTime",
                   cs.room,
                   cs.staff,
                   cs.stream_label  AS "streamLabel",
                   cs.weeks,
                   cs.weeks_raw     AS "weeksRaw",
                   cs.source_count  AS "sourceCount"
              FROM current_sessions cs
             WHERE cs.course_code = ANY(%s)
             -- Qualified so it sorts on the day_of_week enum and lands Monday
             -- first. A bare "day" would bind to the ::text output column
             -- instead and order the week alphabetically, starting on Friday.
             ORDER BY cs.course_code, cs.day, cs.start_min, cs.end_min, cs.id
            """,
            (codes,),
        )
        rows = _rows(cur)

    by_code: dict[str, list[dict[str, Any]]] = {c["code"]: [] for c in courses}
    for row in rows:
        session = dict(row)
        code = session.pop("course_code")
        session["staff"] = list(session["staff"] or [])
        session["weeks"] = list(session["weeks"] or [])
        by_code.setdefault(code, []).append(session)

    for course in courses:
        course["sessions"] = by_code.get(course["code"], [])
    return courses


# Rooms


def room_index(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Every room that has something booked in it, with how heavily it is used."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT room                                AS code,
                   count(*)                            AS sessions,
                   count(DISTINCT course_code)         AS courses,
                   array_agg(DISTINCT day::text)       AS days,
                   round(sum((end_min - start_min) / 60.0), 1) AS hours_per_week
              FROM current_sessions
             WHERE room IS NOT NULL
             GROUP BY room
             ORDER BY room
            """
        )
        rooms = _rows(cur)

    for room in rooms:
        room["days"] = [d for d in DAY_ORDER if d in (room["days"] or [])]
    return rooms


def room_detail(conn: psycopg.Connection, code: str) -> dict[str, Any] | None:
    """What is booked in a room, across every course that uses it."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, course_code, course_title, day::text AS day,
                   start_time, end_time, start_min, end_min,
                   activity_type, stream_label, staff, weeks, weeks_raw,
                   faculty, source_count
              FROM current_sessions
             WHERE room = %s
             ORDER BY day, start_min
            """,
            (code,),
        )
        sessions = _rows(cur)

    if not sessions:
        return None

    for session in sessions:
        session["weeks_mask"] = weeks_to_mask(session["weeks"])
        session["staff"] = list(session["staff"] or [])

    return {
        "code": code,
        "sessions": sessions,
        "courses": sorted({s["course_code"] for s in sessions}),
        "hours_per_week": round(
            sum((s["end_min"] - s["start_min"]) / 60 for s in sessions), 1
        ),
        "weeks_mask": weeks_to_mask(
            sorted({w for s in sessions for w in (s["weeks"] or [])})
        ),
    }


# Staff


def staff_index(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """
    Every member of staff with a class this semester.

    Staff names come mostly from the room and staff PDFs; course PDFs usually
    omit them. This list therefore only exists because the three views were
    merged.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT st.name,
                   count(*)                                   AS sessions,
                   count(DISTINCT c.code)                     AS courses,
                   array_agg(DISTINCT s.day::text)            AS days,
                   round(sum((s.end_min - s.start_min) / 60.0), 1)
                                                              AS hours_per_week,
                   array_remove(array_agg(DISTINCT f.name), NULL) AS faculties
              FROM sessions s
              JOIN session_staff ss ON ss.session_id = s.id
              JOIN staff st         ON st.id = ss.staff_id
              JOIN courses c        ON c.id = s.course_id
              LEFT JOIN faculties f ON f.id = c.faculty_id
             WHERE s.publication_id = (SELECT id FROM latest_publication)
             GROUP BY st.name
             ORDER BY st.name
            """
        )
        people = _rows(cur)

    for person in people:
        person["days"] = [d for d in DAY_ORDER if d in (person["days"] or [])]
    return people


def staff_detail(conn: psycopg.Connection, name: str) -> dict[str, Any] | None:
    """One lecturer's teaching week."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT cs.id, cs.course_code, cs.course_title, cs.day::text AS day,
                   cs.start_time, cs.end_time, cs.start_min, cs.end_min,
                   cs.activity_type, cs.stream_label, cs.room, cs.weeks,
                   cs.weeks_raw, cs.faculty, cs.source_count
              FROM current_sessions cs
              JOIN session_staff ss ON ss.session_id = cs.id
              JOIN staff st         ON st.id = ss.staff_id
             WHERE st.name = %s
             ORDER BY cs.day, cs.start_min
            """,
            (name,),
        )
        sessions = _rows(cur)

    if not sessions:
        return None

    for session in sessions:
        session["weeks_mask"] = weeks_to_mask(session["weeks"])

    return {
        "name": name,
        "sessions": sessions,
        "courses": sorted({s["course_code"] for s in sessions}),
        "rooms": sorted({s["room"] for s in sessions if s["room"]}),
        "hours_per_week": round(
            sum((s["end_min"] - s["start_min"]) / 60 for s in sessions), 1
        ),
        "weeks_mask": weeks_to_mask(
            sorted({w for s in sessions for w in (s["weeks"] or [])})
        ),
    }


__all__ = [
    "TOTAL_WEEKS",
    "DAY_ORDER",
    "DAY_SKEW_THRESHOLD",
    "day_distribution",
    "DAY_START_HOUR",
    "DAY_END_HOUR",
    "weeks_to_mask",
    "normalise_course_code",
    "resolve_published_code",
    "build_code_index",
    "freshness",
    "overview",
    "campus_heat",
    "course_index",
    "course_codes",
    "course_detail",
    "sessions_for_courses",
    "room_index",
    "room_detail",
    "staff_index",
    "staff_detail",
]
