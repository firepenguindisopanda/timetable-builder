"""
CELCAT Timetable PDF Downloader

Downloads timetable PDFs from UWI St. Augustine with optional filtering
by faculty, department, type, or course code.

Usage:
    from timetable_extractor.download import download_timetables

    # Download all COMP courses
    download_timetables(codes=["COMP", "INFO"])

    # Or via CLI:
    # python -m timetable_extractor.download --codes COMP INFO
"""

import argparse
import time
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from timetable_extractor.constants import BASE_URL, FINDER_XML, DELAY_SEC


def fetch_xml(url: str) -> ET.Element:
    """Fetch and parse XML from the given URL."""
    print(f"Fetching index: {url}")
    with urllib.request.urlopen(url, timeout=15) as resp:
        return ET.fromstring(resp.read())


def parse_resources(root: ET.Element) -> list[dict[str, str]]:
    """Parse all <resource> elements into a list of dicts."""
    resources: list[dict[str, str]] = []
    for r in root.findall("resource"):
        resources.append(
            {
                "id": r.get("id") or "",
                "type": r.get("type") or "",  # module / staff / room / group …
                "link": r.get("link") or "",  # e.g. m62602.pdf
                "name": (r.findtext("n") or "").strip(),
                "dept": (r.findtext("dept") or "").strip(),
                "faculty": (r.findtext("faculty") or "").strip(),
            }
        )
    return resources


def filter_resources(
    resources: list[dict[str, str]],
    *,
    res_type: str | None = None,
    faculty: str | None = None,
    dept: str | None = None,
    codes: list[str] | None = None,
) -> list[dict[str, str]]:
    """
    Apply zero or more filters (all conditions must match).
    All string comparisons are case-insensitive substrings.
    """
    out: list[dict[str, str]] = []
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
        print(f"  ' Failed: {e}")
        return False


def download_timetables(
    *,
    faculty: str | None = None,
    dept: str | None = None,
    codes: list[str] | None = None,
    res_type: str = "module",
    all_resources: bool = False,
    limit: int | None = None,
    dry_run: bool = False,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """
    Download CELCAT timetable PDFs from UWI St. Augustine.

    Returns a dict with summary: { "downloaded": int, "skipped": int, "failed": int }
    """
    if out_dir is None:
        out_dir = Path.cwd() / "downloaded_pdfs"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -- Require at least one filter unless --all is explicitly set --
    if not all_resources and not any([faculty, dept, codes]):
        raise ValueError(
            "Provide at least one filter (faculty / dept / codes) "
            "or set all_resources=True to download everything."
        )

    root = fetch_xml(FINDER_XML)
    all_resources_data = parse_resources(root)
    print(f"Total resources in index: {len(all_resources_data)}")

    # -- Apply filters --
    filtered = filter_resources(
        all_resources_data,
        res_type=res_type,
        faculty=faculty,
        dept=dept,
        codes=codes,
    )

    if limit:
        filtered = filtered[:limit]

    print(f"Matched: {len(filtered)} resource(s)\n")

    if not filtered:
        print("No matches - try broadening your filters.")
        return {"downloaded": 0, "skipped": 0, "failed": 0}

    ok = fail = skip = 0
    for i, r in enumerate(filtered, 1):
        dest = out_dir / r["link"]
        status = ""

        if dest.exists():
            status = "(already exists, skipping)"
            skip += 1
        elif dry_run:
            status = "(dry-run)"
        else:
            status = "downloading..."

        print(f"[{i}/{len(filtered)}] {r['name']}")
        print(f"           Dept: {r['dept']} | Faculty: {r['faculty']}")
        print(f"           File: {r['link']}  {status}")

        if not dest.exists() and not dry_run:
            success = download_pdf(r["link"], dest)
            if success:
                size_kb = dest.stat().st_size // 1024
                print(f"           ' Saved ({size_kb} KB)")
                ok += 1
            else:
                fail += 1
            time.sleep(DELAY_SEC)
        print()

    if not dry_run:
        print("-" * 50)
        print(f"Downloaded : {ok}")
        print(f"Skipped    : {skip}  (already on disk)")
        print(f"Failed     : {fail}")
        print(f"Output dir : {out_dir.resolve()}")
    else:
        print(
            f"Dry-run complete - {len(filtered)} file(s) would be downloaded to {out_dir.resolve()}"
        )

    return {"downloaded": ok, "skipped": skip, "failed": fail}


def main() -> None:
    """CLI entry point for downloading."""
    parser = argparse.ArgumentParser(
        description="Download CELCAT timetable PDFs from UWI St. Augustine."
    )
    parser.add_argument("--faculty", help="Filter by faculty name (partial match)")
    parser.add_argument("--dept", help="Filter by department name (partial match)")
    parser.add_argument(
        "--codes", nargs="+", help="Filter by course code prefix(es) e.g. COMP INFO"
    )
    parser.add_argument(
        "--type",
        default="module",
        help="Resource type to download: module (default), staff, room, group",
    )
    parser.add_argument(
        "--all", action="store_true", help="Download ALL resources of the given type"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Max number of PDFs to download"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="List matches without downloading"
    )
    parser.add_argument("--out-dir", default=None, help="Override output directory")
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else None

    download_timetables(
        faculty=args.faculty,
        dept=args.dept,
        codes=args.codes,
        res_type=args.type,
        all_resources=args.all,
        limit=args.limit,
        dry_run=args.dry_run,
        out_dir=out_dir,
    )


if __name__ == "__main__":
    main()
