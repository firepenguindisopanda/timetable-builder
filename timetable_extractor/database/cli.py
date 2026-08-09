"""
Command line interface to the timetable warehouse.

    uv run python -m timetable_extractor.database.cli init
    uv run python -m timetable_extractor.database.cli load
    uv run python -m timetable_extractor.database.cli stats
    uv run python -m timetable_extractor.database.cli course COMP2601
    uv run python -m timetable_extractor.database.cli free-rooms Monday 10:00 12:00
    uv run python -m timetable_extractor.database.cli clashes COMP2601 COMP2602
    uv run python -m timetable_extractor.database.cli staff-load
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from timetable_extractor.database import queries
from timetable_extractor.database.connection import (
    DatabaseNotConfigured,
    apply_schema,
    connect,
)
from timetable_extractor.database.loader import load_all


def _minutes(label: str) -> int:
    """Accept '10:00', '10:00 AM' or '1400'."""
    match = re.match(r"^(\d{1,2}):(\d{2})\s*([AaPp][Mm])?$", label.strip())
    if not match:
        raise argparse.ArgumentTypeError(f"not a time: {label!r}")
    hours, minutes, meridiem = int(match.group(1)), int(match.group(2)), match.group(3)
    if meridiem:
        meridiem = meridiem.upper()
        if meridiem == "PM" and hours != 12:
            hours += 12
        if meridiem == "AM" and hours == 12:
            hours = 0
    return hours * 60 + minutes


def _print_table(rows: list[dict], columns: list[str] | None = None) -> None:
    if not rows:
        print("(no rows)")
        return
    columns = columns or list(rows[0].keys())
    widths = {
        c: min(38, max(len(c), max(len(str(r.get(c, ""))) for r in rows)))
        for c in columns
    }
    print("  ".join(c.upper().ljust(widths[c]) for c in columns))
    print("  ".join("-" * widths[c] for c in columns))
    for row in rows:
        print("  ".join(str(row.get(c, ""))[: widths[c]].ljust(widths[c]) for c in columns))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="create tables, indexes and views")

    load_parser = sub.add_parser("load", help="extract every PDF into the database")
    load_parser.add_argument("--pdf-dir", default="downloaded_pdfs")
    load_parser.add_argument("--registry", default="finder.xml")

    sub.add_parser("stats", help="row counts and field coverage")

    course_parser = sub.add_parser("course", help="show one course's timetable")
    course_parser.add_argument("code", nargs="+")

    free_parser = sub.add_parser("free-rooms", help="rooms free over a time range")
    free_parser.add_argument("day")
    free_parser.add_argument("start", type=_minutes)
    free_parser.add_argument("end", type=_minutes)
    free_parser.add_argument("--week", type=int, help="restrict to one teaching week")

    room_parser = sub.add_parser("room", help="what is booked in a room")
    room_parser.add_argument("code", nargs="+")

    clash_parser = sub.add_parser("clashes", help="real clashes among a course set")
    clash_parser.add_argument("codes", nargs="+")

    staff_parser = sub.add_parser("staff-load", help="teaching hours per staff member")
    staff_parser.add_argument("--limit", type=int, default=20)

    sub.add_parser("busiest", help="most congested weekday hours")

    args = parser.parse_args()

    try:
        with connect() as conn:
            if args.command == "init":
                apply_schema(conn)
                print("Schema applied.")
                return 0

            if args.command == "load":
                apply_schema(conn)
                root = Path(args.pdf_dir)
                stats = load_all(
                    conn,
                    finder_xml=Path(args.registry),
                    pdf_dirs=[root, root / "staff", root / "rooms"],
                )
                print()
                print(f"Publication  : {stats.publication_id}"
                      f"{'  (already known)' if stats.reused_publication else '  (new)'}")
                print(f"Published at : {stats.published_at}")
                print(f"Index        : {stats.resources} resources "
                      f"({stats.courses} courses, {stats.staff} staff, {stats.rooms} rooms)")
                print(f"PDFs read    : {stats.pdfs_read}  (failed: {stats.pdfs_failed})")
                print(f"Raw records  : {stats.raw_records}")
                print(f"Sessions     : {stats.sessions} after merging")
                print(f"Links        : {stats.staff_links} staff, {stats.source_links} sources")
                return 0

            if args.command == "stats":
                summary = queries.coverage_summary(conn)
                total = summary.get("sessions") or 1
                print(f"Sessions                  : {summary.get('sessions')}")
                print(f"Distinct courses          : {summary.get('courses')}")
                for label, key in (
                    ("With a room", "with_room"),
                    ("With staff named", "with_staff"),
                    ("With a stream label", "with_stream"),
                    ("With weeks", "with_weeks"),
                    ("With notes", "with_notes"),
                ):
                    value = summary.get(key, 0)
                    print(f"{label:<26}: {value:>6}  ({100 * value / total:5.1f}%)")
                print(f"Confirmed by >1 PDF       : {summary.get('confirmed_by_multiple_pdfs')}")
                return 0

            if args.command == "course":
                code = " ".join(args.code)
                if " " not in code:  # accept COMP2601 as well as "COMP 2601"
                    code = re.sub(r"^([A-Za-z]+)\s*(\d.*)$", r"\1 \2", code)
                _print_table(queries.course_timetable(conn, code))
                return 0

            if args.command == "free-rooms":
                rooms = queries.free_rooms(
                    conn, args.day.capitalize(), args.start, args.end, args.week
                )
                print(f"{len(rooms)} room(s) free:")
                for room in rooms:
                    print(f"   {room}")
                return 0

            if args.command == "room":
                _print_table(queries.room_occupancy(conn, " ".join(args.code)))
                return 0

            if args.command == "clashes":
                found = queries.clashes(conn, args.codes)
                if not found:
                    print("No clashes.")
                    return 0
                for row in found:
                    print(
                        f"{row['day']:<10} {row['start_a']}-{row['end_a']} "
                        f"{row['course_a']} {row['type_a'] or ''} "
                        f"vs {row['start_b']}-{row['end_b']} "
                        f"{row['course_b']} {row['type_b'] or ''}  "
                        f"weeks {row['shared_weeks']}"
                    )
                return 0

            if args.command == "staff-load":
                _print_table(queries.staff_load(conn, args.limit))
                return 0

            _print_table(queries.busiest_hours(conn))
            return 0

    except DatabaseNotConfigured as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
