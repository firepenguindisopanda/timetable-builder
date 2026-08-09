"""
Text parsing functions for extracting structured data from class blocks.
"""

import re
from typing import Any

from timetable_extractor.config.models import CourseConfig
from timetable_extractor.constants import ACTIVITY_TYPES, PARAGRAPH_GAP

# A single week token, covering every form CELCAT emits:
#   "W1" (semester-relative, current format), "S2W7" (semester-prefixed),
#   "SUM W1" (summer session).
_WEEK_TOKEN = r"(?:SUM\s+)?(?:S\d+)?W\d+"

# One range ("W1-W11") or a lone week ("W8").
_WEEK_RANGE = rf"{_WEEK_TOKEN}(?:\s*-\s*{_WEEK_TOKEN})?"

# The full value after a "Wks"/"Wk" label, including comma-separated
# multi-ranges such as "W1-W7, W9-W12".
_WEEKS_LABELLED = re.compile(rf"\bWks?\s+({_WEEK_RANGE}(?:\s*,\s*{_WEEK_RANGE})*)")

# Fallback for blocks that carry a range with no "Wks" label.
_WEEKS_BARE = re.compile(rf"((?:S\d+W\d+|SUM\s+W\d+)\s*-\s*(?:S\d+W\d+|SUM\s+W\d+))")

# Field labels. CELCAT uses the plural when a block covers several courses or
# rooms ("Courses: CHEM 1075; CHEM 1080").
_FIELD_LABEL = re.compile(r"\b(Courses?|Staff|Rooms?):")
_FIELD_SPLIT = re.compile(r"\b(Courses?|Staff|Rooms?):\s*")

# Stream markers: (L1) lab group, (T1) tutorial group, (G1) generic group.
_GROUP_LABEL = re.compile(r"\(([LTG]\d+)\)")
# A marker rendered on its own line carries no information once captured.
_GROUP_LABEL_ONLY = re.compile(r"^\(?[LTG]\d+\)?$")

# The activity type is whatever precedes the first comma on a block's first
# line: "Lecture, Wks W1-W12 [=12]".
_TYPE_PREFIX = re.compile(r"\s*([A-Za-z][A-Za-z ()/&'.-]{1,40}?),")

# Canonical types keyed by their de-spaced, case-folded form, so that a type
# split across narrow lines ("Postgradua te") still resolves.
_CANONICAL_TYPES = {t.replace(" ", "").lower(): t for t in ACTIVITY_TYPES}


def _despace(text: str) -> str:
    return re.sub(r"\s+", "", text).lower()


def canonical_activity_type(raw: str) -> str | None:
    """Resolve a raw type prefix to a known activity type, or None."""
    return _CANONICAL_TYPES.get(_despace(raw))


def group_lines(block_words: list[dict[str, Any]]) -> list[tuple[float, str]]:
    """Rebuild physical lines from word y-positions, as (top, text)."""
    lines_map: dict[int, list[tuple[float, str]]] = {}
    for w in block_words:
        lines_map.setdefault(round(w["top"]), []).append((w["x0"], w["text"]))
    return [
        (float(top), " ".join(text for _, text in sorted(words)))
        for top, words in sorted(lines_map.items())
    ]


def group_paragraphs(lines: list[tuple[float, str]]) -> list[str]:
    """
    Group physical lines into logical paragraphs.

    A wrapped value continues 9-11pt below its previous line, while a new
    logical group - the header, a "Course:" label, or a trailing free-text note
    - starts at least PARAGRAPH_GAP below. Splitting on that boundary is what
    keeps note text ("Lecture when there is no Lab/Field Trip in that week")
    out of the room and course fields.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    prev_top: float | None = None
    for top, text in lines:
        if prev_top is not None and top - prev_top >= PARAGRAPH_GAP and current:
            paragraphs.append(" ".join(current))
            current = []
        current.append(text)
        prev_top = top
    if current:
        paragraphs.append(" ".join(current))
    return paragraphs


def _repair_split_weeks(text: str) -> str:
    """Rejoin week tokens broken across lines: "W1- W11" -> "W1-W11"."""
    return re.sub(rf"({_WEEK_TOKEN})-\s+({_WEEK_TOKEN})", r"\1-\2", text)


def parse_block_text(
    block_words: list[dict[str, Any]],
    config: Any | None = None,
) -> dict[str, Any]:
    """
    Parse the text words of a class block into structured fields.

    CELCAT blocks can be narrow, causing each word to render on its own line.
    Strategy:
      1. Reconstruct physical lines from y-position grouping.
      2. Group those lines into paragraphs so trailing free-text notes can be
         separated from field values.
      3. Read the activity type from the first paragraph's comma prefix.
      4. Use keyword anchors (Course: / Staff: / Room:) to slice out values
         even when the value wraps across several lines.
    """
    lines = group_lines(block_words)
    raw_text = "\n".join(text for _, text in lines)
    paragraphs = group_paragraphs(lines)

    result: dict[str, Any] = {
        "type": None,
        "weeks": None,
        "week_count": None,
        "course": None,
        "staff": None,
        "room": None,
        "group_label": None,
        "notes": None,
        "raw_text": raw_text,
    }
    if not paragraphs:
        return result

    # -- Separate field-bearing paragraphs from trailing notes --
    # The first paragraph is always the header (type + weeks), so it is never a
    # note even though it carries no field label. Any *later* paragraph without
    # a label is a free-text note from the timetabler. Short blocks have no
    # internal gaps at all, in which case the single paragraph is both.
    header = paragraphs[0]
    field_paragraphs = [p for p in paragraphs if _FIELD_LABEL.search(p)]
    note_paragraphs = [p for p in paragraphs[1:] if not _FIELD_LABEL.search(p)]

    joined = _repair_split_weeks(" ".join([header] + field_paragraphs))
    # The stream marker is sometimes laid out as its own paragraph, so look for
    # it across the whole block rather than just the field text.
    all_text = _repair_split_weeks(" ".join(paragraphs))
    result["notes"] = (
        " ".join(p for p in note_paragraphs if not _GROUP_LABEL_ONLY.match(p.strip())).strip()
        or None
    )

    # -- Activity type --
    # A configured type list wins; otherwise read the header's comma prefix,
    # which covers every type CELCAT publishes rather than a hardcoded few.
    patterns = None
    if config is not None and isinstance(config, CourseConfig) and config.text_patterns:
        patterns = config.text_patterns

    if patterns and patterns.activity_types:
        for at in patterns.activity_types:
            if re.search(rf"\b{re.escape(at)}\b", joined, re.I):
                result["type"] = at
                break
    else:
        prefix = _TYPE_PREFIX.match(_repair_split_weeks(header))
        if prefix:
            raw_type = prefix.group(1).strip()
            # Fall back to the literal prefix so new types still surface
            # instead of silently becoming None.
            result["type"] = canonical_activity_type(raw_type) or raw_type

    # -- Weeks: "W1-W11", "W1-W7, W9-W12", "S2W7-S2W12", "SUM W1-SUM W7" --
    # Prefer the labelled form so stray ranges elsewhere in the block are ignored.
    wk = _WEEKS_LABELLED.search(joined) or _WEEKS_BARE.search(joined)
    if wk:
        result["weeks"] = wk.group(1).strip()

    # Week count: [=6]
    wc = re.search(r"\[=(\d+)\]", joined)
    if wc:
        result["week_count"] = int(wc.group(1))

    # Stream label: (L1) lab, (T1) tutorial, (G1) group. Students pick one
    # stream per course, so all three families matter for conflict resolution.
    gl = _GROUP_LABEL.search(all_text)
    if gl:
        result["group_label"] = gl.group(1).upper()

    # -- Keyword-anchored fields --
    # Captures everything between a label and the next label (or end of text).
    segments = _FIELD_SPLIT.split(" ".join(field_paragraphs))
    # segments is: [pre, key1, val1, key2, val2, ...]
    for i in range(1, len(segments) - 1, 2):
        # "Courses"/"Rooms" -> singular key; "Staff" is unchanged by rstrip("s").
        key = segments[i].strip().rstrip("s").lower()
        val = segments[i + 1].strip()
        # Strip trailing week/label/noise. Text from a neighbouring block can
        # bleed in, so also cut at a bare week range ("FSS 103 W1-W12 [=12]").
        # The leading \b matters: without it "Wk" matches inside a course code
        # such as "SOWK 2004" and truncates it to "SO".
        val = re.split(
            rf"\s*(?:\bWks?\b|\[=|\([LTG]\d|{_WEEK_TOKEN}\s*-\s*{_WEEK_TOKEN})", val
        )[0].strip()
        if key == "course":
            result["course"] = val or None
        elif key == "staff":
            result["staff"] = val or None
        elif key == "room":
            # NB: do not strip a trailing single letter. Those are part of real
            # room names - "TLC LT B", "FFA A", and the "FSS 101 W" / "FSS 101 E"
            # west/east wings are all distinct rooms in CELCAT's room registry.
            result["room"] = val or None

    return result
