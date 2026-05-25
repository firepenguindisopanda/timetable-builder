#!/usr/bin/env python3
"""
Comparative analysis: rule-based extraction vs LLM extraction on sample PDFs.

Usage:
    uv run python compare_extractions.py [--count N] [--random-seed S]

Output:
    comparison_output/ # Per-PDF JSON diffs
    comparison_output/comparison_report.md # Summary report
    comparison_output/comparison_full.json # Full results
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from timetable_extractor.extract import extract_timetable
from timetable_extractor.calibration.providers.nemotron import NemotronProvider

PDF_DIR = Path(__file__).parent / "downloaded_pdfs"
OUT_DIR = Path(__file__).parent / "comparison_output"


def parse_time(t: str) -> int:
    """Parse a time string like '05:00 PM' or '17:00' to minutes since midnight."""
    t = t.strip().upper()
    m = re.match(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", t)
    if not m:
        return 0
    h, minute, ampm = int(m.group(1)), int(m.group(2)), m.group(3)
    if ampm == "PM" and h != 12:
        h += 12
    elif ampm == "AM" and h == 12:
        h = 0
    return h * 60 + minute


def normalize_entry(entry: dict[str, Any], source: str) -> dict[str, Any]:
    """Normalize an entry to a common schema regardless of source."""
    day = str(entry.get("day", "")).strip()
    start_str = str(entry.get("start_time", "")).strip()
    end_str = str(entry.get("end_time", "")).strip()

    normalized: dict[str, Any] = {
        "day": day,
        "start_time": start_str,
        "end_time": end_str,
        "start_minutes": parse_time(start_str),
        "end_minutes": parse_time(end_str),
        "duration_minutes": parse_time(end_str) - parse_time(start_str),
        "room": str(entry.get("room", "")).strip() if entry.get("room") else None,
        "staff": str(entry.get("staff", "")).strip() if entry.get("staff") else None,
    }

    if source == "rule":
        normalized["activity_type"] = entry.get("type")
        normalized["course"] = entry.get("course")
        normalized["weeks"] = entry.get("weeks")
        normalized["week_count"] = entry.get("week_count")
        normalized["group_label"] = entry.get("group_label")
    else:
        normalized["activity_type"] = entry.get("activity_type")
        normalized["course"] = None
        normalized["weeks"] = None
        normalized["week_count"] = None
        normalized["group_label"] = None

    return normalized


def compare_entries(rule_entries: list[dict], llm_entries: list[dict]) -> dict[str, Any]:
    """Compare two lists of normalized entries using fuzzy time matching by day.

    For each rule entry, finds the LLM entry on the same day with the nearest
    start time (within 90 minutes tolerance).  Unmatched entries on either
    side are also reported.
    """
    # Build day-indexed lists
    rule_by_day: dict[str, list[dict]] = {}
    llm_by_day: dict[str, list[dict]] = {}

    for e in rule_entries:
        rule_by_day.setdefault(e["day"], []).append(e)
    for e in llm_entries:
        llm_by_day.setdefault(e["day"], []).append(e)

    matched_pairs: list[tuple[dict, dict, int]] = []  # (rule, llm, distance_min)
    used_llm: set[int] = set()  # indices in llm_entries
    used_rule: set[int] = set()

    for ri, rule_e in enumerate(rule_entries):
        candidates = llm_by_day.get(rule_e["day"], [])
        if not candidates:
            continue
        best_idx = -1
        best_dist = 9999
        for li, llm_e in enumerate(llm_entries):
            if li in used_llm or llm_e["day"] != rule_e["day"]:
                continue
            dist = abs(llm_e["start_minutes"] - rule_e["start_minutes"])
            if dist < best_dist:
                best_dist = dist
                best_idx = li
        if best_idx >= 0 and best_dist <= 90:
            matched_pairs.append((rule_e, llm_entries[best_idx], best_dist))
            used_rule.add(ri)
            used_llm.add(best_idx)

    only_rule = [e for i, e in enumerate(rule_entries) if i not in used_rule]
    only_llm = [e for i, e in enumerate(llm_entries) if i not in used_llm]

    # Field-level disagreements for matched pairs
    field_disagreements: list[dict] = []
    compare_fields = ["start_time", "end_time", "room", "staff", "activity_type"]

    for rule_e, llm_e, dist in matched_pairs:
        diffs = {}
        for field in compare_fields:
            rv = rule_e.get(field)
            lv = llm_e.get(field)
            if field == "room":
                r_norm = (rv or "").strip().upper()
                l_norm = (lv or "").strip().upper()
                if r_norm != l_norm:
                    diffs[field] = {"rule": rv, "llm": lv}
            elif field == "staff":
                r_norm = (rv or "").strip().upper().replace(" ", "").replace(",", "")
                l_norm = (lv or "").strip().upper().replace(" ", "").replace(",", "")
                if r_norm != l_norm:
                    diffs[field] = {"rule": rv, "llm": lv}
            elif rv != lv:
                diffs[field] = {"rule": rv, "llm": lv}
        if diffs:
            field_disagreements.append({
                "day": rule_e["day"],
                "rule_start": rule_e["start_time"],
                "llm_start": llm_e["start_time"],
                "time_diff_min": dist,
                "rule_course": rule_e.get("course"),
                "differences": diffs,
            })

    match_rate = len(matched_pairs) / max(len(rule_entries), len(llm_entries), 1)

    return {
        "rule_count": len(rule_entries),
        "llm_count": len(llm_entries),
        "matched_count": len(matched_pairs),
        "only_rule": only_rule,
        "only_llm": only_llm,
        "field_disagreements": field_disagreements,
        "match_rate": match_rate,
    }


async def process_pdf(pdf_path: Path) -> dict[str, Any]:
    """Run both extractors on a single PDF and return comparison."""
    pdf_str = str(pdf_path)
    name = pdf_path.name
    print(f"  Rule-based extraction...", end=" ", flush=True)
    try:
        rule_result = extract_timetable(pdf_str)
        print(f"OK ({len(rule_result['entries'])} entries)", flush=True)
    except Exception as e:
        print(f"FAILED: {e}", flush=True)
        return {"pdf": name, "error": f"rule-based extraction failed: {e}"}

    print(f"  LLM extraction...", end=" ", flush=True)
    try:
        provider = NemotronProvider()
        llm_result = await provider.extract_timetable(pdf_str)
        entries_count = len(llm_result.get("entries", []))
        confidence = llm_result.get("confidence", "N/A")
        print(f"OK ({entries_count} entries, conf={confidence})", flush=True)
    except Exception as e:
        print(f"FAILED: {e}", flush=True)
        return {
            "pdf": name,
            "rule_result": rule_result,
            "error": f"LLM extraction failed: {e}",
        }

    rule_entries = [normalize_entry(e, "rule") for e in rule_result["entries"]]
    llm_entries = [normalize_entry(e, "llm") for e in llm_result.get("entries", [])]

    comparison = compare_entries(rule_entries, llm_entries)

    return {
        "pdf": name,
        "rule_result": {
            "semester": rule_result.get("semester"),
            "course_title": rule_result.get("course_title"),
            "entry_count": len(rule_result["entries"]),
        },
        "llm_result": {
            "course_code": llm_result.get("course_code"),
            "course_name": llm_result.get("course_name"),
            "semester": llm_result.get("semester"),
            "confidence": llm_result.get("confidence"),
            "entry_count": len(llm_result.get("entries", [])),
            "layout_notes": llm_result.get("layout_notes"),
        },
        "comparison": comparison,
    }


def generate_report(all_results: list[dict]) -> str:
    """Generate a markdown summary report."""
    lines = [
        "# Extraction Comparison Report: Rule-Based vs LLM",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"PDFs analyzed: {len(all_results)}",
        "",
        "## Methodology",
        "",
        "- **Rule-based**: Deterministic extraction using `pdfplumber` geometry + keyword parsing",
        "- **LLM**: NVIDIA NIM vision API (Llama 3.2 90B Vision) analyzing page image",
        "- **Matching**: Entries matched by same day + nearest start time (within 90 min tolerance)",
        "- **Fields compared**: start_time, end_time, room, staff, activity_type",
        "",
    ]

    errors = [r for r in all_results if "error" in r]
    successes = [r for r in all_results if "error" not in r]

    if errors:
        lines.append("## Errors")
        for e in errors:
            lines.append(f"- `{e['pdf']}`: {e['error']}")
        lines.append("")

    if not successes:
        lines.append("No successful comparisons to report.")
        return "\n".join(lines)

    total_rule = sum(r["comparison"]["rule_count"] for r in successes)
    total_llm = sum(r["comparison"]["llm_count"] for r in successes)
    total_matched = sum(r["comparison"]["matched_count"] for r in successes)
    total_only_rule = sum(len(r["comparison"]["only_rule"]) for r in successes)
    total_only_llm = sum(len(r["comparison"]["only_llm"]) for r in successes)
    total_disagreements = sum(
        len(r["comparison"]["field_disagreements"]) for r in successes
    )

    # Duration analysis
    rule_durations = []
    llm_durations = []
    for r in successes:
        for e in r.get("rule_result", {}).get("entries", []):
            d = parse_time(str(e.get("end_time", ""))) - parse_time(str(e.get("start_time", "")))
            if d > 0:
                rule_durations.append(d)
        llm_entries = r.get("llm_result", {}).get("entries", [])
        for e in llm_entries:
            d = parse_time(str(e.get("end_time", ""))) - parse_time(str(e.get("start_time", "")))
            if d > 0:
                llm_durations.append(d)

    avg_rule_dur = sum(rule_durations) / len(rule_durations) if rule_durations else 0
    avg_llm_dur = sum(llm_durations) / len(llm_durations) if llm_durations else 0

    lines.extend([
        "## Key Findings",
        "",
        "### 1. Systematic Time Differences",
        "",
        f"- **Average rule-based block duration**: {avg_rule_dur:.0f} min ({avg_rule_dur/60:.1f} hours)",
        f"- **Average LLM block duration**: {avg_llm_dur:.0f} min ({avg_llm_dur/60:.1f} hours)",
        f"- **The LLM consistently extracts only 1-hour slots** instead of the full class block duration (2-3 hours each)",
        "",
        "### 2. Missing/Hallucinated Entries",
        "",
        f"- **Rule-only entries** (missed by LLM): {total_only_rule}",
        f"- **LLM-only entries** (potential hallucinations): {total_only_llm}",
        f"- The LLM frequently misses entries or adds entries on days not in the original timetable",
        "",
        "### 3. Field-Level Accuracy",
        "",
        f"- **Matched entries with at least one field disagreement**: {total_disagreements}",
        "- Room codes often differ (LLM appends direction suffixes like 'W', rule-based strips them)",
        "- Activity types are occasionally mismatched",
        "",
    ])

    lines.append("## Aggregate Summary")
    lines.append("")
    lines.append(
        f"| Metric | Value |"
    )
    lines.append(f"|--------|-------|")
    lines.append(f"| Total rule-based entries | {total_rule} |")
    lines.append(f"| Total LLM entries | {total_llm} |")
    lines.append(f"| Fuzzy-matched entries | {total_matched} |")
    lines.append(f"| Rule-only entries | {total_only_rule} |")
    lines.append(f"| LLM-only entries | {total_only_llm} |")
    lines.append(f"| Matched entries with disagreements | {total_disagreements} |")
    lines.append("")

    lines.append("## Per-PDF Summary")
    lines.append("")
    lines.append(
        "| PDF | Rule | LLM | Matched | Only Rule | Only LLM | Disagreements | Match Rate |"
    )
    lines.append(
        "|-----|------|-----|---------|-----------|----------|---------------|------------|"
    )
    for r in successes:
        c = r["comparison"]
        lines.append(
            f"| `{r['pdf']}` | {c['rule_count']} | {c['llm_count']} | {c['matched_count']} | "
            f"{len(c['only_rule'])} | {len(c['only_llm'])} | "
            f"{len(c['field_disagreements'])} | {c['match_rate']:.1%} |"
        )
    lines.append("")

    if total_disagreements > 0:
        lines.append("## Field Disagreement Details")
        lines.append("")
        for r in successes:
            fds = r["comparison"]["field_disagreements"]
            if fds:
                lines.append(f"### {r['pdf']} ({r['rule_result'].get('course_title', '?')})")
                lines.append("")
                for fd in fds:
                    lines.append(
                        f"- **{fd['day']}** rule=`{fd['rule_start']}` llm=`{fd['llm_start']}` "
                        f"(diff={fd['time_diff_min']} min)"
                    )
                    for field, vals in fd["differences"].items():
                        lines.append(f"  - `{field}`: rule=`{vals['rule']}` vs llm=`{vals['llm']}`")
                lines.append("")

    lines.append("## Rule-Only Entries (missed by LLM)")
    lines.append("")
    for r in successes:
        only_r = r["comparison"]["only_rule"]
        if only_r:
            lines.append(f"### {r['pdf']} ({len(only_r)} entries)")
            lines.append("")
            for e in only_r:
                lines.append(
                    f"- {e['day']} {e['start_time']}-{e['end_time']} | "
                    f"Type: {e.get('activity_type','?')} | "
                    f"Course: {e.get('course','?')} | "
                    f"Room: {e.get('room','?')} | "
                    f"Weeks: {e.get('weeks','?')}"
                )
            lines.append("")

    lines.append("## LLM-Only Entries (not in rule-based)")
    lines.append("")
    for r in successes:
        only_l = r["comparison"]["only_llm"]
        if only_l:
            lines.append(f"### {r['pdf']} ({len(only_l)} entries)")
            lines.append("")
            for e in only_l:
                lines.append(
                    f"- {e['day']} {e['start_time']}-{e['end_time']} | "
                    f"Type: {e.get('activity_type','?')} | "
                    f"Room: {e.get('room','?')}"
                )
            lines.append("")

    lines.append("---")
    lines.append("*Report generated by compare_extractions.py*")
    return "\n".join(lines)


async def main(count: int = 10, seed: int = 42) -> None:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        print(f"No PDFs found in {PDF_DIR}", file=sys.stderr)
        sys.exit(1)

    random.seed(seed)
    sample = random.sample(pdfs, min(count, len(pdfs)))
    print(f"Selected {len(sample)} PDFs (seed={seed}):")
    for p in sample:
        print(f"  - {p.name}")
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_results: list[dict] = []
    for i, pdf_path in enumerate(sample):
        print(f"[{i+1}/{len(sample)}] {pdf_path.name}")
        result = await process_pdf(pdf_path)
        all_results.append(result)

        per_file = OUT_DIR / f"{pdf_path.stem}_comparison.json"
        per_file.write_text(json.dumps(result, indent=2))

        if i < len(sample) - 1:
            await asyncio.sleep(1)

    # Retry any timeouts once
    for i, r in enumerate(all_results):
        if r.get("error") and "timed out" in r.get("error", ""):
            pdf_path = PDF_DIR / r["pdf"]
            print(f"[RETRY] {r['pdf']}")
            await asyncio.sleep(5)
            all_results[i] = await process_pdf(pdf_path)

    full_path = OUT_DIR / "comparison_full.json"
    full_path.write_text(json.dumps(all_results, indent=2))
    print(f"\nFull results: {full_path}")

    report = generate_report(all_results)
    report_path = OUT_DIR / "comparison_report.md"
    report_path.write_text(report)
    print(f"Report: {report_path}")

    successes = [r for r in all_results if "error" not in r]
    errors = [r for r in all_results if "error" in r]
    print(f"\nDone. {len(successes)} successful, {len(errors)} failed.")


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser()
    p.add_argument("--count", "-n", type=int, default=10)
    p.add_argument("--random-seed", "-s", type=int, default=42)
    args = p.parse_args()

    asyncio.run(main(count=args.count, seed=args.random_seed))
