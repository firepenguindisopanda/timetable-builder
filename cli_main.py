"""
CELCAT Timetable PDF Extractor
Extracts structured class data (day, start time, end time, type, course,
staff, room, label) from CELCAT-generated timetable PDFs.

Usage:
    python extract_celcat.py <path_to_pdf> [<path_to_pdf2> ...]
    
    Or import and call extract_timetable(pdf_path) directly.
"""

import pdfplumber
import re
import json
import sys
from pathlib import Path



# Day names are rendered rotated/reversed in CELCAT PDFs
REVERSED_DAYS = {
    "yadnoM": "Monday",
    "yadseuT": "Tuesday",
    "yadsendew": "Wednesday", # full
    "eW": "Wednesday", # abbreviated (as seen on page)
    "yadsruhT": "Thursday",
    "uhT": "Thursday", # abbreviated
    "yadirF": "Friday",
    "yadrutaS": "Saturday",
    "taS": "Saturday", # abbreviated
    "yadnuS": "Sunday",
    "nuS": "Sunday", # abbreviated
}

# Time header x-positions are consistent across CELCAT PDFs.
# We build this dynamically from the PDF, but this is the expected pattern.
TIME_HEADER_Y_RANGE = (90, 115)  # y band where time headers appear
DAY_LABEL_X_MAX = 60 # day labels always appear left of this x



def parse_time(t: str) -> str:
    """Normalise a time string like '08:00AM' - '08:00 AM'."""
    t = t.strip()
    match = re.match(r"(\d{1,2}):(\d{2})(AM|PM)", t, re.IGNORECASE)
    if match:
        return f"{int(match.group(1)):02d}:{match.group(2)} {match.group(3).upper()}"
    return t


def build_time_x_map(words: list) -> list[tuple[float, float, str, int]]:
    """
    Return a sorted list of (x_start, x_end, time_label, index) tuples
    derived from the time-header row of the page.

    The index is the slot order from left-to-right (0 = first slot).
    """
    time_words = [
        w for w in words
        if TIME_HEADER_Y_RANGE[0] <= w["top"] <= TIME_HEADER_Y_RANGE[1]
        and re.match(r"\d{2}:\d{2}[AP]M", w["text"])
    ]
    time_words.sort(key=lambda w: w["x0"])

    slots = []
    for i, tw in enumerate(time_words):
        x_start = tw["x0"]
        x_end = time_words[i + 1]["x0"] if i + 1 < len(time_words) else tw["x1"] + 50
        slots.append((x_start, x_end, parse_time(tw["text"]), i))
    return slots


def x_to_slot(x: float, slots: list) -> tuple[str | None, float | None, float | None, int | None]:
    """Map an x coordinate to the nearest time slot (label + boundaries + index)."""
    best = (None, None, None, None)
    best_dist = float("inf")
    for x_start, x_end, label, idx in slots:
        dist = abs(x - x_start)
        if dist < best_dist:
            best_dist = dist
            best = (label, x_start, x_end, idx)
    return best


def x_range_to_times(x0: float, x1: float, slots: list) -> tuple[str, str, dict, dict]:
    """Return (start_time, end_time, start_slot, end_slot) for a class block."""
    start_label, start_x0, start_x1, start_idx = x_to_slot(x0, slots)
    end_label, end_x0, end_x1, end_idx = x_to_slot(x1, slots)

    start_slot = {
        "label": start_label or "?",
        "x0": start_x0,
        "x1": start_x1,
        "index": start_idx,
    }
    end_slot = {
        "label": end_label or "?",
        "x0": end_x0,
        "x1": end_x1,
        "index": end_idx,
    }

    return (start_label or "?", end_label or "?", start_slot, end_slot)


def build_day_y_map(words: list) -> list[tuple[float, float, str]]:
    """
    Return a sorted list of (y_top, y_bottom, day_name) from rotated day labels.
    Day labels live on the far left (x0 < DAY_LABEL_X_MAX).
    """
    day_entries = []
    for w in words:
        if w["x0"] < DAY_LABEL_X_MAX and w["x1"] < DAY_LABEL_X_MAX + 20:
            day = REVERSED_DAYS.get(w["text"])
            if day:
                day_entries.append((w["top"], w["bottom"], day))
    day_entries.sort(key=lambda e: e[0])
    return day_entries


def y_to_day(y: float, day_map: list) -> str:
    """
    Map a block y coordinate to a day.
    CELCAT blocks often start a few pixels above the rotated day label,
    so we find the LAST day label whose y_top <= block_y + TOLERANCE.
    """
    TOLERANCE = 50
    if not day_map:
        return "Unknown"
    best_day = day_map[0][2]
    for y_top, _, day in day_map:
        if y_top <= y + TOLERANCE:
            best_day = day
        else:
            break
    return best_day


def identify_class_blocks(words: list, rects: list) -> list[dict]:
    """
    Each class block has 1-2 filled highlight rectangles at its top.
    Group those rects by x AND y proximity to find distinct blocks
    (same x range but different day rows must NOT be merged).
    
    Returns list of raw word groups (one per class block).
    """
    filled = [r for r in rects if r.get("fill") and r["x0"] > 50 and r["width"] > 20]

    # Cluster filled rects into blocks by BOTH x-range overlap AND y-proximity.
    # Two rects belong to the same block only if they overlap in x AND are
    # within ~30 pts vertically (stacked header lines within one block).
    clusters = []
    for r in sorted(filled, key=lambda r: (r["top"], r["x0"])):
        merged = False
        for c in clusters:
            x_overlap = r["x0"] < c["x1"] + 5 and r["x1"] > c["x0"] - 5
            y_close   = abs(r["top"] - c["bottom"]) < 30   # ' new constraint
            if x_overlap and y_close:
                c["x0"]    = min(c["x0"], r["x0"])
                c["x1"]    = max(c["x1"], r["x1"])
                c["top"]   = min(c["top"], r["top"])
                c["bottom"]= max(c["bottom"], r["bottom"])
                merged = True
                break
        if not merged:
            clusters.append({
                "x0": r["x0"], "x1": r["x1"],
                "top": r["top"], "bottom": r["bottom"]
            })

    # For each cluster find y-bottom: next cluster in same x column, or cap.
    MAX_BLOCK_HEIGHT = 130
    clusters_sorted = sorted(clusters, key=lambda c: (c["x0"], c["top"]))

    def get_y_bottom(c):
        same_col_below = [
            other["top"] for other in clusters_sorted
            if other is not c
            and abs(other["x0"] - c["x0"]) < 10
            and other["top"] > c["top"]
        ]
        return (min(same_col_below) - 2) if same_col_below else (c["top"] + MAX_BLOCK_HEIGHT)

    blocks = []
    for c in clusters:
        y_bottom = get_y_bottom(c)
        block_words = [
            w for w in words
            if w["x0"] >= c["x0"] - 5 and w["x1"] <= c["x1"] + 10
            and w["top"] >= c["top"] - 5
            and w["top"] <= y_bottom
            and w["top"] < 560
            and w["x0"] > DAY_LABEL_X_MAX
        ]
        if block_words:
            blocks.append({
                "x0": c["x0"],
                "x1": c["x1"],
                "y_top": min(w["top"] for w in block_words),
                "y_bottom": y_bottom,
                "words": sorted(block_words, key=lambda w: (w["top"], w["x0"]))
            })

    return blocks


def parse_block_text(block_words: list) -> dict:
    """
    Parse the text words of a class block into structured fields.

    CELCAT blocks can be narrow, causing each word to render on its own line.
    Strategy:
      1. Reconstruct physical lines from y-position grouping.
      2. Join everything into a single normalised string.
      3. Repair hyphen-split week tokens (e.g. "S2W7- S2W12" - "S2W7-S2W12").
      4. Use keyword anchors (Course: / Staff: / Room:) to slice out values
         even when the value wraps across several lines.
    """
    lines_map: dict[int, list[str]] = {}
    for w in block_words:
        key = round(w["top"])
        lines_map.setdefault(key, []).append(w["text"])

    lines = [" ".join(v) for _, v in sorted(lines_map.items())]
    raw_text = "\n".join(lines)

    joined = " ".join(lines)
    # Repair split week tokens: "S2W7- S2W12" - "S2W7-S2W12"
    joined = re.sub(r"(S\d+W\d+)-\s+(S\d+W\d+)", r"\1-\2", joined)

    result = {
        "type": None,
        "weeks": None,
        "week_count": None,
        "course": None,
        "staff": None,
        "room": None,
        "group_label": None,
        "raw_text": raw_text,
    }

    # Type
    if re.search(r"\bLecture\b", joined, re.I):
        result["type"] = "Lecture"
    elif re.search(r"\bLab\b", joined, re.I):
        result["type"] = "Lab"

    # Weeks: "S2W7-S2W12" (after repair above)
    wk = re.search(r"(S\d+W\d+-S\d+W\d+)", joined)
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
        # Strip any trailing week/label noise
        val = re.split(r"\s*(?:Wks|\[=|\(L\d)", val)[0].strip()
        if key == "Course":
            result["course"] = val or None
        elif key == "Staff":
            result["staff"] = val or None
        elif key == "Room":
            result["room"] = val or None

    return result


def extract_timetable(pdf_path: str) -> dict:
    """
    Main entry point. Returns a dict:
    {
      "source_file": "...",
      "semester": "...",
      "course": "...",
      "entries": [
        {
          "day": "Monday",
          "start_time": "08:00 AM",
          "end_time": "10:00 AM",
          "start_slot": {"label": "08:00 AM", "x0": 123.4, "x1": 234.5},
          "end_slot": {"label": "10:00 AM", "x0": 345.6, "x1": 456.7},
          "x0": 123.4,
          "x1": 456.7,
          "y_top": 200.2,
          "y_bottom": 260.0,
          "type": "Lecture",
          "weeks": "S2W7-S2W12",
          "week_count": 6,
          "course": "COMP 2603",
          "staff": "MATHURIN,Sergio",
          "room": "Daaga Auditorium",
          "group_label": null
        }, ...
      ]
    }
    """
    entries = []
    meta = {"semester": None, "course_title": None}

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            rects = page.rects

            if meta["semester"] is None:
                for w in words:
                    if w["text"].startswith("Semester_"):
                        meta["semester"] = w["text"]
                    if w["text"] == "timetable":
                        # "Course timetable - COMP XXXX, Course Name"
                        title_words = [
                            x["text"] for x in words
                            if abs(x["top"] - w["top"]) < 5 and x["x0"] > 60
                        ]
                        meta["course_title"] = " ".join(title_words)

            time_slots = build_time_x_map(words)
            day_map    = build_day_y_map(words)

            if not time_slots:
                continue  # skip pages with no time header

            blocks = identify_class_blocks(words, rects)

            for block in blocks:
                day = y_to_day(block["y_top"], day_map)
                start, end, start_slot, end_slot = x_range_to_times(block["x0"], block["x1"], time_slots)
                parsed = parse_block_text(block["words"])

                entry = {
                    "day": day,
                    "start_time": start,
                    "end_time": end,
                    "start_slot": start_slot,
                    "end_slot": end_slot,
                    "x0": block["x0"],
                    "x1": block["x1"],
                    "y_top": block["y_top"],
                    "y_bottom": block.get("y_bottom"),
                    **parsed,
                }
                entries.append(entry)

    return {
        "source_file": str(Path(pdf_path).name),
        "semester": meta["semester"],
        "course_title": meta["course_title"],
        "entries": entries,
    }


if __name__ == "__main__":
    args = sys.argv[1:] if len(sys.argv) > 1 else ["./downloaded_pdfs/"]

    # Expand directories into their PDF files.
    paths: list[Path] = []
    for a in args:
        p = Path(a)
        if p.is_dir():
            paths.extend(sorted(p.glob("*.pdf")))
        elif p.is_file():
            paths.append(p)
        else:
            print(f"Warning: path does not exist or is not a file: {a}")

    all_results = []
    for pdf_path in paths:
        print(f"Processing: {pdf_path}")
        result = extract_timetable(str(pdf_path))
        all_results.append(result)

        print(f"Semester : {result['semester']}")
        print(f"Course : {result['course_title']}")
        print(f"Entries : {len(result['entries'])}\n")

        for e in result["entries"]:
            label = f"[{e['group_label']}]" if e["group_label"] else ""
            print(
                f"  {e['day']:<12} {e['start_time']} – {e['end_time']}"
                f"  |  {e['type'] or '?':<8} {label:<5}"
                f"  |  {e['course'] or '?'}"
                f"  |  Staff: {e['staff'] or '?'}"
                f"  |  Room: {e['room'] or '?'}"
                f"  |  Wks: {e['weeks'] or '?'} ({e['week_count'] or '?'}x)"
            )

    # Save JSON output
    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "timetable_extracted.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n' JSON saved to: {out_path}")