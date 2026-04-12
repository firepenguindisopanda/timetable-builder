"""
Class block detection functions for timetable extraction.
"""

from typing import Any

from timetable_extractor.constants import DAY_LABEL_X_MAX, MAX_BLOCK_HEIGHT


def identify_class_blocks(
    words: list[dict[str, Any]], rects: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """
    Each class block has 1-2 filled highlight rectangles at its top.
    Group those rects by x AND y proximity to find distinct blocks
    (same x range but different day rows must NOT be merged).

    Returns list of raw word groups (one per class block).
    """
    # Filled rects = highlight bars on class header rows
    filled = [r for r in rects if r.get("fill") and r["x0"] > 50 and r["width"] > 20]

    # Cluster filled rects into blocks by BOTH x-range overlap AND y-proximity.
    # Two rects belong to the same block only if they overlap in x AND are
    # within ~30 pts vertically (stacked header lines within one block).
    clusters: list[dict[str, float]] = []
    for r in sorted(filled, key=lambda r: (r["top"], r["x0"])):
        merged = False
        for c in clusters:
            x_overlap = r["x0"] < c["x1"] + 5 and r["x1"] > c["x0"] - 5
            y_close = abs(r["top"] - c["bottom"]) < 30  # <- new constraint
            if x_overlap and y_close:
                c["x0"] = min(c["x0"], r["x0"])
                c["x1"] = max(c["x1"], r["x1"])
                c["top"] = min(c["top"], r["top"])
                c["bottom"] = max(c["bottom"], r["bottom"])
                merged = True
                break
        if not merged:
            clusters.append(
                {"x0": r["x0"], "x1": r["x1"], "top": r["top"], "bottom": r["bottom"]}
            )

    # For each cluster find y-bottom: next cluster in same x column, or cap.
    clusters_sorted = sorted(clusters, key=lambda c: (c["x0"], c["top"]))

    def get_y_bottom(c: dict[str, float]) -> float:
        same_col_below = [
            other["top"]
            for other in clusters_sorted
            if other is not c
            and abs(other["x0"] - c["x0"]) < 10
            and other["top"] > c["top"]
        ]
        return (
            (min(same_col_below) - 2)
            if same_col_below
            else (c["top"] + MAX_BLOCK_HEIGHT)
        )

    blocks: list[dict[str, Any]] = []
    for c in clusters:
        y_bottom = get_y_bottom(c)
        block_words = [
            w
            for w in words
            if w["x0"] >= c["x0"] - 5
            and w["x1"] <= c["x1"] + 10
            and w["top"] >= c["top"] - 5
            and w["top"] <= y_bottom
            and w["top"] < 560
            and w["x0"] > DAY_LABEL_X_MAX
        ]
        if block_words:
            blocks.append(
                {
                    "x0": c["x0"],
                    "x1": c["x1"],
                    "y_top": min(w["top"] for w in block_words),
                    "words": sorted(block_words, key=lambda w: (w["top"], w["x0"])),
                }
            )

    return blocks
