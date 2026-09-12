"""
Expand CELCAT week strings into explicit week numbers.

Storing the expanded set is what makes "which classes run in week 8" an index
lookup instead of string parsing, and it is the only way to tell whether two
classes that clash on the calendar actually collide in the same weeks.
"""

from __future__ import annotations

import re
from typing import Iterable

# "W1", "S2W7" (semester-prefixed) and "SUM W1" (summer session) all appear.
# Only the trailing number identifies the teaching week.
_TOKEN = re.compile(r"(?:SUM\s*)?(?:S\d+)?W(\d+)", re.I)

#: The range an export covers, as CELCAT prints it at the end of every PDF
#: title: "Course timetable - ACCT 1003, Intro. to Cost ... (Wks W2-W12)".
_TITLE_RANGE = re.compile(r"\(\s*Wks?\s+(?:SUM\s*)?(?:S\d+)?W(\d+)", re.I)


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
    missing horizon for week 1.
    """
    if not title:
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
