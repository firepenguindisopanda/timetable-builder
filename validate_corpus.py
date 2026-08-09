"""
Corpus-wide smoke test for the CELCAT extractor.

Runs extraction over every downloaded PDF and reports field-level coverage plus
sanity checks, cross-referencing extracted rooms and course codes against the
authoritative lists published in finder.xml. Run this after each semester's
PDFs are published: CELCAT's layout and text conventions drift between
semesters, and the failures are usually silent (a whole day of classes landing
on the wrong row) rather than a crash.

Usage:
    uv run python validate_corpus.py
    uv run python validate_corpus.py --pdf-dir downloaded_pdfs
    uv run python validate_corpus.py --json report.json     # machine-readable
    uv run python validate_corpus.py --fail-under 95        # CI gate

Exits non-zero if any PDF crashes, if a sanity check fails, or if coverage of
the required fields drops below --fail-under.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

from timetable_extractor import extract_timetable
from timetable_extractor.constants import FINDER_XML

VALID_DAYS = {
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
}
TIME_RE = re.compile(r"^\d{2}:\d{2} (AM|PM)$")

# Fields that must be present on every entry for the calendar to place it.
REQUIRED_FIELDS = ("day", "start_time", "end_time")
# Fields that are informative but legitimately absent on some blocks.
OPTIONAL_FIELDS = ("type", "course", "room", "weeks", "staff")


def load_registry(path: Path) -> tuple[set[str], dict[str, str]]:
    """Return (official room codes, {pdf link -> course name}) from finder.xml."""
    if not path.exists():
        print(f"Fetching room/course registry: {FINDER_XML}")
        with urllib.request.urlopen(FINDER_XML, timeout=30) as resp:
            path.write_bytes(resp.read())

    root = ET.parse(path).getroot()
    rooms: set[str] = set()
    modules: dict[str, str] = {}
    for r in root.findall("resource"):
        name = (r.findtext("name") or r.findtext("n") or "").strip()
        if r.get("type") == "room":
            rooms.add(name.split(",")[0].strip())
        elif r.get("type") == "module":
            modules[r.get("link") or ""] = name
    return rooms, modules


def to_minutes(t: str | None) -> int | None:
    m = re.match(r"^(\d{2}):(\d{2}) (AM|PM)$", t or "")
    if not m:
        return None
    hours, mins, meridiem = int(m.group(1)), int(m.group(2)), m.group(3)
    if meridiem == "PM" and hours != 12:
        hours += 12
    if meridiem == "AM" and hours == 12:
        hours = 0
    return hours * 60 + mins


def validate(pdf_dir: Path, registry: Path) -> dict[str, Any]:
    rooms, modules = load_registry(registry)
    pdfs = sorted(pdf_dir.glob("*.pdf"))
    if not pdfs:
        raise SystemExit(f"No PDFs found in {pdf_dir}. Run download first.")

    print(f"Validating {len(pdfs)} PDFs from {pdf_dir}\n")

    stats: Counter[str] = Counter()
    semesters: Counter[str] = Counter()
    types: Counter[str] = Counter()
    days: Counter[str] = Counter()
    unknown_rooms: Counter[str] = Counter()
    crashes: list[dict[str, str]] = []
    empty: list[str] = []
    bad_times: list[str] = []
    course_mismatch: list[dict[str, str]] = []
    multi_session: list[str] = []

    started = time.time()
    for pdf in pdfs:
        try:
            result = extract_timetable(str(pdf))
        except Exception as exc:  # noqa: BLE001 - scan the whole corpus regardless
            crashes.append({"file": pdf.name, "error": f"{type(exc).__name__}: {exc}"})
            continue

        stats["files"] += 1
        semesters[result["semester"] or "(none)"] += 1
        entries = result["entries"]
        stats["entries"] += len(entries)
        if not entries:
            empty.append(pdf.name)

        expected_code = ""
        if pdf.name in modules:
            expected_code = modules[pdf.name].split(",")[0].strip()

        for e in entries:
            for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
                if e.get(field):
                    stats[f"has_{field}"] += 1

            days[e.get("day") or "(none)"] += 1
            if e.get("day") not in VALID_DAYS:
                stats["bad_day"] += 1
            if not TIME_RE.match(e.get("start_time") or ""):
                stats["bad_start"] += 1
            if e.get("type"):
                types[e["type"]] += 1

            start, end = to_minutes(e.get("start_time")), to_minutes(e.get("end_time"))
            if start is not None and end is not None and end <= start:
                stats["end_before_start"] += 1
                if len(bad_times) < 10:
                    bad_times.append(f"{pdf.name} {e['start_time']}-{e['end_time']}")

            # A block holding two "Room:" labels is really two sessions that
            # were merged, so one of the two rooms is being reported wrongly.
            if len(re.findall(r"\bRoom:", e.get("raw_text") or "")) > 1:
                stats["multi_session_block"] += 1
                if len(multi_session) < 10:
                    multi_session.append(f"{pdf.name}: {e.get('room')}")

            room = e.get("room")
            if room and rooms and room not in rooms:
                unknown_rooms[room] += 1

            # A block may legitimately list several courses ("Courses: CHEM
            # 1075; CHEM 1080; ..." on a shared review session), so the PDF's
            # own module code only has to appear somewhere in the value.
            got = (e.get("course") or "").replace(" ", "")
            want = expected_code.replace(" ", "")
            if want and got:
                if ";" in (e.get("course") or ""):
                    stats["multi_course_block"] += 1
                if want not in got:
                    stats["course_mismatch"] += 1
                    if len(course_mismatch) < 10:
                        course_mismatch.append(
                            {"file": pdf.name, "expected": expected_code, "got": e["course"]}
                        )

    return {
        "elapsed_sec": round(time.time() - started, 1),
        "pdf_count": len(pdfs),
        "stats": dict(stats),
        "semesters": dict(semesters),
        "types": dict(types),
        "days": dict(days),
        "crashes": crashes,
        "empty": empty,
        "bad_times": bad_times,
        "course_mismatch": course_mismatch,
        "multi_session": multi_session,
        "unknown_rooms": unknown_rooms.most_common(20),
        "room_registry_size": len(rooms),
    }


def report(r: dict[str, Any], fail_under: float) -> int:
    stats = r["stats"]
    total = stats.get("entries", 0)
    n = total or 1

    print("=" * 64)
    print(f"Files parsed         : {stats.get('files', 0)} / {r['pdf_count']}   ({r['elapsed_sec']}s)")
    print(f"Crashes              : {len(r['crashes'])}")
    print(f"Files with 0 entries : {len(r['empty'])}")
    print(f"Total entries        : {total}")
    print()

    print("Field coverage (% of entries):")
    for field in REQUIRED_FIELDS + OPTIONAL_FIELDS:
        got = stats.get(f"has_{field}", 0)
        flag = "  <- required" if field in REQUIRED_FIELDS else ""
        print(f"   {field:<12} {got:>6} / {total}   {100 * got / n:5.1f}%{flag}")
    print()

    print("Sanity checks:")
    print(f"   invalid day values      : {stats.get('bad_day', 0)}")
    print(f"   malformed start times   : {stats.get('bad_start', 0)}")
    print(f"   end <= start            : {stats.get('end_before_start', 0)}")
    print(f"   merged multi-session    : {stats.get('multi_session_block', 0)}")
    print(f"   course missing PDF's code: {stats.get('course_mismatch', 0)}"
          f"   (multi-course blocks: {stats.get('multi_course_block', 0)})")
    if r["room_registry_size"]:
        with_room = stats.get("has_room", 0)
        unknown = sum(c for _, c in r["unknown_rooms"])
        known = with_room - unknown
        print(f"   rooms in official list  : {known} / {with_room}"
              f"  ({100 * known / max(with_room, 1):.1f}%)")
    print()
    print(f"Semesters : {r['semesters']}")
    print(f"Days      : {r['days']}")
    print(f"Types     : {r['types']}")

    if r["crashes"]:
        print("\nCRASHES:")
        for c in r["crashes"][:15]:
            print(f"   {c['file']}: {c['error']}")
    if r["empty"]:
        print(f"\nEmpty extractions ({len(r['empty'])}), first 15: {r['empty'][:15]}")
    if r["bad_times"]:
        print(f"\nBad time ranges: {r['bad_times']}")
    if r["multi_session"]:
        print("\nMerged multi-session blocks (sample):")
        for m in r["multi_session"]:
            print(f"   {m}")
    if r["course_mismatch"]:
        print("\nCourse-code mismatches (sample):")
        for m in r["course_mismatch"]:
            print(f"   {m['file']}: expected {m['expected']!r}, got {m['got']!r}")
    if r["unknown_rooms"]:
        print("\nRooms not in the official registry (top 20):")
        for room, cnt in r["unknown_rooms"]:
            print(f"   {cnt:>4}  {room[:70]!r}")

    # -- Exit status --
    failures: list[str] = []
    if r["crashes"]:
        failures.append(f"{len(r['crashes'])} PDF(s) crashed")
    if r["empty"]:
        failures.append(f"{len(r['empty'])} PDF(s) produced no entries")
    for check, label in (
        ("bad_day", "invalid day values"),
        ("bad_start", "malformed start times"),
        ("end_before_start", "inverted time ranges"),
    ):
        if stats.get(check):
            failures.append(f"{stats[check]} {label}")
    for field in REQUIRED_FIELDS:
        pct = 100 * stats.get(f"has_{field}", 0) / n
        if pct < fail_under:
            failures.append(f"{field} coverage {pct:.1f}% < {fail_under}%")

    print()
    if failures:
        print("FAILED: " + "; ".join(failures))
        return 1
    print("PASSED: all required fields present, no crashes, no sanity violations.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--pdf-dir", default="downloaded_pdfs", help="Directory of timetable PDFs")
    parser.add_argument(
        "--registry",
        default="finder.xml",
        help="Path to finder.xml (downloaded automatically if absent)",
    )
    parser.add_argument("--json", help="Also write the full report to this JSON file")
    parser.add_argument(
        "--fail-under",
        type=float,
        default=99.0,
        help="Minimum %% coverage required for day/start_time/end_time (default: 99)",
    )
    args = parser.parse_args()

    result = validate(Path(args.pdf_dir), Path(args.registry))
    code = report(result, args.fail_under)

    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=2, default=str))
        print(f"\nJSON report written to {args.json}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
