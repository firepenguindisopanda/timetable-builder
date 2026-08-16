"""
What changed between two publications.

A republish rewrites the whole site, so "what is different" cannot be read off
the files: it has to be diffed out of the warehouse, which keeps every
publication's sessions rather than overwriting them.

Two rules shape everything here.

**A class is identified by course, activity type and stream label, not by
where it sits.** That is the same identity the builder's option groups use
(`assets/js/option-groups.js`), so "this class moved" here and "this placement
was refilled" there are the same event and cannot disagree.

**Diffs are between two endpoints, never a replay of the hops between them.**
A class that moves Monday to Tuesday and back to Monday across two republishes
has not moved, and a student who missed both must be told so. Composing the
stored hops would report two changes instead of none, which is worse than
saying nothing at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import psycopg
from psycopg.types.json import Json

#: Rooms CELCAT publishes when it has not allocated one yet. A class going
#: from one of these to a real room has not moved; its venue was confirmed,
#: which is good news and is reported as its own kind so the page can say so.
_PLACEHOLDER_ROOM_MARKERS = ("to be advised", "not confirmed", "tba", "to be confirmed")

COURSE_ADDED = "course_added"
COURSE_DROPPED = "course_dropped"
COURSE_RENAMED = "course_renamed"
CLASS_ADDED = "class_added"
CLASS_REMOVED = "class_removed"
CLASS_MOVED = "class_moved"
CLASS_VENUE_CONFIRMED = "class_venue_confirmed"


@dataclass(frozen=True)
class Change:
    change_type: str
    course_code: str
    course_title: str | None = None
    activity_type: str | None = None
    stream_label: str | None = None
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


def _is_placeholder_room(room: str | None) -> bool:
    if not room or not room.strip():
        return True
    lowered = room.lower()
    return any(marker in lowered for marker in _PLACEHOLDER_ROOM_MARKERS)


def _minutes_to_label(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _slot(row: dict[str, Any]) -> dict[str, Any]:
    """Where a class sits, as the page will render it."""
    return {
        "day": row["day"],
        "startTime": _minutes_to_label(row["start_min"]),
        "endTime": _minutes_to_label(row["end_min"]),
        "room": row.get("room") or None,
        "weeks": row.get("weeks_raw") or None,
    }


def _slot_key(slot: dict[str, Any]) -> tuple:
    """Comparable, order-independent identity of a slot."""
    return (
        slot["day"],
        slot["startTime"],
        slot["endTime"],
        slot["room"] or "",
        slot["weeks"] or "",
    )


def _class_key(row: dict[str, Any]) -> tuple[str, str, str]:
    return (
        row["code"],
        row.get("activity_type") or "",
        row.get("stream_label") or "",
    )


def _sorted_slots(slots: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(slots, key=_slot_key)


def _is_venue_confirmation(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> bool:
    """
    One class, same day and time, a placeholder room replaced by a real one.

    Deliberately narrow. A class that changes room *and* time has moved, and
    calling that a confirmation would understate it.
    """
    if len(before) != 1 or len(after) != 1:
        return False
    b, a = before[0], after[0]
    if (b["day"], b["startTime"], b["endTime"]) != (a["day"], a["startTime"], a["endTime"]):
        return False
    return _is_placeholder_room(b["room"]) and not _is_placeholder_room(a["room"])


def diff_sessions(
    before_rows: list[dict[str, Any]], after_rows: list[dict[str, Any]]
) -> list[Change]:
    """
    The changes between two publications' session rows.

    Pure: it takes rows and returns changes, so it is tested without a
    database. Each row needs `code`, `title`, `activity_type`, `stream_label`,
    `day`, `start_min`, `end_min`, `room`, `weeks_raw` and `resource_id`.

    Output order is stable, so re-running a diff produces the same rows in the
    same order and a stored diff can be compared against a fresh one.
    """
    titles: dict[str, str | None] = {}
    resources: dict[str, Any] = {}
    for row in [*before_rows, *after_rows]:
        titles[row["code"]] = row.get("title") or titles.get(row["code"])
        if row.get("resource_id") is not None:
            resources[row["code"]] = row["resource_id"]

    before_by: dict[tuple, list[dict]] = {}
    after_by: dict[tuple, list[dict]] = {}
    for row in before_rows:
        before_by.setdefault(_class_key(row), []).append(_slot(row))
    for row in after_rows:
        after_by.setdefault(_class_key(row), []).append(_slot(row))

    before_codes = {row["code"] for row in before_rows}
    after_codes = {row["code"] for row in after_rows}

    added_codes = after_codes - before_codes
    dropped_codes = before_codes - after_codes

    # A code that disappears while its resource reappears under another code is
    # a rename, not a withdrawal plus an arrival. `EDMA 11**` became
    # `EDMA 1142` this way, and reporting it twice would alarm a student about
    # a course that never went anywhere.
    renames: list[tuple[str, str]] = []
    for old in sorted(dropped_codes):
        resource = resources.get(old)
        if resource is None:
            continue
        for new in sorted(added_codes):
            if resources.get(new) == resource:
                renames.append((old, new))
                break
    renamed_from = {old for old, _ in renames}
    renamed_to = {new for _, new in renames}

    #: Activity types a course still publishes, for deciding whether a removed
    #: class took the last of its kind with it.
    types_after: dict[str, set[str]] = {}
    for row in after_rows:
        types_after.setdefault(row["code"], set()).add(row.get("activity_type") or "")

    changes: list[Change] = []

    for old, new in renames:
        changes.append(
            Change(
                change_type=COURSE_RENAMED,
                course_code=new,
                course_title=titles.get(new),
                before={"code": old},
                after={"code": new},
            )
        )

    for code in sorted(added_codes - renamed_to):
        changes.append(
            Change(
                change_type=COURSE_ADDED,
                course_code=code,
                course_title=titles.get(code),
                after={"code": code},
            )
        )

    for code in sorted(dropped_codes - renamed_from):
        changes.append(
            Change(
                change_type=COURSE_DROPPED,
                course_code=code,
                course_title=titles.get(code),
                before={"code": code},
            )
        )

    for key in sorted(set(before_by) | set(after_by)):
        code, activity_type, stream_label = key
        # A renamed course's classes are reported under the rename, not as a
        # course's worth of arrivals and departures.
        if code in renamed_from or code in renamed_to:
            continue
        before = _sorted_slots(before_by.get(key, []))
        after = _sorted_slots(after_by.get(key, []))
        if [_slot_key(s) for s in before] == [_slot_key(s) for s in after]:
            continue

        if before and after:
            change_type = (
                CLASS_VENUE_CONFIRMED
                if _is_venue_confirmation(before, after)
                else CLASS_MOVED
            )
            payload_before: dict[str, Any] | None = {"slots": before}
            payload_after: dict[str, Any] | None = {"slots": after}
        elif after:
            if code in added_codes:
                continue  # already reported as a new course
            change_type = CLASS_ADDED
            payload_before, payload_after = None, {"slots": after}
        else:
            if code in dropped_codes:
                continue  # already reported as a withdrawn course
            change_type = CLASS_REMOVED
            payload_after = None
            # Whether this took the course's last class of its type with it.
            # The page says "no longer has a published Lecture" rather than
            # listing a removal, and needs to know without a second query.
            payload_before = {
                "slots": before,
                "lastOfType": activity_type not in types_after.get(code, set()),
            }

        changes.append(
            Change(
                change_type=change_type,
                course_code=code,
                course_title=titles.get(code),
                activity_type=activity_type or None,
                stream_label=stream_label or None,
                before=payload_before,
                after=payload_after,
            )
        )

    return changes


# Database access


_SESSIONS = """
SELECT c.code            AS code,
       c.title           AS title,
       c.resource_id     AS resource_id,
       s.activity_type   AS activity_type,
       s.stream_label    AS stream_label,
       s.day::text       AS day,
       s.start_min       AS start_min,
       s.end_min         AS end_min,
       r.code            AS room,
       s.weeks_raw       AS weeks_raw
  FROM sessions s
  JOIN courses c ON c.id = s.course_id
  LEFT JOIN rooms r ON r.id = s.room_id
 WHERE s.publication_id = %s
"""


def _session_rows(conn: psycopg.Connection, publication_id: int) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(_SESSIONS, (publication_id,))
        columns = [c.name for c in cur.description or ()]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


def previous_publication(conn: psycopg.Connection, publication_id: int) -> int | None:
    """The publication immediately before this one, or None if it is the first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM publications
             WHERE COALESCE(published_at, discovered_at) < (
                       SELECT COALESCE(published_at, discovered_at)
                         FROM publications WHERE id = %s)
             ORDER BY COALESCE(published_at, discovered_at) DESC
             LIMIT 1
            """,
            (publication_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def diff_publications(
    conn: psycopg.Connection, from_publication_id: int, to_publication_id: int
) -> list[Change]:
    """The changes between two publications, in either direction of time."""
    return diff_sessions(
        _session_rows(conn, from_publication_id),
        _session_rows(conn, to_publication_id),
    )


def store_diff(
    conn: psycopg.Connection, from_publication_id: int, to_publication_id: int
) -> int:
    """
    Compute and persist a diff, replacing any already stored for the pair.

    Idempotent, because a `--replace` reload changes the sessions a stored diff
    was computed from, and a diff describing rows that no longer exist is worse
    than no diff.
    """
    changes = diff_publications(conn, from_publication_id, to_publication_id)
    with conn.cursor() as cur:
        cur.execute(
            """
            DELETE FROM publication_changes
             WHERE from_publication_id = %s AND to_publication_id = %s
            """,
            (from_publication_id, to_publication_id),
        )
        if changes:
            cur.executemany(
                """
                INSERT INTO publication_changes
                    (from_publication_id, to_publication_id, change_type,
                     course_code, course_title, activity_type, stream_label,
                     before, after)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        from_publication_id,
                        to_publication_id,
                        c.change_type,
                        c.course_code,
                        c.course_title,
                        c.activity_type,
                        c.stream_label,
                        Json(c.before) if c.before is not None else None,
                        Json(c.after) if c.after is not None else None,
                    )
                    for c in changes
                ],
            )
    conn.commit()
    return len(changes)


#: How the page orders its class list: the changes a student must act on
#: first, then the ones that are merely good news.
_CLASS_KIND_ORDER = {
    CLASS_MOVED: 0,
    CLASS_REMOVED: 1,
    "sitting_removed": 2,
    CLASS_ADDED: 3,
    "sitting_added": 4,
    CLASS_VENUE_CONFIRMED: 5,
}


#: Display-only kinds. The stored `change_type` records what happened to the
#: class; these record what the reader sees, which is not always the same:
#: a class that kept every sitting and gained one more has changed without
#: having moved.
SITTING_ADDED = "sitting_added"
SITTING_REMOVED = "sitting_removed"


def slot_delta(
    before_slots: list[dict[str, Any]], after_slots: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """
    Only the slots that differ, either side.

    A class whose Tutorial gained a third sitting has two unchanged rows on
    each side. Printing them makes the reader do the diff themselves, and the
    thing that actually changed is the one line they have to find.
    """
    shared = {_slot_key(s) for s in before_slots} & {_slot_key(s) for s in after_slots}
    return (
        [s for s in before_slots if _slot_key(s) not in shared],
        [s for s in after_slots if _slot_key(s) not in shared],
    )


def display_kind(
    change_type: str,
    before_only: list[dict[str, Any]],
    after_only: list[dict[str, Any]],
) -> str:
    if change_type != CLASS_MOVED:
        return change_type
    if not before_only and after_only:
        return SITTING_ADDED
    if before_only and not after_only:
        return SITTING_REMOVED
    return CLASS_MOVED


def changes_for_page(conn: psycopg.Connection) -> dict[str, Any] | None:
    """
    The stored diff between the current publication and the one before it.

    Returns None when the warehouse holds a single publication, which is not an
    error: there is genuinely nothing to compare against, and the page says so.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, published_at FROM publications
             ORDER BY COALESCE(published_at, discovered_at) DESC LIMIT 2
            """
        )
        publications = cur.fetchall()

    if len(publications) < 2:
        return None

    (to_id, to_published_at), (from_id, from_published_at) = publications

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT change_type, course_code, course_title, activity_type,
                   stream_label, before, after
              FROM publication_changes
             WHERE from_publication_id = %s AND to_publication_id = %s
             ORDER BY course_code, activity_type NULLS FIRST, stream_label NULLS FIRST
            """,
            (from_id, to_id),
        )
        columns = [c.name for c in cur.description or ()]
        rows = [dict(zip(columns, row)) for row in cur.fetchall()]

    classes: list[dict[str, Any]] = []
    courses_added: list[dict[str, Any]] = []
    courses_dropped: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    lost_types: list[dict[str, Any]] = []

    for row in rows:
        kind = row["change_type"]
        if kind == COURSE_ADDED:
            courses_added.append(row)
        elif kind == COURSE_DROPPED:
            courses_dropped.append(row)
        elif kind == COURSE_RENAMED:
            renamed.append(
                {**row, "from_code": (row["before"] or {}).get("code")}
            )
        else:
            before = row["before"] or {}
            after = row["after"] or {}
            before_slots = before.get("slots") or []
            after_slots = after.get("slots") or []

            before_only, after_only = slot_delta(before_slots, after_slots)

            entry = {
                **row,
                "kind": kind,
                "before_slots": before_only,
                "after_slots": after_only,
                # What the reader is actually looking at. A class that only
                # gained a sitting has not moved, and saying it moved would
                # send them looking for a change that is not there.
                "display_kind": display_kind(kind, before_only, after_only),
            }
            classes.append(entry)
            # A removal that took the last of its type is the case that
            # strands a saved placement, so it is called out separately as
            # well as listed. It is not counted twice: the count of things
            # that changed is the number of changes, and this is a reading of
            # one of them.
            if kind == CLASS_REMOVED and before.get("lastOfType"):
                lost_types.append(entry)

    classes.sort(
        key=lambda c: (
            _CLASS_KIND_ORDER.get(c["display_kind"], 9),
            c["course_code"],
            c["activity_type"] or "",
            c["stream_label"] or "",
        )
    )

    # Counted by what the reader sees, so the headline "classes moved" does
    # not include classes that only gained a sitting.
    counts = {kind: 0 for kind in _CLASS_KIND_ORDER}
    for entry in classes:
        counts[entry["display_kind"]] = counts.get(entry["display_kind"], 0) + 1

    return {
        "from_id": from_id,
        "to_id": to_id,
        "from_published_at": from_published_at,
        "to_published_at": to_published_at,
        "classes": classes,
        "courses_added": courses_added,
        "courses_dropped": courses_dropped,
        "renamed": renamed,
        "lost_types": lost_types,
        "counts": counts,
        "total": len(rows),
    }


# What changed for one student's courses


def _api_entry(row: dict[str, Any]) -> dict[str, Any]:
    """
    One change, shaped for the builder.

    Both paths below produce this: the stored rows and a live diff have the
    same field names, so the caller cannot tell which one answered it.
    """
    change_type = row["change_type"]
    before = row.get("before") or {}
    after = row.get("after") or {}

    if change_type in (COURSE_ADDED, COURSE_DROPPED, COURSE_RENAMED):
        return {
            "code": row["course_code"],
            "title": row.get("course_title"),
            "changeType": change_type,
            "displayKind": change_type,
            "activityType": None,
            "streamLabel": None,
            # The code the student's timetable is holding, which is not the
            # one this change is filed under.
            "previousCode": before.get("code") if change_type == COURSE_RENAMED else None,
            "lastOfType": False,
            "before": [],
            "after": [],
        }

    before_only, after_only = slot_delta(
        before.get("slots") or [], after.get("slots") or []
    )
    return {
        "code": row["course_code"],
        "title": row.get("course_title"),
        "changeType": change_type,
        "displayKind": display_kind(change_type, before_only, after_only),
        "activityType": row.get("activity_type"),
        "streamLabel": row.get("stream_label"),
        "lastOfType": bool(before.get("lastOfType")),
        "before": before_only,
        "after": after_only,
    }


def _publication_exists(conn: psycopg.Connection, publication_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM publications WHERE id = %s", (publication_id,))
        return cur.fetchone() is not None


def _stored_changes_for(
    conn: psycopg.Connection, from_id: int, to_id: int, codes: list[str]
) -> list[dict[str, Any]]:
    """The precomputed hop, filtered to the courses asked about."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT change_type, course_code, course_title, activity_type,
                   stream_label, before, after
              FROM publication_changes
             WHERE from_publication_id = %s AND to_publication_id = %s
               AND (course_code = ANY(%s) OR before->>'code' = ANY(%s))
             ORDER BY course_code, activity_type NULLS FIRST
            """,
            # A rename is filed under the *new* code, so a student still
            # holding the old one would otherwise never be told about it.
            (from_id, to_id, codes, codes),
        )
        columns = [c.name for c in cur.description or ()]
        return [dict(zip(columns, row)) for row in cur.fetchall()]


_SCOPED_SESSIONS = _SESSIONS.replace(
    "WHERE s.publication_id = %s",
    """
 WHERE s.publication_id = %s
   AND (c.code = ANY(%s)
        OR c.resource_id IN (SELECT resource_id FROM courses
                              WHERE code = ANY(%s) AND resource_id IS NOT NULL))
""",
)


def _live_changes_for(
    conn: psycopg.Connection, from_id: int, to_id: int, codes: list[str]
) -> list[dict[str, Any]]:
    """
    A diff between two publications that are not neighbours.

    Only the consecutive hop is precomputed, so a student who missed a
    republish is answered by diffing their own courses directly. Scoped to
    those courses, which is at most 40, rather than the whole warehouse.

    The scope deliberately reaches past the codes asked for to anything
    sharing their published resource. A course whose code changed is a
    different code on each side of the diff, and scoping to the student's list
    alone would show them a withdrawal where there was a rename.
    """
    rows = []
    for publication_id in (from_id, to_id):
        with conn.cursor() as cur:
            cur.execute(_SCOPED_SESSIONS, (publication_id, codes, codes))
            columns = [c.name for c in cur.description or ()]
            rows.append([dict(zip(columns, row)) for row in cur.fetchall()])

    from dataclasses import asdict

    return [asdict(change) for change in diff_sessions(rows[0], rows[1])]


def changes_for_courses(
    conn: psycopg.Connection, codes: list[str], since: int | None = None
) -> dict[str, Any] | None:
    """
    What changed for a set of courses since a given publication.

    `since` is the publication the caller's timetable was built against.
    Omitting it means "the previous publication", which is the right answer
    for someone who has not built one.

    Returns None when the warehouse holds a single publication.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, published_at FROM publications
             ORDER BY COALESCE(published_at, discovered_at) DESC LIMIT 2
            """
        )
        publications = cur.fetchall()

    if len(publications) < 2:
        return None

    (to_id, to_published_at), (previous_id, previous_published_at) = publications

    since_unavailable = False
    if since is None or since == previous_id:
        from_id = previous_id
    elif since == to_id:
        # Already on the current publication. Nothing has happened to them.
        return {
            "from_id": to_id,
            "to_id": to_id,
            "from_published_at": to_published_at,
            "to_published_at": to_published_at,
            "since_unavailable": False,
            "changes": [],
        }
    elif _publication_exists(conn, since):
        from_id = since
    else:
        # Answering a different question silently would be worse than saying
        # which one was answered.
        from_id = previous_id
        since_unavailable = True

    rows = (
        _stored_changes_for(conn, from_id, to_id, codes)
        if from_id == previous_id
        else _live_changes_for(conn, from_id, to_id, codes)
    )

    from_published_at = previous_published_at
    if from_id != previous_id:
        with conn.cursor() as cur:
            cur.execute("SELECT published_at FROM publications WHERE id = %s", (from_id,))
            row = cur.fetchone()
            from_published_at = row[0] if row else None

    return {
        "from_id": from_id,
        "to_id": to_id,
        "from_published_at": from_published_at,
        "to_published_at": to_published_at,
        "since_unavailable": since_unavailable,
        "changes": [_api_entry(row) for row in rows],
    }


def summarise(changes: Iterable[Change]) -> dict[str, int]:
    """Headline counts, in the order the page's tiles read."""
    counts = {
        CLASS_MOVED: 0,
        CLASS_VENUE_CONFIRMED: 0,
        CLASS_ADDED: 0,
        CLASS_REMOVED: 0,
        COURSE_ADDED: 0,
        COURSE_DROPPED: 0,
        COURSE_RENAMED: 0,
    }
    for change in changes:
        if change.change_type in counts:
            counts[change.change_type] += 1
    return counts
