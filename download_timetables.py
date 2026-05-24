"""
CELCAT Timetable PDF Downloader
Reads the UWI St. Augustine finder.xml and downloads timetable PDFs
with optional filtering by faculty, department, type, or course code.

Usage examples:
    # Download all COMP and INFO courses
    python download_timetables.py --codes COMP INFO

    # Download everything in the Science & Technology faculty
    python download_timetables.py --faculty "Science & Technology"

    # Download a specific department
    python download_timetables.py --dept "Computing & Information Technology"

    # Download ALL courses (hundreds of PDFs - use --limit to test first)
    python download_timetables.py --all --limit 20

    # Only show what would be downloaded without actually downloading
    python download_timetables.py --faculty "Science & Technology" --dry-run
"""

import argparse
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path


BASE_URL    = "https://mysta.uwi.edu/timetable/"
FINDER_XML  = BASE_URL + "finder.xml"
OUTPUT_DIR  = Path(__file__).parent / "downloaded_pdfs"
DELAY_SEC   = 1.5   # polite delay between requests


def fetch_xml(url: str) -> ET.Element:
    print(f"Fetching index: {url}")
    with urllib.request.urlopen(url, timeout=15) as resp:
        return ET.fromstring(resp.read())


def parse_resources(root: ET.Element) -> list[dict]:
    """Parse all <resource> elements into a list of dicts."""
    resources = []
    for r in root.findall("resource"):
        resources.append({
            "id":       r.get("id"),
            "type":     r.get("type"), # module / staff / room / group …
            "link":     r.get("link"), # e.g. m62602.pdf
            "name":     (r.findtext("name") or "").strip(),
            "dept":     (r.findtext("dept") or "").strip(),
            "faculty":  (r.findtext("faculty") or "").strip(),
        })
    return resources


def filter_resources(
    resources: list[dict],
    *,
    res_type:  str | None = None,
    faculty:   str | None = None,
    dept:      str | None = None,
    codes:     list[str] | None = None,
) -> list[dict]:
    """
    Apply zero or more filters (all conditions must match).
    All string comparisons are case-insensitive substrings.
    """
    out = []
    for r in resources:
        if res_type and r["type"].lower() != res_type.lower():
            continue
        if faculty and faculty.lower() not in r["faculty"].lower():
            continue
        if dept and dept.lower() not in r["dept"].lower():
            continue
        if codes:
            name_upper = r["name"].upper()
            if not any(c.upper() in name_upper for c in codes):
                continue
        out.append(r)
    return out


def download_pdf(link: str, dest: Path) -> bool:
    """Download a single PDF. Returns True on success."""
    url = BASE_URL + link
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            dest.write_bytes(resp.read())
        return True
    except Exception as e:
        print(f" Failed: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Download CELCAT timetable PDFs from UWI St. Augustine."
    )
    parser.add_argument("--faculty", help="Filter by faculty name (partial match)")
    parser.add_argument("--dept", help="Filter by department name (partial match)")
    parser.add_argument("--codes", nargs="+", help="Filter by course code prefix(es) e.g. COMP INFO")
    parser.add_argument("--type", default="module", help="Resource type to download: module (default), staff, room, group")
    parser.add_argument("--all", action="store_true", help="Download ALL resources of the given type")
    parser.add_argument("--limit", type=int, default=None, help="Max number of PDFs to download")
    parser.add_argument("--dry-run", action="store_true", help="List matches without downloading")
    parser.add_argument("--out-dir", default=None, help="Override output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    if not args.all and not any([args.faculty, args.dept, args.codes]):
        parser.error(
            "Provide at least one filter (--faculty / --dept / --codes) "
            "or pass --all to download everything."
        )

    root = fetch_xml(FINDER_XML)
    all_resources = parse_resources(root)
    print(f"Total resources in index: {len(all_resources)}")

    filtered = filter_resources(
        all_resources,
        res_type=args.type,
        faculty=args.faculty,
        dept=args.dept,
        codes=args.codes,
    )

    if args.limit:
        filtered = filtered[: args.limit]

    print(f"Matched: {len(filtered)} resource(s)\n")

    if not filtered:
        print("No matches - try broadening your filters.")
        return

    ok = fail = skip = 0
    for i, r in enumerate(filtered, 1):
        dest = out_dir / r["link"]
        status = ""

        if dest.exists():
            status = "(already exists, skipping)"
            skip += 1
        elif args.dry_run:
            status = "(dry-run)"
        else:
            status = "downloading..."

        print(f"[{i}/{len(filtered)}] {r['name']}")
        print(f"Dept: {r['dept']} | Faculty: {r['faculty']}")
        print(f"File: {r['link']}  {status}")

        if not dest.exists() and not args.dry_run:
            success = download_pdf(r["link"], dest)
            if success:
                size_kb = dest.stat().st_size // 1024
                print(f"Saved ({size_kb} KB)")
                ok += 1
            else:
                fail += 1
            time.sleep(DELAY_SEC)
        print()

    if not args.dry_run:
        print("-" * 50)
        print(f"Downloaded : {ok}")
        print(f"Skipped: {skip}  (already on disk)")
        print(f"Failed: {fail}")
        print(f"Output dir : {out_dir.resolve()}")
    else:
        print(f"Dry-run complete - {len(filtered)} file(s) would be downloaded to {out_dir.resolve()}")


if __name__ == "__main__":
    main()