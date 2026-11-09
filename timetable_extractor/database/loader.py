"""
Load the finder.xml index and every extracted PDF into Postgres.

Sessions are written against a `publication` - the specific finder.xml the
site was serving - so successive loads accumulate history instead of
overwriting each other.
"""

from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

import psycopg

from timetable_extractor.database.changes import previous_publication, store_diff
from timetable_extractor.database.courses import (
    build_code_index,
    clipped_subject,
    is_test_course,
    published_subjects,
    resolve_course_code,
)
from timetable_extractor.database.horizon import carry_past_weeks, earlier_sittings
from timetable_extractor.database.people import build_name_index, resolve_name
from timetable_extractor.database.records import (
    SessionRecord,
    merge_records,
    normalise_room_code,
    records_from_extraction,
)
from timetable_extractor.database.weeks import export_horizon
from timetable_extractor.extract import extract_timetable
from timetable_extractor.observability import Diagnostics, get_logger

logger = get_logger(__name__)

# "Published 06-Aug-26 2:22:58 PM - University of the West Indies St. Augustine"
_PUBLISHED = re.compile(
    r"Published\s+(\d{1,2}-[A-Za-z]{3}-\d{2})\s+(\d{1,2}:\d{2}:\d{2}\s*[AP]M)", re.I
)

# finder.xml resource types -> our resource_kind enum.
_KINDS = {"module": "course", "staff": "staff", "room": "room"}
# PDF filename prefixes CELCAT uses per resource type.
_PREFIX_KINDS = {"m": "course", "s": "staff", "r": "room"}


@dataclass
class LoadStats:
    publication_id: int
    published_at: datetime | None
    resources: int
    courses: int
    staff: int
    rooms: int
    pdfs_read: int
    pdfs_failed: int
    raw_records: int
    sessions: int
    staff_links: int
    source_links: int
    reused_publication: bool
    #: Changes recorded against the previous publication. Zero on the first
    #: load, when there is nothing to compare against.
    changes: int = 0
    #: The first teaching week these PDFs cover, from their titles. None when
    #: no title said.
    horizon: int | None = None
    #: Sessions that took their past weeks back from the previous publication.
    weeks_carried: int = 0


def parse_published_at(xml_text: str) -> datetime | None:
    """Read the timestamp CELCAT prints in the finder.xml footer."""
    match = _PUBLISHED.search(xml_text)
    if not match:
        return None
    stamp = f"{match.group(1)} {match.group(2).replace(' ', '')}"
    for fmt in ("%d-%b-%y %I:%M:%S%p", "%d-%b-%Y %I:%M:%S%p"):
        try:
            return datetime.strptime(stamp, fmt)
        except ValueError:
            continue
    return None


def kind_for_pdf(link: str) -> str:
    """Course, staff or room, from CELCAT's filename prefix."""
    return _PREFIX_KINDS.get(Path(link).name[:1].lower(), "course")


def _fetch_id(cur: psycopg.Cursor, sql: str, params: tuple) -> int:
    cur.execute(sql, params)
    row = cur.fetchone()
    assert row is not None
    return row[0]


def upsert_publication(
    conn: psycopg.Connection,
    xml_bytes: bytes,
    *,
    http_last_modified: datetime | None = None,
    http_etag: str | None = None,
    resource_count: int = 0,
) -> tuple[int, bool]:
    """
    Return (publication_id, reused). Identity is the XML's sha256, so loading
    the same index twice does not create a second publication.
    """
    digest = hashlib.sha256(xml_bytes).hexdigest()
    published_at = parse_published_at(xml_bytes.decode("utf-8", "replace"))

    with conn.cursor() as cur:
        cur.execute("SELECT id FROM publications WHERE xml_sha256 = %s", (digest,))
        row = cur.fetchone()
        if row:
            return row[0], True

        publication_id = _fetch_id(
            cur,
            """
            INSERT INTO publications
                (published_at, http_last_modified, http_etag, xml_sha256, resource_count)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id
            """,
            (published_at, http_last_modified, http_etag, digest, resource_count),
        )
    conn.commit()
    return publication_id, False


def load_index(
    conn: psycopg.Connection, xml_bytes: bytes, publication_id: int
) -> dict[str, int]:
    """
    Load faculties, departments, resources and the course/staff/room entities.

    Returns counts. Re-running against the same index is a no-op apart from
    refreshing `last_seen_publication`.
    """
    root = ET.fromstring(xml_bytes)
    counts = {"resources": 0, "courses": 0, "staff": 0, "rooms": 0}

    faculty_ids: dict[str, int] = {}
    department_ids: dict[tuple[str, int | None], int] = {}

    with conn.cursor() as cur:
        for element in root.findall("resource"):
            kind = _KINDS.get(element.get("type") or "")
            link = element.get("link") or ""
            name = (element.findtext("name") or element.findtext("n") or "").strip()
            if not kind or not link or not name:
                continue

            faculty = (element.findtext("faculty") or "").strip()
            department = (element.findtext("dept") or "").strip()

            faculty_id = None
            if faculty:
                if faculty not in faculty_ids:
                    faculty_ids[faculty] = _fetch_id(
                        cur,
                        """
                        INSERT INTO faculties (name) VALUES (%s)
                        ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                        """,
                        (faculty,),
                    )
                faculty_id = faculty_ids[faculty]

            department_id = None
            if department:
                key = (department, faculty_id)
                if key not in department_ids:
                    cur.execute(
                        """
                        INSERT INTO departments (name, faculty_id) VALUES (%s, %s)
                        ON CONFLICT (name, faculty_id)
                        DO UPDATE SET name = EXCLUDED.name
                        RETURNING id
                        """,
                        key,
                    )
                    row = cur.fetchone()
                    assert row is not None
                    department_ids[key] = row[0]
                department_id = department_ids[key]

            resource_id = _fetch_id(
                cur,
                """
                INSERT INTO resources
                    (celcat_id, kind, pdf_link, name, department_id, faculty_id,
                     first_seen_publication, last_seen_publication)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (pdf_link) DO UPDATE SET
                    name = EXCLUDED.name,
                    department_id = EXCLUDED.department_id,
                    faculty_id = EXCLUDED.faculty_id,
                    last_seen_publication = EXCLUDED.last_seen_publication
                RETURNING id
                """,
                (
                    element.get("id") or "",
                    kind,
                    link,
                    name,
                    department_id,
                    faculty_id,
                    publication_id,
                    publication_id,
                ),
            )
            counts["resources"] += 1

            if kind == "course":
                # "ACCT 1002, Intro. to Financial Accounting"
                code, _, title = name.partition(",")
                code = " ".join(code.upper().split())
                if is_test_course(code):
                    # A Timetable Unit test entry is not a course: no row for
                    # students to search. `load_all` drops its sessions too.
                    continue
                cur.execute(
                    """
                    INSERT INTO courses (code, title, department_id, faculty_id, resource_id)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (code) DO UPDATE SET
                        title = COALESCE(EXCLUDED.title, courses.title),
                        department_id = COALESCE(EXCLUDED.department_id, courses.department_id),
                        faculty_id = COALESCE(EXCLUDED.faculty_id, courses.faculty_id),
                        resource_id = COALESCE(EXCLUDED.resource_id, courses.resource_id)
                    """,
                    (code, title.strip() or None, department_id, faculty_id, resource_id),
                )
                counts["courses"] += 1
            elif kind == "staff":
                cur.execute(
                    """
                    INSERT INTO staff (name, resource_id) VALUES (%s, %s)
                    ON CONFLICT (name) DO UPDATE SET
                        resource_id = COALESCE(EXCLUDED.resource_id, staff.resource_id)
                    """,
                    (name, resource_id),
                )
                counts["staff"] += 1
            elif kind == "room":
                # "TLC LT A1, Teaching and Learning Complex Lecture Theatre A 1"
                code, _, full = name.partition(",")
                cur.execute(
                    """
                    INSERT INTO rooms (code, name, resource_id) VALUES (%s, %s, %s)
                    ON CONFLICT (code) DO UPDATE SET
                        name = COALESCE(EXCLUDED.name, rooms.name),
                        resource_id = COALESCE(EXCLUDED.resource_id, rooms.resource_id)
                    """,
                    (normalise_room_code(code), full.strip() or None, resource_id),
                )
                counts["rooms"] += 1

    merge_room_spellings(conn)
    conn.commit()
    return counts


def plan_room_merges(rooms: Iterable[tuple[int, str]]) -> list[tuple[int, list[int], str]]:
    """
    (keep, drop, code) for each room stored under more than one spelling.

    Pure, so the choice of survivor is tested without a database. The row
    already spelt the normalised way is kept, since the bookings point at it;
    failing that, the oldest. A lone row whose code only needs its spaces
    collapsed comes back with nothing to drop, to be renamed.
    """
    groups: dict[str, list[tuple[int, str]]] = {}
    for room_id, code in rooms:
        groups.setdefault(normalise_room_code(code), []).append((room_id, code))

    plan = []
    for code, members in sorted(groups.items()):
        if not code or (len(members) == 1 and members[0][1] == code):
            continue
        members.sort(key=lambda m: (m[1] != code, m[0]))
        (keep, _), *drop = members
        plan.append((keep, [room_id for room_id, _ in drop], code))
    return plan


def merge_room_spellings(conn: psycopg.Connection) -> int:
    """
    Fold rooms stored under a doubled-space spelling into the single-spaced row.

    Before `normalise_room_code`, every load wrote the registry's spelling and
    the bookings' as separate rows, and the warehouse still holds both. This
    runs on every load so the copy the deployment reads heals on its next load
    without a one-off script; once merged it finds nothing to do.

    A drop row's sessions move to the survivor. If one would collide with a
    session already there, the pair is left alone and logged rather than a
    class deleted: the free rooms page compares collapsed codes either way.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT id, code FROM rooms")
        plan = plan_room_merges(cur.fetchall())

    merged = 0
    for keep, drop, code in plan:
        try:
            with conn.transaction(), conn.cursor() as cur:
                for room_id in drop:
                    cur.execute(
                        "UPDATE sessions SET room_id = %s WHERE room_id = %s", (keep, room_id)
                    )
                    cur.execute(
                        """
                        UPDATE rooms keep SET
                            name = COALESCE(keep.name, old.name),
                            resource_id = COALESCE(keep.resource_id, old.resource_id)
                          FROM rooms old
                         WHERE keep.id = %s AND old.id = %s
                        """,
                        (keep, room_id),
                    )
                    cur.execute("DELETE FROM rooms WHERE id = %s", (room_id,))
                cur.execute("UPDATE rooms SET code = %s WHERE id = %s", (code, keep))
        except psycopg.errors.UniqueViolation:
            logger.warning(
                "room_merge_collided",
                extra={"event": "load.room_merge_collided", "room": code},
            )
            continue
        merged += len(drop)

    if plan:
        logger.info("room_spellings_merged", extra={"event": "load.room_spellings_merged", "rows": merged})
    return merged


def drop_test_records(
    records: list[SessionRecord], diagnostics: Diagnostics
) -> list[SessionRecord]:
    """
    Leave out Timetable Unit test entries ("TEST 1001"): they are not classes.

    Named as a finding, once per course, rather than dropped silently, so a
    real subject the rule caught by mistake would show up in the load's output.
    Runs after code resolution, so a test code read from a room's PDF is
    caught too.
    """
    for code in sorted({r.course_code for r in records if is_test_course(r.course_code)}):
        diagnostics.add("test_course_skipped", course=code)
    return [r for r in records if not is_test_course(r.course_code)]


def repair_clipped_codes(
    records: list[SessionRecord],
    own_course: dict[str, str],
    canonical: set[str],
    diagnostics: Diagnostics,
) -> list[SessionRecord]:
    """
    Give a course code CELCAT clipped to its bare subject back to its course.

    The 6 Nov 2026 publication printed an hour-long GEND block as "GEND 3501;
    GEND 5001; GEND 6002; GEND 7001; GEND". Left alone, the bare "GEND" became
    a course of its own, and GEND 8001, whose own PDF the block was read from,
    lost the class. A block in a course's own PDF belongs to that course, so a
    clipped code read there becomes it when the subject matches. Read anywhere
    else, the course it named cannot be recovered and the record is dropped;
    the other PDFs that print the block still place it. Runs after code
    resolution, on records that each come from one PDF, and every repair is
    named as a finding.
    """
    subjects = published_subjects(canonical)
    kept: list[SessionRecord] = []
    for record in records:
        subject = (
            None
            if record.course_code in canonical
            else clipped_subject(record.course_code, subjects)
        )
        if subject is None:
            kept.append(record)
            continue
        source = min(record.sources) if record.sources else None
        owner = own_course.get(source or "")
        if owner and owner.split()[0].upper() != subject:
            owner = None
        diagnostics.add(
            "course_code_clipped", code=record.course_code, course=owner, source=source
        )
        if owner:
            record.course_code = owner
            kept.append(record)
    return kept


def drop_orphaned_test_courses(conn: psycopg.Connection) -> int:
    """
    Remove test-entry course rows that no session refers to any more.

    "TEST 1001" was loaded with publication 12 before the loader learned to
    skip test entries. Re-loading drops its sessions, but the course row would
    stay, and the course page looks a course up there. Run after the sessions
    are written, so a test course with history in an older publication keeps
    its row.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.id, c.code FROM courses c
             WHERE NOT EXISTS (SELECT 1 FROM sessions s WHERE s.course_id = c.id)
            """
        )
        doomed = [row[0] for row in cur.fetchall() if is_test_course(row[1])]
        if doomed:
            cur.execute("DELETE FROM courses WHERE id = ANY(%s)", (doomed,))
    conn.commit()
    return len(doomed)


def register_pdfs(conn: psycopg.Connection, paths: list[Path]) -> dict[str, int]:
    """
    Record every local PDF's bytes in one batch, returning {filename: id}.

    `content_changed_at` only moves when the hash actually differs, so a
    re-load of unchanged files does not fake an update.
    """
    if not paths:
        return {}

    now = datetime.now(timezone.utc)
    rows = []
    for path in paths:
        data = path.read_bytes()
        rows.append(
            (
                path.name,
                kind_for_pdf(path.name),
                hashlib.sha256(data).hexdigest(),
                len(data),
                now,
                now,
            )
        )

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO pdf_files
                (pdf_link, kind, sha256, byte_size, content_changed_at, last_checked_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (pdf_link) DO UPDATE SET
                last_checked_at = EXCLUDED.last_checked_at,
                byte_size = EXCLUDED.byte_size,
                content_changed_at = CASE
                    WHEN pdf_files.sha256 IS DISTINCT FROM EXCLUDED.sha256
                    THEN EXCLUDED.content_changed_at
                    ELSE pdf_files.content_changed_at
                END,
                sha256 = EXCLUDED.sha256
            """,
            rows,
        )
        cur.execute("SELECT pdf_link, id FROM pdf_files")
        registered = dict(cur.fetchall())
    conn.commit()

    return {path.name: registered[path.name] for path in paths if path.name in registered}


def iter_pdfs(directories: Iterable[Path]) -> list[Path]:
    """Every PDF under the given directories, deduplicated by filename."""
    seen: dict[str, Path] = {}
    for directory in directories:
        if not directory.exists():
            continue
        for path in sorted(directory.rglob("*.pdf")):
            seen.setdefault(path.name, path)
    return list(seen.values())


def _ensure_lookup(
    cur: psycopg.Cursor,
    table: str,
    column: str,
    values: Iterable[str],
) -> dict[str, int]:
    """Insert any missing lookup rows in one round trip, then map value -> id."""
    wanted = sorted({v for v in values if v})
    if wanted:
        cur.executemany(
            f"INSERT INTO {table} ({column}) VALUES (%s) ON CONFLICT ({column}) DO NOTHING",
            [(value,) for value in wanted],
        )
    cur.execute(f"SELECT {column}, id FROM {table}")
    return dict(cur.fetchall())


def write_sessions(
    conn: psycopg.Connection,
    publication_id: int,
    records: list[SessionRecord],
    pdf_ids: dict[str, int],
) -> tuple[int, int, int]:
    """
    Insert merged sessions plus their staff and provenance links.

    Written in bulk rather than row-by-row: the database is remote, and a
    round trip per session (plus one per staff and source link) turned a load
    into tens of thousands of sequential network calls. Session ids are
    recovered by selecting the natural key back, which avoids needing RETURNING
    on a batched insert.
    """
    if not records:
        return 0, 0, 0

    with conn.cursor() as cur:
        # Courses and rooms can appear inside a shared block without having
        # their own entry in the index, so top the lookup tables up first.
        course_ids = _ensure_lookup(cur, "courses", "code", (r.course_code for r in records))
        room_ids = _ensure_lookup(cur, "rooms", "code", (r.room_code for r in records))
        staff_ids = _ensure_lookup(
            cur, "staff", "name", (name for r in records for name in r.staff)
        )

        rows = []
        for record in records:
            rows.append(
                (
                    publication_id,
                    record.semester,
                    course_ids[record.course_code],
                    room_ids.get(record.room_code) if record.room_code else None,
                    record.day,
                    record.start_min,
                    record.end_min,
                    record.activity_type,
                    record.stream_label,
                    record.weeks_raw,
                    record.weeks,
                    record.week_count,
                    record.notes,
                    record.raw_text,
                )
            )

        cur.execute("SELECT count(*) FROM sessions WHERE publication_id = %s", (publication_id,))
        before = (cur.fetchone() or [0])[0]

        cur.executemany(
            """
            INSERT INTO sessions
                (publication_id, semester, course_id, room_id, day,
                 start_min, end_min, activity_type, stream_label,
                 weeks_raw, weeks, week_count, notes, raw_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            rows,
        )

        cur.execute("SELECT count(*) FROM sessions WHERE publication_id = %s", (publication_id,))
        written = (cur.fetchone() or [0])[0] - before

        # Recover ids by natural key so the link tables can be built in bulk.
        cur.execute(
            """
            SELECT id, course_id, day::text, start_min, end_min,
                   COALESCE(room_id, -1), COALESCE(activity_type, ''),
                   COALESCE(stream_label, ''), COALESCE(weeks_raw, '')
              FROM sessions
             WHERE publication_id = %s
            """,
            (publication_id,),
        )
        session_ids = {tuple(row[1:]): row[0] for row in cur.fetchall()}

        staff_rows: list[tuple[int, int]] = []
        source_rows: list[tuple[int, int]] = []
        for record in records:
            key = (
                course_ids[record.course_code],
                record.day,
                record.start_min,
                record.end_min,
                room_ids.get(record.room_code, -1) if record.room_code else -1,
                record.activity_type or "",
                record.stream_label or "",
                record.weeks_raw or "",
            )
            session_id = session_ids.get(key)
            if session_id is None:
                continue
            for name in record.staff:
                staff_rows.append((session_id, staff_ids[name]))
            for source in record.sources:
                pdf_id = pdf_ids.get(source)
                if pdf_id is not None:
                    source_rows.append((session_id, pdf_id))

        if staff_rows:
            cur.executemany(
                "INSERT INTO session_staff (session_id, staff_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                staff_rows,
            )
        if source_rows:
            cur.executemany(
                "INSERT INTO session_sources (session_id, pdf_file_id) VALUES (%s, %s) "
                "ON CONFLICT DO NOTHING",
                source_rows,
            )

    conn.commit()
    return written, len(staff_rows), len(source_rows)


def load_all(
    open_connection: Callable[[], psycopg.Connection],
    *,
    finder_xml: Path,
    pdf_dirs: Iterable[Path],
    http_last_modified: datetime | None = None,
    http_etag: str | None = None,
    progress: bool = True,
    replace: bool = False,
) -> LoadStats:
    """
    Extract every PDF and load one publication's worth of data.

    Set `replace` when re-loading a publication the database already has after
    changing the extractor. Sessions are keyed on their content, so a fix that
    moves a class to a different day inserts a corrected row without removing
    the wrong one, leaving the class on both days. Replacing clears the
    publication's sessions so the reload is a true re-extraction.

    The clear happens in the same transaction as the insert, after extraction
    rather than before it. Replacing the *current* publication used to delete
    its sessions and commit straight away, and then spend ten minutes reading
    PDFs, so the live site served that publication with no classes at all for
    the whole extraction.

    Nothing is written until every PDF has been read, for the same reason: a
    new publication becomes the current one the moment its row is committed,
    and a publication with no sessions yet is an empty timetable. Extraction
    needs no database, so it runs first and the writes follow it.

    That is also why this takes a way to open a connection rather than an open
    one. A connection held across extraction sits idle for its four minutes,
    and the server closes it: the 17 Sep and 12 Oct 2026 loads both died on
    the first statement afterwards with "SSL connection has been closed
    unexpectedly". Neon suspends idle compute after about five minutes. The
    connection is opened once the last PDF has been read, so the writes start
    on a fresh one.
    """
    xml_bytes = finder_xml.read_bytes()
    resource_count = len(ET.fromstring(xml_bytes).findall("resource"))

    # Read the PDFs before the publication row exists. `latest_publication`
    # picks the newest publication and `current_sessions` reads only that one,
    # so a publication row created up front is current for the whole twenty
    # minutes of extraction while it still has no sessions - the live site
    # serves an empty timetable, exactly as the `--replace` path used to.
    # On 17 Sep 2026 the connection dropped mid-extraction and the load never
    # reached `write_sessions`, so that window stayed open: /explore/ops.json
    # reported 0 sessions and 0 courses until the publication was reloaded.
    # Extraction needs no database, so it happens first and a crash here now
    # leaves the previous publication current.
    paths = iter_pdfs(pdf_dirs)
    raw: list[SessionRecord] = []
    read = failed = 0
    #: Each PDF's export horizon, keyed by filename as `SessionRecord.sources` is.
    horizons: dict[str, int | None] = {}
    diagnostics = Diagnostics(source=finder_xml.name)

    for position, path in enumerate(paths, 1):
        if progress and position % 100 == 0:
            print(f"  extracting {position}/{len(paths)}...", flush=True)
        try:
            result = extract_timetable(str(path))
        except Exception as exc:  # noqa: BLE001 - one bad PDF must not stop the load
            failed += 1
            print(f"  ! {path.name}: {type(exc).__name__}: {exc}", flush=True)
            continue
        read += 1
        horizons[path.name] = export_horizon(result.get("course_title"))
        if horizons[path.name] is None:
            diagnostics.add("export_horizon_missing", source=path.name)
        raw.extend(records_from_extraction(result, source=path.name))

    with open_connection() as conn:
        publication_id, reused = upsert_publication(
            conn,
            xml_bytes,
            http_last_modified=http_last_modified,
            http_etag=http_etag,
            resource_count=resource_count,
        )

        index_counts = load_index(conn, xml_bytes, publication_id)

        pdf_ids = register_pdfs(conn, paths)

        # Snap course codes and staff spellings back onto the published index
        # before merging. A wrapped or junk-suffixed code would otherwise become
        # its own course row, splitting one course's timetable across two.
        with conn.cursor() as cur:
            cur.execute("SELECT name FROM staff WHERE resource_id IS NOT NULL")
            name_index = build_name_index([row[0] for row in cur.fetchall()])
            cur.execute("SELECT code FROM courses WHERE resource_id IS NOT NULL")
            code_index = build_code_index([row[0] for row in cur.fetchall()])
            cur.execute(
                "SELECT r.pdf_link, c.code FROM courses c"
                " JOIN resources r ON r.id = c.resource_id"
            )
            own_course = {link: code for link, code in cur.fetchall()}

        for record in raw:
            record.course_code = resolve_course_code(record.course_code, code_index)
            record.staff = list(
                dict.fromkeys(resolve_name(name, name_index) for name in record.staff)
            )

        raw = repair_clipped_codes(
            raw, own_course, set(code_index.values()), diagnostics
        )
        raw = drop_test_records(raw, diagnostics)

        merged = merge_records(raw)

        # The PDFs only print weeks from the current teaching week on. Weeks that
        # have passed are taken back from the publication before this one, or the
        # diff reports every class as moved each week. See horizon.py.
        distinct = sorted({h for h in horizons.values() if h is not None})
        if len(distinct) > 1:
            diagnostics.add("export_horizon_mixed", horizons=distinct)
        # The diff takes the lowest, so no week a PDF still printed counts as past.
        # Carrying is decided per record from its own sources, so it only needs to
        # know whether any PDF has moved past week 1.
        horizon = distinct[0] if distinct else None

        previous = previous_publication(conn, publication_id)
        weeks_carried = 0
        if previous and distinct and distinct[-1] > 1:
            weeks_carried = carry_past_weeks(
                merged, earlier_sittings(conn, previous), horizons, diagnostics
            )
        if progress and horizon:
            print(
                f"  weeks from W{horizon}: past weeks carried onto {weeks_carried} sessions",
                flush=True,
            )
        diagnostics.emit(logger)
        if progress:
            for finding, count in sorted(diagnostics.findings.items()):
                print(f"  ! {finding}: {count}", flush=True)

        if replace and reused:
            with conn.cursor() as cur:
                # session_staff and session_sources cascade from sessions. Not
                # committed here: write_sessions commits the insert, and readers
                # see the old rows until then.
                cur.execute(
                    "DELETE FROM sessions WHERE publication_id = %s", (publication_id,)
                )
                removed = cur.rowcount
            if progress:
                print(f"  replacing {removed} existing sessions", flush=True)

        written, staff_links, source_links = write_sessions(
            conn, publication_id, merged, pdf_ids
        )
        drop_orphaned_test_courses(conn)

        with conn.cursor() as cur:
            cur.execute("SELECT published_at FROM publications WHERE id = %s", (publication_id,))
            row = cur.fetchone()
            published_at = row[0] if row else None

        # What this republish changed, computed now rather than on every page view.
        # A `--replace` reload rewrites the sessions the stored diff was derived
        # from, so this recomputes rather than appending.
        changes = store_diff(conn, previous, publication_id, horizon=horizon) if previous else 0
        if progress and previous:
            print(f"  changes vs publication {previous}: {changes}", flush=True)

        return LoadStats(
            publication_id=publication_id,
            published_at=published_at,
            resources=index_counts["resources"],
            courses=index_counts["courses"],
            staff=index_counts["staff"],
            rooms=index_counts["rooms"],
            pdfs_read=read,
            pdfs_failed=failed,
            raw_records=len(raw),
            sessions=written,
            staff_links=staff_links,
            source_links=source_links,
            reused_publication=reused,
            changes=changes,
            horizon=horizon,
            weeks_carried=weeks_carried,
        )
