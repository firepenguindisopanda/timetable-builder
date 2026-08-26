"""
`sync pull` has to leave the registry on disk describing the corpus on disk.

It used to fetch finder.xml, read the links out of it and throw it away, while
`database.cli load` read the copy on disk. After a republish that meant load
hashed the *previous* index, `upsert_publication` recognised the hash and
handed back the old publication id, and the new sessions attached to it - a
moved class inserting a second row beside its old one, and `current_sessions`
never flipping, so no saved timetable was ever prompted. Nothing failed
loudly; the runbook grew a manual step instead.

What is pinned here is that a complete pull advances the registry, that a
partial one does not (advancing it would claim a publication the corpus does
not yet hold), and that the previous registry is never lost or overwritten,
since UWI publishes no history and it is the only way to diff two
publications at the resource level.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from timetable_extractor import sync

FOOTER = "Published {stamp} - University of the West Indies St. Augustine"


def registry_bytes(stamp: str = "21-Aug-26 4:03:34 PM", links: tuple[str, ...] = ("m1.pdf",)) -> bytes:
    resources = "".join(f'<resource link="{link}" />' for link in links)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<finder><footer>{FOOTER.format(stamp=stamp)}</footer>{resources}</finder>"
    ).encode("utf-8")


class FakeCursor:
    """Enough of a psycopg cursor for pull's six statements."""

    def __init__(self, log: list[str]) -> None:
        self.log = log

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: tuple = ()) -> None:
        self.log.append(sql.strip().split()[0].upper())

    def fetchone(self) -> tuple[int]:
        return (1,)

    def fetchall(self) -> list[tuple]:
        return []


class FakeConnection:
    def __init__(self) -> None:
        self.log: list[str] = []

    def cursor(self) -> FakeCursor:
        return FakeCursor(self.log)

    def commit(self) -> None:
        return None


@pytest.fixture
def no_delay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sync, "DELAY_SEC", 0)


def run_pull(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    index: bytes,
    registry: Path,
    limit: int | None = None,
    failing: set[str] | None = None,
) -> dict[str, int]:
    """Drive pull with the network faked and every PDF reporting as changed."""
    failing = failing or set()

    def fake_fetch(url: str, *, etag=None, last_modified=None, method="GET"):
        if url == sync.FINDER_XML:
            return sync.HeadResult(200, None, None, index)
        if any(url.endswith(name) for name in failing):
            raise OSError("connection reset")
        return sync.HeadResult(200, '"abc"', None, b"%PDF-1.4 fake")

    monkeypatch.setattr(sync, "fetch", fake_fetch)
    root = tmp_path / "downloaded_pdfs"
    pdf_dirs = {"course": root, "staff": root / "staff", "room": root / "rooms"}
    return sync.pull(
        FakeConnection(), pdf_dirs, limit=limit, registry=registry
    )


def test_complete_pull_writes_the_registry(monkeypatch, tmp_path, no_delay):
    registry = tmp_path / "finder.xml"
    index = registry_bytes(links=("m1.pdf", "m2.pdf"))

    result = run_pull(monkeypatch, tmp_path, index=index, registry=registry)

    assert result["registry_written"] is True
    assert registry.read_bytes() == index


def test_a_limited_pull_leaves_the_registry_alone(monkeypatch, tmp_path, no_delay):
    """--limit stops early, so the corpus does not yet hold the new publication."""
    registry = tmp_path / "finder.xml"
    registry.write_bytes(registry_bytes(stamp="14-Aug-26 3:41:35 PM"))

    result = run_pull(
        monkeypatch,
        tmp_path,
        index=registry_bytes(links=("m1.pdf", "m2.pdf")),
        registry=registry,
        limit=1,
    )

    assert result["registry_written"] is False
    assert sync.parse_published_at(registry.read_text()).day == 14


def test_a_failed_download_leaves_the_registry_alone(monkeypatch, tmp_path, no_delay):
    """One unreachable PDF means the corpus is half-updated. Do not claim it."""
    registry = tmp_path / "finder.xml"
    registry.write_bytes(registry_bytes(stamp="14-Aug-26 3:41:35 PM"))

    result = run_pull(
        monkeypatch,
        tmp_path,
        index=registry_bytes(links=("m1.pdf", "m2.pdf")),
        registry=registry,
        failing={"m2.pdf"},
    )

    assert result["errors"] == 1
    assert result["registry_written"] is False
    assert sync.parse_published_at(registry.read_text()).day == 14


def test_the_previous_registry_is_kept_under_its_publication_date(
    monkeypatch, tmp_path, no_delay
):
    registry = tmp_path / "finder.xml"
    registry.write_bytes(registry_bytes(stamp="14-Aug-26 3:41:35 PM"))

    run_pull(
        monkeypatch,
        tmp_path,
        index=registry_bytes(stamp="21-Aug-26 4:03:34 PM"),
        registry=registry,
    )

    archive = tmp_path / "finder-previous-2026-08-14.xml"
    assert archive.exists()
    assert sync.parse_published_at(archive.read_text()).day == 14
    assert sync.parse_published_at(registry.read_text()).day == 21


def test_writing_leaves_no_temporary_file_behind(monkeypatch, tmp_path, no_delay):
    """Publication identity is this file's sha256, so a stray .tmp would be a
    publication that never existed if anything ever read it."""
    registry = tmp_path / "finder.xml"

    run_pull(monkeypatch, tmp_path, index=registry_bytes(), registry=registry)

    assert list(tmp_path.glob("*.tmp")) == []


def test_archiving_an_absent_registry_is_a_no_op(tmp_path):
    assert sync._archive_registry(tmp_path / "finder.xml", b"<finder/>") is None


def test_an_unchanged_registry_is_not_archived(tmp_path):
    """Re-running pull on the same publication must not litter archives."""
    registry = tmp_path / "finder.xml"
    body = registry_bytes()
    registry.write_bytes(body)

    assert sync._archive_registry(registry, body) is None
    assert list(tmp_path.glob("finder-previous-*")) == []


def test_an_existing_archive_is_never_overwritten(tmp_path):
    """Two different indexes published the same day must both survive."""
    registry = tmp_path / "finder.xml"
    taken = tmp_path / "finder-previous-2026-08-14.xml"
    taken.write_bytes(b"<finder>first</finder>")
    registry.write_bytes(registry_bytes(stamp="14-Aug-26 3:41:35 PM"))

    archive = sync._archive_registry(registry, b"<finder>new</finder>")

    assert archive == tmp_path / "finder-previous-2026-08-14-2.xml"
    assert taken.read_bytes() == b"<finder>first</finder>"


def test_an_unreadable_publication_date_still_archives(tmp_path):
    """A footer CELCAT has reworded must not cost us the previous registry."""
    registry = tmp_path / "finder.xml"
    registry.write_bytes(b"<finder><footer>no date here</footer></finder>")

    archive = sync._archive_registry(registry, b"<finder>new</finder>")

    assert archive == tmp_path / "finder-previous-unknown.xml"
    assert not registry.exists()
