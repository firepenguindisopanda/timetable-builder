"""
Expand CELCAT week strings into explicit week numbers.

Storing the expanded set is what makes "which classes run in week 8" an index
lookup instead of string parsing, and it is the only way to tell whether two
classes that clash on the calendar actually collide in the same weeks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Iterable

# "W1", "S2W7" (semester-prefixed) and "SUM W1" (summer session) all appear.
# Only the trailing number identifies the teaching week.
_TOKEN = re.compile(r"(?:SUM\s*)?(?:S\d+)?W(\d+)", re.I)

#: The range an export covers, as CELCAT prints it at the end of every PDF
#: title: "Course timetable - ACCT 1003, Intro. to Cost ... (Wks W2-W12)".
_TITLE_RANGE = re.compile(r"\(\s*Wks?\s+(?:SUM\s*)?(?:S\d+)?W(\d+)", re.I)

#: A date range in a title, "31-Aug-26 - 16-Nov-26". Only the "Inspection
#: Copy" template prints one, and it exports the whole semester.
_TITLE_DATES = re.compile(r"\d{1,2}-[A-Za-z]{3}-\d{2}\s*-\s*\d{1,2}-[A-Za-z]{3}-\d{2}")


def expand_weeks(weeks_raw: str | None) -> list[int]:
    """
    Turn a week expression into a sorted list of week numbers.

        "W1-W11"           -> [1..11]
        "W1-W7, W9-W12"    -> [1..7, 9..12]
        "W1, W3, W5"       -> [1, 3, 5]
        "W8"               -> [8]
        "S2W7-S2W12"       -> [7..12]

    Unparseable input yields an empty list rather than raising: a malformed
    week string should not stop a session being recorded.
    """
    if not weeks_raw:
        return []

    found: set[int] = set()
    for part in weeks_raw.split(","):
        numbers = [int(m.group(1)) for m in _TOKEN.finditer(part)]
        if not numbers:
            continue
        if len(numbers) >= 2 and "-" in part:
            start, end = numbers[0], numbers[1]
            if start <= end:
                found.update(range(start, end + 1))
            else:
                # Reversed range ("W12-W1") is a typo upstream; keep the ends
                # rather than silently dropping the session's weeks entirely.
                found.update({start, end})
        else:
            found.update(numbers)

    return sorted(found)


def weeks_overlap(a: str | None, b: str | None) -> bool:
    """
    Whether two week expressions share at least one teaching week.

    An unknown expression is treated as overlapping: better to warn about a
    clash that may not exist than to hide one that does.
    """
    weeks_a, weeks_b = expand_weeks(a), expand_weeks(b)
    if not weeks_a or not weeks_b:
        return True
    return bool(set(weeks_a) & set(weeks_b))


def export_horizon(title: str | None) -> int | None:
    """
    The first teaching week a PDF covers, read from its title.

    CELCAT exports each timetable from the current teaching week to the end of
    the semester, and prints the range it chose: every PDF pulled on
    11 September 2026, in week 2, was titled "(Wks W2-W12)". A class's own
    weeks therefore lose a week every time the site is republished, which is
    a fact about the export and not about the class. Course, staff and room
    PDFs all carry it.

    Returns None when the title has no range, so a caller cannot mistake a
    missing horizon for week 1. Also None for a title that prints the
    semester's dates, "(Wks W1-W12 (Semester 1), 31-Aug-26 - 16-Nov-26)": that
    template exports the whole semester whatever the current week, so its W1
    says nothing about which weeks have passed. PHPP 0301 arrived in it in
    week 5 (29 Sep 2026), and read as W1 it dragged the corpus's lowest
    horizon down with it, so the diff counted every class that had finished
    in W3-W4 as removed.
    """
    if not title or _TITLE_DATES.search(title):
        return None
    match = _TITLE_RANGE.search(title)
    return int(match.group(1)) if match else None


def render_weeks(weeks: Iterable[int]) -> str | None:
    """
    Write a set of week numbers the way CELCAT prints them.

        [1..12]          -> "W1-W12"
        [1..7, 9..12]    -> "W1-W7, W9-W12"
        [1, 3, 5]        -> "W1, W3, W5"

    The inverse of `expand_weeks` for every week string in the warehouse as of
    publication 8, which is what lets a reconstructed range be compared with
    one CELCAT printed.
    """
    runs: list[list[int]] = []
    for week in sorted(set(weeks)):
        if runs and week == runs[-1][1] + 1:
            runs[-1][1] = week
        else:
            runs.append([week, week])
    if not runs:
        return None
    return ", ".join(f"W{a}" if a == b else f"W{a}-W{b}" for a, b in runs)


@dataclass(frozen=True)
class Term:
    """What the site needs to know about one semester, from UWI's calendar."""

    #: Monday of teaching week 1.
    week_one: date
    #: How many teaching weeks the semester has. Bounds week numbering for
    #: the term, as `TOTAL_WEEKS` did for semester 1 alone.
    teaching_weeks: int
    #: The last teaching day.
    teaching_ends: date
    #: First and last day of the examination period.
    exams: tuple[date, date]


#: Each term's dates, by academic year and semester number. CELCAT publishes
#: week numbers and never dates, so these are typed in from UWI's academic
#: calendar (academiccalendar.pdf, revised July 2026) rather than parsed from
#: it: one page that changes once a year, where a misread date would put every
#: class on the wrong day. Semester 1 2026/27 was settled on 22 Sep 2026
#: (ICS-EXPORT-SPEC 3.3) and confirmed by the Inspection Copy title
#: "31-Aug-26 - 16-Nov-26"; its teaching began on Tue 1 Sep, but week 1 is the
#: week of Mon 31 Aug. Semester 2 prints S2W1-S2W13, and the calendar agrees:
#: 13 weeks. A term missing here is not guessed at; the calendar falls back
#: to an undated week. SEMESTERS-SPEC.md section 4.
TERMS: dict[tuple[str, int], Term] = {
    ("2026/2027", 1): Term(
        week_one=date(2026, 8, 31),
        teaching_weeks=12,
        teaching_ends=date(2026, 11, 20),
        exams=(date(2026, 12, 1), date(2026, 12, 22)),
    ),
    ("2026/2027", 2): Term(
        week_one=date(2027, 1, 18),
        teaching_weeks=13,
        teaching_ends=date(2027, 4, 16),
        exams=(date(2027, 4, 26), date(2027, 5, 14)),
    ),
}

#: "Semester_1_TT2026_2027", "Semester_I_2026_2027" and "Semester_I_2026_2027_"
#: are the three spellings of one semester CELCAT used in four publications.
#: The semester 2 inspection copy of 26 Nov 2026 added a fourth,
#: "Inspection_Sem_2_2026_2027": with `Semester` required it gave no term, and
#: the builder could not date a single week. The same pattern backfills
#: publications' terms in schema.sql, so the two must not drift.
_SEMESTER = re.compile(
    r"Sem(?:ester)?[_\s]*(III|II|I|\d)[_\s]*(?:TT)?[_\s]*(\d{4})[_\s]*(\d{4})", re.I
)
_ROMAN = {"I": 1, "II": 2, "III": 3}

#: A label CELCAT gives a draft published for checking.
_INSPECTION = re.compile(r"^\s*Inspection", re.I)


def semester_key(label: str | None) -> tuple[str, int] | None:
    """
    A semester label reduced to (academic year, semester number).

    Keyed this way rather than on the label itself because the label drifts:
    a table keyed on "Semester_I_2026_2027" would have stopped dating the
    timetable the week CELCAT went back to "Semester_1_TT2026_2027".
    """
    match = _SEMESTER.search(label or "")
    if not match:
        return None
    number, first, second = match.groups()
    semester = _ROMAN.get(number.upper()) or int(number)
    return f"{first}/{second}", semester


def publication_stage(label: str | None) -> str:
    """
    `inspection` for UWI's draft published for checking, `final` otherwise.

    A final timetable outranks any inspection copy of the same term
    (`term_publication` in schema.sql), so this decides which one students
    are served once both exist.
    """
    return "inspection" if _INSPECTION.match(label or "") else "final"


def teaching_start(label: str | None) -> date | None:
    """Monday of teaching week 1 for a semester label, or None when unknown."""
    key = semester_key(label)
    term = TERMS.get(key) if key else None
    return term.week_one if term else None
