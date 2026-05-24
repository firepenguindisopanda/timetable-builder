"""
Time parsing and mapping functions for timetable extraction.
"""

import re
from typing import Any

from timetable_extractor.config.models import CourseConfig
from timetable_extractor.constants import TIME_HEADER_Y_RANGE


def parse_time(t: str) -> str:
    """Normalise a time string like '08:00AM' -> '08:00 AM'."""
    t = t.strip()
    match = re.match(r"(\d{1,2}):(\d{2})(AM|PM)", t, re.IGNORECASE)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)} {match.group(3).upper()}"
    return t


def build_time_x_map(
    words: list[dict[str, Any]],
    config: Any | None = None,
    page_width: float | None = None,
    page_height: float | None = None,
) -> list[tuple[float, float, str]]:
    """
    Return a sorted list of (x_start, x_end, time_label) tuples
    derived from the time-header row of the page.
    """
    time_y_min, time_y_max = TIME_HEADER_Y_RANGE
    if config is not None and page_height is not None and isinstance(config, CourseConfig) and config.time_slot_map:
        y_vals: list[float] = []
        for ts in config.time_slot_map:
            if ts.top is not None and ts.bottom is not None:
                y_vals.append(ts.top * page_height)
                y_vals.append(ts.bottom * page_height)
        if y_vals:
            time_y_min = min(y_vals)
            time_y_max = max(y_vals)

    time_words = [
        w
        for w in words
        if time_y_min <= w["top"] <= time_y_max
        and re.match(r"\d{2}:\d{2}[AP]M", w["text"])
    ]
    time_words.sort(key=lambda w: w["x0"])

    slots: list[tuple[float, float, str]] = []
    for i, tw in enumerate(time_words):
        x_start = tw["x0"]
        x_end = time_words[i + 1]["x0"] if i + 1 < len(time_words) else tw["x1"] + 50
        slots.append((x_start, x_end, parse_time(tw["text"])))
    return slots


def x_to_time(x: float, slots: list[tuple[float, float, str]]) -> str | None:
    """Map an x coordinate to the nearest time label."""
    best: str | None = None
    best_dist = float("inf")
    for x_start, x_end, label in slots:
        dist = abs(x - x_start)
        if dist < best_dist:
            best_dist = dist
            best = label
    return best


def x_range_to_times(
    x0: float, x1: float, slots: list[tuple[float, float, str]]
) -> tuple[str, str]:
    """Return (start_time, end_time) for a class block spanning x0..x1."""
    start = x_to_time(x0, slots)
    # end time = the slot whose x_start is nearest x1
    end_time: str | None = None
    best_dist = float("inf")
    for x_start, x_end, label in slots:
        dist = abs(x1 - x_start)
        if dist < best_dist:
            best_dist = dist
            end_time = label
    return start or "?", end_time or "?"
