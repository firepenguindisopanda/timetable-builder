"""
Day mapping functions for timetable extraction.
"""

from typing import Any

from timetable_extractor.config.models import CourseConfig
from timetable_extractor.constants import REVERSED_DAYS, DAY_LABEL_X_MAX, Y_TOLERANCE


def build_day_y_map(
    words: list[dict[str, Any]],
    config: Any | None = None,
    page_width: float | None = None,
    page_height: float | None = None,
) -> list[tuple[float, float, str]]:
    """
    Return a sorted list of (y_top, y_bottom, day_name) from rotated day labels.
    Day labels live on the far left (x0 < DAY_LABEL_X_MAX).
    """
    day_label_x_max = DAY_LABEL_X_MAX
    if config is not None and page_width is not None and isinstance(config, CourseConfig):
        col_lefts: list[float] = []
        for day_attr in ("monday", "tuesday", "wednesday", "thursday", "friday"):
            col = getattr(config.day_columns, day_attr, None)
            if col is not None and col.left is not None:
                col_lefts.append(col.left * page_width)
        if col_lefts:
            day_label_x_max = min(day_label_x_max, min(col_lefts) - 5)

    day_entries: list[tuple[float, float, str]] = []
    for w in words:
        if w["x0"] < day_label_x_max and w["x1"] < day_label_x_max + 20:
            day = REVERSED_DAYS.get(w["text"])
            if day:
                day_entries.append((w["top"], w["bottom"], day))
    day_entries.sort(key=lambda e: e[0])
    return day_entries


def y_to_day(y: float, day_map: list[tuple[float, float, str]]) -> str:
    """
    Map a block y coordinate to a day.
    CELCAT blocks often start a few pixels above the rotated day label,
    so we find the LAST day label whose y_top <= block_y + TOLERANCE.
    """
    if not day_map:
        return "Unknown"
    best_day = day_map[0][2]
    for y_top, y_bottom, day in day_map:
        if y_top <= y + Y_TOLERANCE:
            best_day = day
        else:
            break
    return best_day
