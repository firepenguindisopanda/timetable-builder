"""
Detect when UWI republishes the timetable, and re-download only what changed.

The server sends Last-Modified and ETag on every file and honours conditional
requests, so a check that finds nothing new costs one 304 response per file
rather than a full download.

It exposes only the *current* Last-Modified - there is no history endpoint -
so the `sync_runs` and `publications` tables are the only place a record of
past updates can accumulate. Run this on a schedule to build that history.

Usage:
    # Has the index changed since we last looked?
    uv run python -m timetable_extractor.sync check

    # Re-download changed PDFs, refresh finder.xml and record the result
    uv run python -m timetable_extractor.sync pull

    # Show what we know about past updates
    uv run python -m timetable_extractor.sync history
"""

from __future__ import annotations

import argparse
import email.utils
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from timetable_extractor.constants import BASE_URL, DELAY_SEC, FINDER_XML
from timetable_extractor.database.connection import (
    DatabaseNotConfigured,
    apply_schema,
    connect,
)
from timetable_extractor.database.loader import kind_for_pdf, parse_published_at

USER_AGENT = "uwi-timetable-builder/1.0 (+course timetable sync)"

#: Where ``database.cli load`` looks for the registry by default. ``pull``
#: writes it here so the two cannot disagree about which publication the PDFs
#: on disk belong to.
DEFAULT_REGISTRY = Path("finder.xml")


@dataclass
class HeadResult:
    status: int
    etag: str | None
    last_modified: datetime | None
    body: bytes | None = None


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


def fetch(
    url: str,
    *,
    etag: str | None = None,
    last_modified: datetime | None = None,
    method: str = "GET",
    timeout: int = 30,
) -> HeadResult:
    """
    Conditional fetch. Returns status 304 with no body when unchanged.

    Sending both validators lets the server pick whichever it trusts; IIS
    answers on either.
    """
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", USER_AGENT)
    if etag:
        request.add_header("If-None-Match", etag)
    if last_modified:
        request.add_header(
            "If-Modified-Since", email.utils.format_datetime(last_modified)
        )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read() if method == "GET" else None
            return HeadResult(
                status=response.status,
                etag=response.headers.get("ETag"),
                last_modified=_parse_http_date(response.headers.get("Last-Modified")),
                body=body,
            )
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return HeadResult(status=304, etag=etag, last_modified=last_modified)
        raise


def _last_known_index(conn) -> tuple[int | None, str | None, datetime | None, datetime | None]:
    """Id, ETag, Last-Modified and published_at of the most recent publication."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, http_etag, http_last_modified, published_at
              FROM publications
             ORDER BY COALESCE(published_at, discovered_at) DESC
             LIMIT 1
            """
        )
        row = cur.fetchone()
    return row if row else (None, None, None, None)


def check(conn, *, verbose: bool = True) -> bool:
    """
    Report whether finder.xml changed since the last recorded publication.

    Prefers the cheap conditional request, but a publication loaded from a
    local file has no stored validators. Rather than call that a change, fall
    back to hashing the body and comparing it against the publications we
    already know - and record the validators so the next check stays cheap.
    """
    import hashlib

    publication_id, etag, last_modified, published_at = _last_known_index(conn)
    have_validators = bool(etag or last_modified)

    result = fetch(
        FINDER_XML,
        etag=etag,
        last_modified=last_modified,
        method="HEAD" if have_validators else "GET",
    )

    changed = result.status != 304
    if changed and result.body is not None:
        digest = hashlib.sha256(result.body).hexdigest()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM publications WHERE xml_sha256 = %s", (digest,))
            known = cur.fetchone()
            if known:
                changed = False
                # Backfill the validators so the next check is a HEAD + 304.
                cur.execute(
                    """
                    UPDATE publications
                       SET http_etag = COALESCE(%s, http_etag),
                           http_last_modified = COALESCE(%s, http_last_modified)
                     WHERE id = %s
                    """,
                    (result.etag, result.last_modified, known[0]),
                )
        conn.commit()

    if verbose:
        if published_at or last_modified:
            print(f"Last known publication : {published_at or last_modified}")
        else:
            print("Last known publication : (none recorded yet)")
        print(f"Server Last-Modified   : {result.last_modified}")
        print(f"Server ETag            : {result.etag}")
        print()
        print("CHANGED - the timetable was republished." if changed
              else "No change since the last recorded sync.")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_runs (finished_at, index_changed, pdfs_checked, note)
            VALUES (now(), %s, 0, %s)
            """,
            (changed, "check only"),
        )
    conn.commit()
    return changed


def _archive_registry(registry: Path, replacement: bytes) -> Path | None:
    """
    Move an existing registry aside, named for the publication it describes.

    UWI exposes no history endpoint, so an overwritten registry is gone for
    good and with it any resource-level diff between two publications - which
    is how a withdrawn PDF is spotted at all. Renames rather than copies, and
    never reuses a name, so nothing can be lost here.

    Returns the archive path, or None when there was nothing worth keeping.
    """
    if not registry.exists():
        return None
    previous = registry.read_bytes()
    if previous == replacement:
        return None

    published = parse_published_at(previous.decode("utf-8", "replace"))
    stamp = published.date().isoformat() if published else "unknown"
    archive = registry.with_name(f"{registry.stem}-previous-{stamp}{registry.suffix}")
    attempt = 2
    while archive.exists():
        archive = registry.with_name(
            f"{registry.stem}-previous-{stamp}-{attempt}{registry.suffix}"
        )
        attempt += 1

    registry.rename(archive)
    return archive


def _write_registry(registry: Path, body: bytes) -> None:
    """
    Replace the registry in one step, never leaving a partial file behind.

    Publication identity is the sha256 of exactly these bytes
    (`loader.upsert_publication`), so a half-written registry would not be a
    stale publication - it would be a publication that never existed.
    """
    registry.parent.mkdir(parents=True, exist_ok=True)
    tmp = registry.with_name(registry.name + ".tmp")
    tmp.write_bytes(body)
    os.replace(tmp, registry)


def pull(
    conn,
    pdf_dirs: dict[str, Path],
    *,
    limit: int | None = None,
    registry: Path | None = None,
) -> dict[str, int]:
    """
    Conditionally re-download every PDF we already hold, plus any new ones.

    Files that have not changed cost a 304 and no bytes, so this is cheap
    enough to run daily.

    On a complete pass this also writes the index it fetched to ``registry``.
    It used to fetch the index, enumerate its links and discard it, while
    ``database.cli load`` read the copy on disk. Loading after a republish
    therefore hashed the *previous* index, `upsert_publication` recognised it
    and returned the old publication id, and the new sessions attached to it:
    a class that had moved inserted a second row beside its old one instead of
    replacing it, and `current_sessions` never flipped, so no saved timetable
    was ever prompted to update. None of that failed loudly. The runbook grew
    a manual "refresh finder.xml" step to work around it; writing the bytes we
    already hold removes the step and the trap with it.

    A partial pass - ``limit``, or any file that failed to download - leaves
    the registry alone, because advancing it would claim a publication the
    corpus on disk does not yet hold.
    """
    registry = DEFAULT_REGISTRY if registry is None else registry
    index = fetch(FINDER_XML)
    assert index.body is not None
    published_at = parse_published_at(index.body.decode("utf-8", "replace"))

    import xml.etree.ElementTree as ET

    root = ET.fromstring(index.body)
    links = [
        (r.get("link") or "")
        for r in root.findall("resource")
        if (r.get("link") or "")
    ]
    if limit:
        links = links[:limit]

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO sync_runs (index_changed, note) VALUES (%s, %s) RETURNING id
            """,
            (True, f"pull of {len(links)} resources"),
        )
        row = cur.fetchone()
        assert row is not None
        run_id = row[0]

        cur.execute("SELECT pdf_link, http_etag, http_last_modified FROM pdf_files")
        known = {link: (etag, lm) for link, etag, lm in cur.fetchall()}
    conn.commit()

    checked = changed = added = errors = 0

    for position, link in enumerate(links, 1):
        kind = kind_for_pdf(link)
        target_dir = pdf_dirs.get(kind)
        if target_dir is None:
            continue
        target_dir.mkdir(parents=True, exist_ok=True)
        destination = target_dir / link

        etag, last_modified = known.get(link, (None, None))
        if not destination.exists():
            etag, last_modified = None, None

        try:
            result = fetch(
                BASE_URL + link, etag=etag, last_modified=last_modified, method="GET"
            )
        except Exception as exc:  # noqa: BLE001 - one bad file must not stop the sync
            print(f"  ! {link}: {exc}")
            errors += 1
            continue

        checked += 1
        if result.status == 304:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE pdf_files SET last_checked_at = now() WHERE pdf_link = %s",
                    (link,),
                )
            conn.commit()
        else:
            if result.body:
                is_new = not destination.exists()
                destination.write_bytes(result.body)
                changed += 1
                added += int(is_new)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pdf_files
                        (pdf_link, kind, http_etag, http_last_modified, byte_size,
                         content_changed_at, last_checked_at)
                    VALUES (%s, %s, %s, %s, %s, now(), now())
                    ON CONFLICT (pdf_link) DO UPDATE SET
                        http_etag = EXCLUDED.http_etag,
                        http_last_modified = EXCLUDED.http_last_modified,
                        byte_size = EXCLUDED.byte_size,
                        content_changed_at = now(),
                        last_checked_at = now()
                    """,
                    (
                        link,
                        kind,
                        result.etag,
                        result.last_modified,
                        len(result.body or b""),
                    ),
                )
            conn.commit()
            time.sleep(DELAY_SEC)

        if position % 100 == 0:
            print(f"  {position}/{len(links)} checked, {changed} changed")

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE sync_runs
               SET finished_at = now(), pdfs_checked = %s,
                   pdfs_changed = %s, pdfs_added = %s
             WHERE id = %s
            """,
            (checked, changed, added, run_id),
        )
    conn.commit()

    print(f"\nPublished at : {published_at}")
    print(f"Checked      : {checked}")
    print(f"Changed      : {changed}  (new: {added})")

    complete = limit is None and errors == 0
    if complete:
        archived = _archive_registry(registry, index.body)
        _write_registry(registry, index.body)
        kept = f", previous kept as {archived.name}" if archived else ""
        print(f"Registry     : {registry} updated{kept}")
    else:
        why = "--limit was set" if limit is not None else f"{errors} file(s) failed"
        print(f"Registry     : {registry} left alone - {why}")
        print("               The corpus is only partly updated. Loading now would")
        print("               attach these sessions to the PREVIOUS publication.")
        print("               Re-run pull until it completes before loading.")

    return {
        "checked": checked,
        "changed": changed,
        "added": added,
        "errors": errors,
        "registry_written": complete,
    }


def history(conn, limit: int = 20) -> None:
    """Print the update history we have accumulated."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT published_at, http_last_modified, discovered_at, resource_count
              FROM publications
             ORDER BY COALESCE(published_at, discovered_at) DESC
             LIMIT %s
            """,
            (limit,),
        )
        publications = cur.fetchall()

        cur.execute(
            """
            SELECT started_at, index_changed, pdfs_checked, pdfs_changed, note
              FROM sync_runs
             ORDER BY started_at DESC
             LIMIT %s
            """,
            (limit,),
        )
        runs = cur.fetchall()

    print("Publications seen (each is one republish of the site):")
    if not publications:
        print("   (none yet - run `pull` to record the current one)")
    for published_at, last_modified, discovered_at, count in publications:
        print(
            f"   published {published_at or '?'}   "
            f"server-mtime {last_modified or '?'}   "
            f"resources {count}   first seen by us {discovered_at:%Y-%m-%d %H:%M}"
        )

    print("\nChecks we have run:")
    if not runs:
        print("   (none yet)")
    for started_at, changed, checked, files_changed, note in runs:
        flag = "CHANGED" if changed else "no change"
        print(
            f"   {started_at:%Y-%m-%d %H:%M}  {flag:<9} "
            f"checked={checked:<5} changed={files_changed:<5} {note or ''}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect and pull timetable updates.")
    parser.add_argument(
        "command", choices=["check", "pull", "history"], help="what to do"
    )
    parser.add_argument("--limit", type=int, help="only process this many PDFs (pull)")
    parser.add_argument(
        "--pdf-dir", default="downloaded_pdfs", help="root directory for PDFs"
    )
    parser.add_argument(
        "--registry",
        default=str(DEFAULT_REGISTRY),
        help="where to write the fetched index (pull); database.cli load reads this",
    )
    parser.add_argument("--quiet", action="store_true", help="suppress non-essential output")
    args = parser.parse_args()

    root = Path(args.pdf_dir)
    pdf_dirs = {"course": root, "staff": root / "staff", "room": root / "rooms"}

    try:
        with connect() as conn:
            apply_schema(conn)
            if args.command == "check":
                changed = check(conn, verbose=not args.quiet)
                return 10 if changed else 0
            if args.command == "pull":
                result = pull(
                    conn, pdf_dirs, limit=args.limit, registry=Path(args.registry)
                )
                # A deliberate --limit run is not a failure; a download that
                # errored is, because the corpus is now half-updated.
                return 0 if result["errors"] == 0 else 1
            history(conn)
            return 0
    except DatabaseNotConfigured as exc:
        print(f"error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
