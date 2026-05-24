"""
Text parsing functions for extracting structured data from class blocks.
"""

import re
from typing import Any

from timetable_extractor.config.models import CourseConfig


def parse_block_text(
    block_words: list[dict[str, Any]],
    config: Any | None = None,
) -> dict[str, Any]:
    """
    Parse the text words of a class block into structured fields.

    CELCAT blocks can be narrow, causing each word to render on its own line.
    Strategy:
      1. Reconstruct physical lines from y-position grouping.
      2. Join everything into a single normalised string.
      3. Repair hyphen-split week tokens (e.g. "S2W7- S2W12" -> "S2W7-S2W12").
      4. Use keyword anchors (Course: / Staff: / Room:) to slice out values
         even when the value wraps across several lines.
    """
    # -- Build physical lines --
    lines_map: dict[int, list[str]] = {}
    for w in block_words:
        key = round(w["top"])
        lines_map.setdefault(key, []).append(w["text"])

    lines = [" ".join(v) for _, v in sorted(lines_map.items())]
    raw_text = "\n".join(lines)

    joined = " ".join(lines)
    # Repair split week tokens: "S2W7- S2W12" -> "S2W7-S2W12"
    joined = re.sub(r"(S\d+W\d+)-\s+(S\d+W\d+)", r"\1-\2", joined)

    result: dict[str, Any] = {
        "type": None,
        "weeks": None,
        "week_count": None,
        "course": None,
        "staff": None,
        "room": None,
        "group_label": None,
        "raw_text": raw_text,
    }

    # Get patterns from config if available
    patterns = None
    if config is not None and isinstance(config, CourseConfig) and config.text_patterns:
        patterns = config.text_patterns

    # Type detection — use config activity_types if available
    if patterns and patterns.activity_types:
        for at in patterns.activity_types:
            if re.search(rf"\b{re.escape(at)}\b", joined, re.I):
                result["type"] = at
                break
    else:
        if re.search(r"\bLecture\b", joined, re.I):
            result["type"] = "Lecture"
        elif re.search(r"\bLab\b", joined, re.I):
            result["type"] = "Lab"
        elif re.search(r"\bTutorial\b", joined, re.I):
            result["type"] = "Tutorial"
        elif re.search(r"\bPostgraduate\b", joined, re.I):
            result["type"] = "Postgraduate"

    # Weeks: "S2W7-S2W12" or "SUM W1-SUM W7" (after repair above)
    wk = re.search(r"(S\d+W\d+-S\d+W\d+)", joined)
    if not wk:
        wk = re.search(r"(SUM W\d+-SUM W\d+)", joined)
    if wk:
        result["weeks"] = wk.group(1)

    # Week count: [=6]
    wc = re.search(r"\[=(\d+)\]", joined)
    if wc:
        result["week_count"] = int(wc.group(1))

    # Group label: (L1)
    gl = re.search(r"\(L(\d+)\)", joined)
    if gl:
        result["group_label"] = f"L{gl.group(1)}"

    # Captures everything between a keyword and the next keyword (or end).
    KEYWORDS = ["Course", "Staff", "Room"]
    kw_pattern = "|".join(KEYWORDS)
    # Split on keyword boundaries
    segments = re.split(rf"({kw_pattern}):\s*", joined)
    # segments is: [pre, key1, val1, key2, val2, ...]
    for i in range(1, len(segments) - 1, 2):
        key = segments[i].strip()
        val = segments[i + 1].strip()
        # Strip any trailing week/label/noise
        val = re.split(r"\s*(?:Wks|\[=|\(L\d)", val)[0].strip()
        if key == "Course":
            result["course"] = val or None
        elif key == "Staff":
            result["staff"] = val or None
        elif key == "Room":
            # Clean trailing orphan tokens (single letters like W, E direction suffixes)
            cleaned = re.sub(r"\s+[A-Z0-9]\s*$", "", val).strip()
            result["room"] = cleaned or None

    return result
