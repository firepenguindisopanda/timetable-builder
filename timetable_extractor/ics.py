"""
A timetable as iCalendar text, for the subscription feed.

The download is built in the browser by `assets/js/ics-export.js`; a feed is
fetched by calendar servers that run no JavaScript, so the same file has to be
written here as well. This is a port of that file rather than a second design:
the same UIDs, the same weekly rule with exceptions, the same zone, escaping
and folding. `tests/fixtures/ics_golden.ics` is the browser's output for a
fixed timetable, and both suites must reproduce it byte for byte, so the two
cannot drift into describing a class differently.

Standard library only, as the download needs no dependency either.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable

from timetable_extractor.subscription import Note, fnv1a_hex

#: Trinidad and Tobago: UTC-4 all year, no daylight saving.
TZID = "America/Port_of_Spain"
UTC_OFFSET_HOURS = 4

PRODID = "-//UWI Timetable Builder//Timetable Export//EN"
UID_DOMAIN = "timetable.uwi-sta"

#: RFC 5545 folds content lines longer than this many octets.
LINE_OCTETS = 75

DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

VTIMEZONE = (
    "BEGIN:VTIMEZONE",
    f"TZID:{TZID}",
    "BEGIN:STANDARD",
    "DTSTART:19700101T000000",
    "TZOFFSETFROM:-0400",
    "TZOFFSETTO:-0400",
    "TZNAME:AST",
    "END:STANDARD",
    "END:VTIMEZONE",
)


# Text


def escape(value: Any) -> str:
    """Backslash, semicolon, comma and newline (RFC 5545 3.3.11)."""
    text = "" if value is None else str(value)
    text = text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    return re.sub(r"\r\n|\r|\n", "\\\\n", text)


def fold(line: str) -> str:
    """Fold at 75 UTF-8 octets, never inside a character."""
    parts: list[str] = []
    current = ""
    octets = 0
    limit = LINE_OCTETS
    for ch in line:
        size = len(ch.encode("utf-8"))
        if octets + size > limit:
            parts.append(current)
            current = ""
            octets = 0
            limit = LINE_OCTETS - 1
        current += ch
        octets += size
    parts.append(current)
    return "\r\n ".join(parts)


# Dates


def _mins(time: str) -> int:
    hours, _, minutes = (time or "0:0").partition(":")
    return int(hours) * 60 + int(minutes or 0)


def local(day: date, time: str) -> str:
    mins = _mins(time)
    return f"{day:%Y%m%d}T{mins // 60:02d}{mins % 60:02d}00"


def utc(day: date, time: str) -> str:
    """A campus time in UTC, for UNTIL: a fixed four hours, which can cross midnight."""
    mins = _mins(time)
    at = datetime(day.year, day.month, day.day) + timedelta(
        hours=mins // 60 + UTC_OFFSET_HOURS, minutes=mins % 60
    )
    return f"{at:%Y%m%dT%H%M}00Z"


def stamp(at: datetime) -> str:
    return f"{at.astimezone(timezone.utc):%Y%m%dT%H%M%S}Z"


def date_of_teaching_day(week: int, day: str, week_one: date) -> date | None:
    if not isinstance(week, int) or week < 1 or day not in DAYS:
        return None
    return week_one + timedelta(days=(week - 1) * 7 + DAYS.index(day))


# Weeks

_WEEK_TOKEN = re.compile(r"(?:S\d+)?W(\d+)(?:\s*-\s*(?:S\d+)?W?(\d+))?", re.IGNORECASE)


def weeks_from_text(text: str | None) -> list[int]:
    weeks: set[int] = set()
    for match in _WEEK_TOKEN.finditer(str(text or "")):
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else start
        weeks.update(range(min(start, end), max(start, end) + 1))
    return sorted(weeks)


def weeks_of(event: dict[str, Any]) -> list[int]:
    weeks = event.get("weeks")
    if isinstance(weeks, list) and weeks:
        return sorted(set(weeks))
    return weeks_from_text(event.get("weeksRaw"))


@dataclass(frozen=True)
class Recurrence:
    start: date
    rule: str | None
    exdates: tuple[str, ...]


def recurrence(weeks: list[int], day: str, start_time: str, week_one: date) -> Recurrence | None:
    """One weekly rule from the first week to the last, excepting skipped weeks."""
    if not weeks:
        return None
    first, last = weeks[0], weeks[-1]
    start = date_of_teaching_day(first, day, week_one)
    if start is None:
        return None
    if first == last:
        return Recurrence(start, None, ())
    runs = set(weeks)
    exdates = tuple(
        local(date_of_teaching_day(w, day, week_one), start_time)  # type: ignore[arg-type]
        for w in range(first + 1, last)
        if w not in runs
    )
    until = utc(date_of_teaching_day(last, day, week_one), start_time)  # type: ignore[arg-type]
    return Recurrence(start, f"FREQ=WEEKLY;UNTIL={until}", exdates)


# Identity


def uid(entry: dict[str, Any]) -> str:
    """Course, type, group, day and start; a dated one-off also its weeks."""
    key = "|".join(
        [
            str(entry.get("courseKey") or ""),
            entry.get("type") or "",
            entry.get("streamLabel") or "",
            entry.get("day") or "",
            entry.get("startTime") or "",
            ",".join(str(w) for w in entry.get("weeks") or []) if entry.get("dated") else "",
        ]
    )
    return f"{fnv1a_hex(key, 0x811C9DC5)}{fnv1a_hex(key, 0x01000193)}@{UID_DOMAIN}"


# Events


def _rooms(room: str | None) -> list[str]:
    return [r.strip() for r in str(room or "").split(";") if r.strip()]


def _where(rooms: list[str]) -> str:
    if len(rooms) > 1:
        return " / ".join(rooms) + " (check which is yours)"
    return rooms[0] if rooms else ""


def entries(placed: Iterable[dict[str, Any]], dated: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Weekly classes, then dated one-offs with a split exam's rooms joined."""
    out = [
        {**event, "rooms": _rooms(event.get("room")), "weeks": weeks_of(event), "dated": False}
        for event in placed
    ]
    by_key: dict[str, dict[str, Any]] = {}
    for session in dated:
        weeks = weeks_of(session)
        key = "|".join(
            [
                str(session.get("courseKey") or ""),
                str(session.get("type") or ""),
                str(session.get("day") or ""),
                str(session.get("startTime") or ""),
                str(session.get("endTime") or ""),
                ",".join(str(w) for w in weeks),
            ]
        )
        if key not in by_key:
            by_key[key] = {**session, "rooms": [], "weeks": weeks, "dated": True}
        entry = by_key[key]
        for room in _rooms(session.get("room")):
            if room not in entry["rooms"]:
                entry["rooms"].append(room)
    for entry in by_key.values():
        # localeCompare in the browser; codes are ASCII, where the two agree.
        entry["rooms"].sort()
        out.append(entry)
    return out


def _summary(entry: dict[str, Any]) -> str:
    label = entry.get("code") or entry.get("courseKey")
    stream = f"({entry['streamLabel']})" if entry.get("streamLabel") else ""
    return " ".join(part for part in (label, entry.get("type"), stream) if part)


def _description(entry: dict[str, Any], published_label: str, page_url: str) -> str:
    lines = []
    title = entry.get("courseTitle")
    if title and title != entry.get("courseKey"):
        lines.append(title)
    if entry.get("staff"):
        lines.append(", ".join(entry["staff"]))
    if len(entry["rooms"]) > 1:
        lines.append("Held in " + ", ".join(entry["rooms"]) + ". Check which room is yours.")
    if published_label:
        lines.append(f"From UWI's timetable published {published_label}.")
    if page_url:
        lines.append(f"Your timetable: {page_url}")
    return "\n".join(lines)


def _note_lines(note: Note, today: date, dtstamp: str, sequence: int, page_url: str) -> list[str]:
    """An all-day event today, keyed so the next fetch updates it in place."""
    key = f"note|{note.code}|{note.kind}"
    detail = note.detail + (f"\nYour timetable: {page_url}" if page_url else "")
    return [
        "BEGIN:VEVENT",
        f"UID:note-{fnv1a_hex(key)}{fnv1a_hex(key, 0x01000193)}@{UID_DOMAIN}",
        f"DTSTAMP:{dtstamp}",
        f"SEQUENCE:{sequence}",
        f"SUMMARY:{escape(note.summary)}",
        f"DESCRIPTION:{escape(detail)}",
        f"DTSTART;VALUE=DATE:{today:%Y%m%d}",
        f"DTEND;VALUE=DATE:{today + timedelta(days=1):%Y%m%d}",
        "TRANSP:TRANSPARENT",
        "END:VEVENT",
    ]


@dataclass
class Calendar:
    text: str
    events: int
    skipped: list[str]


def build_calendar(
    placed: Iterable[dict[str, Any]],
    dated: Iterable[dict[str, Any]],
    *,
    week_one: date,
    now: datetime,
    publication_id: int | None = None,
    published_label: str = "",
    page_url: str = "",
    name: str = "My UWI timetable",
    refresh_hours: int | None = None,
    notes: Iterable[Note] = (),
    today: date | None = None,
) -> Calendar:
    """
    The whole calendar, as `buildIcsCalendar` in ics-export.js writes it.

    The feed passes `name`, `refresh_hours` and `notes`; left at their
    defaults the output is the browser's download, which is what the shared
    golden file checks.
    """
    dtstamp = stamp(now)
    sequence = publication_id if isinstance(publication_id, int) and publication_id > 0 else 0
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(name)}",
        f"X-WR-TIMEZONE:{TZID}",
    ]
    if refresh_hours:
        # Apple and Outlook read the first, older clients the second.
        lines.append(f"REFRESH-INTERVAL;VALUE=DURATION:PT{refresh_hours}H")
        lines.append(f"X-PUBLISHED-TTL:PT{refresh_hours}H")
    lines.extend(VTIMEZONE)

    skipped: list[str] = []
    used: set[str] = set()
    events = 0
    for entry in entries(placed, dated):
        rec = recurrence(entry["weeks"], entry.get("day") or "", entry.get("startTime") or "", week_one)
        if rec is None or _mins(entry.get("endTime") or "") <= _mins(entry.get("startTime") or ""):
            skipped.append(_summary(entry))
            continue

        base = uid(entry)
        event_uid = base
        n = 2
        while event_uid in used:
            event_uid = base.replace("@", f"-{n}@")
            n += 1
        used.add(event_uid)

        lines.append("BEGIN:VEVENT")
        lines.append(f"UID:{event_uid}")
        lines.append(f"DTSTAMP:{dtstamp}")
        lines.append(f"SEQUENCE:{sequence}")
        lines.append(f"SUMMARY:{escape(_summary(entry))}")
        description = _description(entry, published_label, page_url)
        if description:
            lines.append(f"DESCRIPTION:{escape(description)}")
        where = _where(entry["rooms"])
        if where:
            lines.append(f"LOCATION:{escape(where)}")
        lines.append(f"DTSTART;TZID={TZID}:{local(rec.start, entry['startTime'])}")
        lines.append(f"DTEND;TZID={TZID}:{local(rec.start, entry['endTime'])}")
        if rec.rule:
            lines.append(f"RRULE:{rec.rule}")
        for exdate in rec.exdates:
            lines.append(f"EXDATE;TZID={TZID}:{exdate}")
        lines.append("TRANSP:OPAQUE")
        lines.append("END:VEVENT")
        events += 1

    for note in notes:
        lines.extend(_note_lines(note, today or now.date(), dtstamp, sequence, page_url))
        events += 1

    lines.append("END:VCALENDAR")
    return Calendar("\r\n".join(fold(line) for line in lines) + "\r\n", events, skipped)
