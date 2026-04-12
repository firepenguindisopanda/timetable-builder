"""
CELCAT Time Header Coordinate Evaluator
Scans all PDFs in downloaded_pdfs/ and checks that time header labels
appear at consistent x/y positions across every file.

Reports:
  - The "expected" (majority) x position for each time slot
  - Any PDF/page where a time label deviates beyond a tolerance
  - PDFs where the header row is missing entirely
  - A summary table of x-coordinate stats per time slot

Usage:
    python evaluate_headers.py # scans ./downloaded_pdfs/
    python evaluate_headers.py --dir /some/path # custom folder
    python evaluate_headers.py --tolerance 3 # tighter tolerance (default 5 pts)
    python evaluate_headers.py --save-csv # also write results to CSV
"""

import argparse
import csv
import statistics
from collections import defaultdict
from pathlib import Path

import pdfplumber

DEFAULT_PDF_DIR   = Path(__file__).parent / "downloaded_pdfs"
TIME_HEADER_Y_MIN = 85
TIME_HEADER_Y_MAX = 120
DEFAULT_TOLERANCE = 5 # pts - flag if x deviates more than this from median

EXPECTED_TIMES = [
    "08:00AM", "09:00AM", "10:00AM", "11:00AM",
    "12:00PM", "01:00PM", "02:00PM", "03:00PM",
    "04:00PM", "05:00PM", "06:00PM", "07:00PM",
    "08:00PM", "09:00PM",
]


def extract_time_headers(page) -> list[dict]:
    """Return list of {label, x0, x1, top, bottom} for time headers on a page."""
    found = []
    for w in page.extract_words():
        if TIME_HEADER_Y_MIN <= w["top"] <= TIME_HEADER_Y_MAX:
            import re
            if re.match(r"\d{2}:\d{2}[AP]M", w["text"]):
                found.append({
                    "label": w["text"],
                    "x0": round(w["x0"], 2),
                    "x1": round(w["x1"], 2),
                    "top": round(w["top"], 2),
                    "bottom": round(w["bottom"], 2),
                })
    return sorted(found, key=lambda h: h["x0"])


def scan_all_pdfs(pdf_dir: Path) -> dict:
    """
    Scan every PDF in pdf_dir.
    Returns {
        "per_file": { filename: [ {page, headers:[...], missing:[...]} ] },
        "global_x": { "08:00AM": [x0_values across all pages] },
        "errors": [ {file, error} ]
    }
    """
    per_file = {}
    global_x = defaultdict(list) # label - list of x0 values
    errors = []
    pdf_files = sorted(pdf_dir.glob("*.pdf"))

    if not pdf_files:
        print(f"No PDFs found in {pdf_dir}")
        return {"per_file": {}, "global_x": {}, "errors": []}

    print(f"Scanning {len(pdf_files)} PDFs in {pdf_dir}\n")

    for i, pdf_path in enumerate(pdf_files, 1):
        print(f"  [{i:>4}/{len(pdf_files)}] {pdf_path.name}", end=" ... ", flush=True)
        file_pages = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page_num, page in enumerate(pdf.pages, 1):
                    headers = extract_time_headers(page)
                    found_labels = {h["label"] for h in headers}
                    missing = [t for t in EXPECTED_TIMES if t not in found_labels]

                    file_pages.append({
                        "page": page_num,
                        "headers": headers,
                        "missing": missing,
                        "width": round(page.width, 1),
                        "height": round(page.height, 1),
                    })

                    for h in headers:
                        global_x[h["label"]].append(h["x0"])

            per_file[pdf_path.name] = file_pages
            total_headers = sum(len(p["headers"]) for p in file_pages)
            print(f"{len(file_pages)} page(s), {total_headers} header(s) found")

        except Exception as e:
            errors.append({"file": pdf_path.name, "error": str(e)})
            print(f"ERROR: {e}")

    return {
        "per_file": per_file,
        "global_x": dict(global_x),
        "errors": errors,
    }



def compute_expected_x(global_x: dict) -> dict[str, float]:
    """Return {label: median_x0} as the canonical expected position."""
    return {
        label: statistics.median(vals)
        for label, vals in global_x.items()
        if vals
    }


def find_discrepancies(scan: dict, expected_x: dict, tolerance: float) -> list[dict]:
    """
    Return list of discrepancy records:
    { file, page, label, expected_x, actual_x, delta, top }
    """
    discrepancies = []
    for filename, pages in scan["per_file"].items():
        for page_info in pages:
            for h in page_info["headers"]:
                exp = expected_x.get(h["label"])
                if exp is None:
                    continue
                delta = abs(h["x0"] - exp)
                if delta > tolerance:
                    discrepancies.append({
                        "file": filename,
                        "page": page_info["page"],
                        "label": h["label"],
                        "expected_x": round(exp, 2),
                        "actual_x": h["x0"],
                        "delta": round(delta, 2),
                        "top": h["top"],
                    })
    return sorted(discrepancies, key=lambda d: (d["label"], d["delta"]), reverse=True)


def find_missing_headers(scan: dict) -> list[dict]:
    """Return pages where one or more expected time labels are absent."""
    missing = []
    for filename, pages in scan["per_file"].items():
        for page_info in pages:
            if page_info["missing"]:
                missing.append({
                    "file": filename,
                    "page": page_info["page"],
                    "missing": page_info["missing"],
                })
    return missing



def print_summary_table(global_x: dict, expected_x: dict, tolerance: float):
    col = 14
    print(" TIME HEADER X-COORDINATE STATISTICS  (across all PDFs)")
    print(f"{'Label':<12} {'Median x0':>10} {'Min x0':>8} {'Max x0':>8} "
          f"{'StdDev':>8} {'Count':>6} {'Spread OK?':>10}")
    for label in EXPECTED_TIMES:
        vals = global_x.get(label, [])
        if not vals:
            print(f"{label:<12} {'-':>10} {'-':>8} {'-':>8} {'-':>8} {'0':>6} {'NO DATA':>10}")
            continue
        med = statistics.median(vals)
        mn = min(vals)
        mx = max(vals)
        stdev = statistics.pstdev(vals) if len(vals) > 1 else 0.0
        spread_ok = "'" if (mx - mn) <= tolerance * 2 else "' WIDE"
        print(f"{label:<12} {med:>10.2f} {mn:>8.2f} {mx:>8.2f} "
              f"{stdev:>8.3f} {len(vals):>6}  {spread_ok:>10}")


def print_discrepancies(discrepancies: list[dict], tolerance: float):
    print(f" X-COORDINATE DISCREPANCIES  (delta > {tolerance} pts)")
    if not discrepancies:
        print(f"' None found - all time headers within {tolerance} pt tolerance.")
        return
    print(f"{len(discrepancies)} discrepancy/ies found:\n")
    print(f"{'Label':<12} {'File':<30} {'Pg':>3} {'Expected':>9} "
          f"{'Actual':>8} {'Delta':>7}")
    for d in discrepancies:
        fname = d["file"][:28] + ".." if len(d["file"]) > 30 else d["file"]
        print(f"{d['label']:<12} {fname:<30} {d['page']:>3} "
              f"{d['expected_x']:>9.2f} {d['actual_x']:>8.2f} {d['delta']:>7.2f} '")


def print_missing(missing: list[dict]):
    print(f" PAGES WITH MISSING TIME HEADERS")
    if not missing:
        print("' All pages have the full set of time headers.")
        return
    print(f"{len(missing)} page(s) with missing headers:\n")
    for m in missing:
        print(f"{m['file']} (page {m['page']}):")
        print(f"Missing: {', '.join(m['missing'])}")


def print_errors(errors: list[dict]):
    if not errors:
        return
    print(f" PDF READ ERRORS")
    for e in errors:
        print(f"' {e['file']}: {e['error']}")


def print_final_verdict(discrepancies, missing, errors, total_pdfs):
    print(f" VERDICT")
    issues = len(discrepancies) + len(missing) + len(errors)
    print(f"PDFs scanned: {total_pdfs}")
    print(f"X discrepancies : {len(discrepancies)}")
    print(f"Missing headers : {len(missing)}")
    print(f"Read errors: {len(errors)}")
    if issues == 0:
        print("\n'All PDFs look consistent - extraction script should work reliably.")
    else:
        print(f"\n'{issues} issue(s) found. Review the files listed above before")
        print(f"running the bulk extraction.")
    print()



def save_csv(scan: dict, expected_x: dict, discrepancies: list[dict],
             missing: list[dict], out_dir: Path):
    # Raw header positions
    raw_path = out_dir / "header_positions.csv"
    with open(raw_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "page", "label", "x0", "x1", "top", "bottom"])
        w.writeheader()
        for filename, pages in scan["per_file"].items():
            for p in pages:
                for h in p["headers"]:
                    w.writerow({"file": filename, "page": p["page"], **h})
    print(f"Saved: {raw_path}")

    # Discrepancies
    disc_path = out_dir / "discrepancies.csv"
    with open(disc_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["file", "page", "label", "expected_x", "actual_x", "delta", "top"])
        w.writeheader()
        w.writerows(discrepancies)
    print(f"Saved: {disc_path}")

    # Missing headers
    miss_path = out_dir / "missing_headers.csv"
    with open(miss_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["file", "page", "missing_labels"])
        for m in missing:
            w.writerow([m["file"], m["page"], "; ".join(m["missing"])])
    print(f"Saved: {miss_path}")



def main():
    parser = argparse.ArgumentParser(
        description="Evaluate time header x/y consistency across CELCAT timetable PDFs."
    )
    parser.add_argument("--dir",default=None, help="Folder containing PDFs (default: ./downloaded_pdfs)")
    parser.add_argument("--tolerance", type=float, default=DEFAULT_TOLERANCE,
                        help=f"Max allowed x deviation in pts (default: {DEFAULT_TOLERANCE})")
    parser.add_argument("--save-csv",  action="store_true", help="Export results to CSV files")
    args = parser.parse_args()

    pdf_dir = Path(args.dir) if args.dir else DEFAULT_PDF_DIR
    if not pdf_dir.exists():
        print(f"' Directory not found: {pdf_dir}")
        return

    scan = scan_all_pdfs(pdf_dir)
    expected_x = compute_expected_x(scan["global_x"])
    discrepancies = find_discrepancies(scan, expected_x, args.tolerance)
    missing = find_missing_headers(scan)
    total_pdfs = len(scan["per_file"])

    print_summary_table(scan["global_x"], expected_x, args.tolerance)
    print_discrepancies(discrepancies, args.tolerance)
    print_missing(missing)
    print_errors(scan["errors"])
    print_final_verdict(discrepancies, missing, scan["errors"], total_pdfs)

    
    if args.save_csv:
        print("Saving CSV reports...")
        save_csv(scan, expected_x, discrepancies, missing, pdf_dir)

    return discrepancies, missing


if __name__ == "__main__":
    main()