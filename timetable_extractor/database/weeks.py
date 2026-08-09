"""
Expand CELCAT week strings into explicit week numbers.

Storing the expanded set is what makes "which classes run in week 8" an index
lookup instead of string parsing, and it is the only way to tell whether two
classes that clash on the calendar actually collide in the same weeks.
"""

from __future__ import annotations

import re

# "W1", "S2W7" (semester-prefixed) and "SUM W1" (summer session) all appear.
# Only the trailing number identifies the teaching week.
_TOKEN = re.compile(r"(?:SUM\s*)?(?:S\d+)?W(\d+)", re.I)


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
