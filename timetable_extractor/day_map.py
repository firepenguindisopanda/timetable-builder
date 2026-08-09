"""
Day mapping functions for timetable extraction.
"""

from typing import Any

from timetable_extractor.config.models import CourseConfig
from timetable_extractor.constants import (
    REVERSED_DAYS,
    DAY_LABEL_X_MAX,
    RULE_MIN_WIDTH_RATIO,
    ROW_TOP_TOLERANCE,
    Y_TOLERANCE,
)

# Matched case-insensitively: a single wrong-case key silently drops a whole
# day's classes, and the reversed labels are distinctive enough that
# case-folding cannot collide.
_REVERSED_DAYS_CI = {k.lower(): v for k, v in REVERSED_DAYS.items()}


def horizontal_rules(lines: list[dict[str, Any]], page_width: float) -> list[float]:
    """
    Return the y positions of the full-width rules that delimit day rows.

    CELCAT draws these as the timetable grid, so they are the authoritative
    row boundaries - far more reliable than inferring a row's extent from
    where its label happens to sit.
    """
    return sorted(
        {
            round(line["top"], 1)
            for line in lines
            if abs(line["top"] - line["bottom"]) < 0.6
            and line["x1"] - line["x0"] > page_width * RULE_MIN_WIDTH_RATIO
        }
    )


def _rows_from_rules(
    labels: list[tuple[float, float, str]], rules: list[float]
) -> list[tuple[float, float, str]]:
    """
    Widen each day label to the full grid row that contains it.

    A label is vertically centred in its row, so the row it belongs to is the
    pair of consecutive rules straddling the label's centre.
    """
    rows: list[tuple[float, float, str]] = []
    for y_top, y_bottom, day in labels:
        centre = (y_top + y_bottom) / 2
        for lo, hi in zip(rules, rules[1:]):
            if lo <= centre < hi:
                rows.append((lo, hi, day))
                break
        else:
            rows.append((y_top, y_bottom, day))
    return rows


def build_day_y_map(
    words: list[dict[str, Any]],
    config: Any | None = None,
    page_width: float | None = None,
    page_height: float | None = None,
    lines: list[dict[str, Any]] | None = None,
) -> list[tuple[float, float, str]]:
    """
    Return a sorted list of (y_top, y_bottom, day_name) day bands.

    Day labels live on the far left (x0 < DAY_LABEL_X_MAX). When the page's
    grid `lines` are supplied, each band is widened to the full grid row, which
    is what a class block actually occupies; otherwise the label's own extent
    is returned and y_to_day falls back to proximity matching.
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
            day = _REVERSED_DAYS_CI.get(w["text"].lower())
            if day:
                day_entries.append((w["top"], w["bottom"], day))
    day_entries.sort(key=lambda e: e[0])

    if lines and page_width:
        rules = horizontal_rules(lines, page_width)
        if rules:
            return _rows_from_rules(day_entries, rules)
    return day_entries


def y_to_day(y: float, day_map: list[tuple[float, float, str]]) -> str:
    """
    Map a block y coordinate to a day.

    With grid-derived rows the block simply falls inside one of them. The
    tolerance covers a highlight bar drawn a hair above its row's rule.
    """
    if not day_map:
        return "Unknown"

    for y_top, y_bottom, day in day_map:
        if y_top - ROW_TOP_TOLERANCE <= y < y_bottom:
            return day

    # Fallback for label-only bands (no grid lines available): the last label
    # starting at or just below the block. The tolerance must stay small - a
    # large one lets a block low in a tall row reach into the next day.
    best_day = day_map[0][2]
    for y_top, _, day in day_map:
        if y_top <= y + Y_TOLERANCE:
            best_day = day
        else:
            break
    return best_day
