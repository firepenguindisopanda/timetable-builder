"""
The diff's half of the contract with the builder's change notes.

On 12 Nov 2026 the API began sending `displayKind: 'weeks_changed'` and the
builder, which had no wording for it, told students "Postgraduate changed"
where it used to say which weeks. Both suites passed, because each tested its
own layer with a hand-built entry. The cases in
tests/fixtures/change_wording.json are shared with
tests/js/change-wording.test.js: here the session rows must still produce the
stored API entry, there the entry must still produce the stored line.

After a deliberate change to `_api_entry`, regenerate the entries with
`uv run --group test python -m tests.test_change_wording --write` and review
the diff. The lines are written by hand.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

from timetable_extractor.database.changes import (
    _CLASS_KIND_ORDER,
    COURSE_ADDED,
    COURSE_DROPPED,
    COURSE_RENAMED,
    _api_entry,
    diff_sessions,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "change_wording.json"
FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

#: Every kind the builder can be sent. `_CLASS_KIND_ORDER` is the page's list
#: of class kinds, so a kind added there for the page reaches the API too.
EMITTED_KINDS = set(_CLASS_KIND_ORDER) | {COURSE_ADDED, COURSE_DROPPED, COURSE_RENAMED}


def api_entries(case: dict) -> list[dict]:
    return [_api_entry(asdict(c)) for c in diff_sessions(case["before"], case["after"])]


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_the_rows_still_produce_the_entry_the_builder_is_tested_against(case):
    assert api_entries(case) == [case["entry"]], (
        "The API entry for this case changed. If that was deliberate, "
        "regenerate with `uv run --group test python -m "
        "tests.test_change_wording --write`, then check the builder's line "
        "for it in tests/js/change-wording.test.js."
    )


def test_every_kind_the_api_can_send_has_a_case():
    """
    A new kind with no case here is a kind the builder has never been shown,
    which is exactly how `weeks_changed` reached students as "changed".
    """
    covered = {case["entry"]["displayKind"] for case in FIXTURE["cases"]}
    assert EMITTED_KINDS <= covered, f"no case for {sorted(EMITTED_KINDS - covered)}"


def _write() -> None:
    for case in FIXTURE["cases"]:
        (case["entry"],) = api_entries(case)
    # Bytes, not text: text mode on Windows would turn every newline into
    # CRLF and rewrite the whole file on a no-op regenerate.
    FIXTURE_PATH.write_bytes((json.dumps(FIXTURE, indent=2) + "\n").encode("utf-8"))


if __name__ == "__main__" and "--write" in sys.argv:
    _write()
