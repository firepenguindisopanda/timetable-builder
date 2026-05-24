"""
Main extraction module for CELCAT Timetable PDFs.

This module provides the main entry point for extracting structured class data
from CELCAT-generated timetable PDFs.

Usage:
    from timetable_extractor import extract_timetable

    result = extract_timetable("timetable.pdf")

    # Or via CLI:
    # python -m timetable_extractor.extract path/to/pdf
"""

import json
import sys
from pathlib import Path
from typing import Any

import pdfplumber

from timetable_extractor.blocks import identify_class_blocks
from timetable_extractor.config.loader import load_active_config
from timetable_extractor.day_map import build_day_y_map, y_to_day
from timetable_extractor.text_parser import parse_block_text
from timetable_extractor.time_parser import build_time_x_map, x_range_to_times


def extract_timetable(
    pdf_path: str | Path,
    course_code: str | None = None,
) -> dict[str, Any]:
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
    entries: list[dict[str, Any]] = []
    meta: dict[str, str | None] = {"semester": None, "course_title": None}

    config = None
    if course_code:
        config = load_active_config(course_code)

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words()
            rects = page.rects

            page_width = page.width
            page_height = page.height

            if meta["semester"] is None:
                for w in words:
                    if w["text"].startswith("Semester_"):
                        meta["semester"] = w["text"]
                    if w["text"] == "timetable":
                        # "Course timetable - COMP XXXX, Course Name"
                        title_words = [
                            x["text"]
                            for x in words
                            if abs(x["top"] - w["top"]) < 5 and x["x0"] > 60
                        ]
                        meta["course_title"] = " ".join(title_words)

            time_slots = build_time_x_map(words, config=config, page_width=page_width, page_height=page_height)
            day_map = build_day_y_map(words, config=config, page_width=page_width, page_height=page_height)

            if not time_slots:
                continue  # skip pages with no time header

            blocks = identify_class_blocks(words, rects, config=config, page_width=page_width, page_height=page_height)

            for block in blocks:
                day = y_to_day(block["y_top"], day_map)
                start, end = x_range_to_times(block["x0"], block["x1"], time_slots)
                parsed = parse_block_text(block["words"], config=config)

                entry: dict[str, Any] = {
                    "day": day,
                    "start_time": start,
                    "end_time": end,
                    **parsed,
                }
                entries.append(entry)

    return {
        "source_file": str(Path(pdf_path).name),
        "semester": meta["semester"],
        "course_title": meta["course_title"],
        "entries": entries,
    }


def main() -> None:
    """CLI entry point for extraction."""
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

    all_results: list[dict[str, Any]] = []
    for pdf_path in paths:
        print(f"\n{'=' * 60}")
        print(f"Processing: {pdf_path}")
        print("=" * 60)
        result = extract_timetable(str(pdf_path))
        all_results.append(result)

        print(f"Semester : {result['semester']}")
        print(f"Course   : {result['course_title']}")
        print(f"Entries  : {len(result['entries'])}\n")

        for e in result["entries"]:
            label = f"[{e['group_label']}]" if e["group_label"] else ""
            print(
                f"  {e['day']:<12} {e['start_time']} - {e['end_time']}"
                f"  |  {e['type'] or '?':<8} {label:<5}"
                f"  |  {e['course'] or '?'}"
                f"  |  Staff: {e['staff'] or '?'}"
                f"  |  Room: {e['room'] or '?'}"
                f"  |  Wks: {e['weeks'] or '?'} ({e['week_count'] or '?'}x)"
            )

    # Save JSON output
    out_dir = Path(__file__).parent.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "timetable_extracted.json"
    with open(out_path, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n' JSON saved to: {out_path}")


if __name__ == "__main__":
    main()
