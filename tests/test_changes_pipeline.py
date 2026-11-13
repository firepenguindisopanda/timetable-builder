"""
The changes page, from session rows to the card a student reads.

`test_changes_page.py` pins the page's contract with hand-built cards, each
with `display_kind` already set. That is how 12 Nov 2026 got through: the
page called eleven weeks-only changes "moved" and printed WAS and NOW rows
that looked the same, while every test passed. Here nothing is hand-built.
Each case's two publications go through `diff_sessions`, `shape_changes`
and the real route and template, and every card is checked against what it
shows:

- a "moved" card differs in day, time or room, not only in weeks
- a "weeks changed" card keeps its place and says which weeks in words
- no card falls back to the bare label "changed"
- no card's WAS and NOW rows read the same

The cases are the ones in tests/fixtures/change_wording.json, so the page and
the builder are tested against the same changes.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import explore_router
import main
from timetable_extractor.database.changes import diff_sessions, shape_changes

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "change_wording.json").read_text(encoding="utf-8")
)

NOV_6 = datetime(2026, 11, 6, 14, 53, tzinfo=timezone.utc)
NOV_12 = datetime(2026, 11, 12, 14, 43, tzinfo=timezone.utc)

_CARD = re.compile(r'<article class="card chg [^"]*"[^>]*>(.*?)</article>', re.S)
_KIND = re.compile(r'<span class="chg-kind">(.*?)</span>', re.S)
_NOTE = re.compile(r'<p class="chg-note">(.*?)</p>', re.S)
_SLOT = re.compile(r'<div class="chg-slot chg-slot--(was|now)">(.*?)</div>', re.S)
_SPAN = re.compile(r'<span class="([^"]*)">(.*?)</span>', re.S)


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _slot(fragment: str) -> dict[str, str]:
    """One WAS or NOW row as the reader sees it, field by field."""
    spans = [(cls, _text(body)) for cls, body in _SPAN.findall(fragment)]
    mono = [text for cls, text in spans if cls == "mono"]
    return {
        "place": " ".join(mono + [t for c, t in spans if c == "chg-room"]),
        "weeks": next((t for c, t in spans if "chg-weeks" in c), ""),
    }


def render(rows_before: list[dict], rows_after: list[dict], monkeypatch) -> str:
    changes = [asdict(c) for c in diff_sessions(rows_before, rows_after)]
    page = {
        "from_id": 15,
        "to_id": 16,
        "from_published_at": NOV_6,
        "to_published_at": NOV_12,
        **shape_changes(changes),
    }

    def query(fn, *args):
        if fn.__name__ == "changes_for_page":
            return page
        if fn.__name__ == "freshness":
            return {"publication_id": 16, "published_at": NOV_12,
                    "imported_at": NOV_12, "checked_at": NOV_12,
                    "resource_count": 1617, "check_count": 1,
                    "publication_count": 16, "update_pending": False}
        raise AssertionError(f"unexpected query: {fn.__name__}")

    monkeypatch.setattr(explore_router, "query", query)
    explore_router.clear_cache()
    try:
        with TestClient(main.app) as client:
            return client.get("/explore/changes").text
    finally:
        explore_router.clear_cache()


def cards(page: str) -> list[dict]:
    found = []
    for body in _CARD.findall(page):
        slots = [(which, _slot(fragment)) for which, fragment in _SLOT.findall(body)]
        found.append({
            "kind": _text(_KIND.search(body).group(1)),
            "notes": [_text(n) for n in _NOTE.findall(body)],
            "was": [s for which, s in slots if which == "was"],
            "now": [s for which, s in slots if which == "now"],
        })
    return found


def places(slots: list[dict]) -> list[str]:
    return sorted(s["place"] for s in slots)


def rows_read(slots: list[dict]) -> list[tuple[str, str]]:
    return sorted((s["place"], s["weeks"]) for s in slots)


@pytest.mark.parametrize("case", FIXTURE["cases"], ids=lambda c: c["name"])
def test_every_card_shows_what_its_label_claims(case, monkeypatch):
    page = render(case["before"], case["after"], monkeypatch)
    found = cards(page)
    assert found, "the change never reached the page"

    for card in found:
        assert card["kind"] != "changed", "a kind with no label on the page"

        if card["was"] and card["now"]:
            assert rows_read(card["was"]) != rows_read(card["now"]), (
                f"{card['kind']!r} card with WAS and NOW rows that read the same"
            )

        if card["kind"] == "moved":
            assert places(card["was"]) != places(card["now"]), (
                "called moved, but day, time and room are all unchanged"
            )
        if card["kind"] == "weeks changed":
            assert places(card["was"]) == places(card["now"])
            assert card["notes"], "weeks changed without saying which"


def test_changes_a_student_could_not_see_never_reach_the_page(monkeypatch):
    """
    Beside one real move, a class whose weeks were re-spelled and one whose
    placeholder venue was re-worded. Only the move is a card: the other two
    would print rows the reader cannot tell apart.
    """
    (case,) = [c for c in FIXTURE["cases"] if c["name"] == "a class on another day"]
    quiet_before = [
        {**case["before"][0], "code": "OPTM 3011", "weeks_raw": "W1 - W12"},
        {**case["before"][0], "code": "COMS 6003", "room": "TBA"},
    ]
    quiet_after = [
        {**case["before"][0], "code": "OPTM 3011", "weeks_raw": "W1-W12"},
        {**case["before"][0], "code": "COMS 6003", "room": "Venue to be advised"},
    ]
    page = render(case["before"] + quiet_before, case["after"] + quiet_after, monkeypatch)
    assert [card["kind"] for card in cards(page)] == ["moved"]
    assert "OPTM 3011" not in page and "COMS 6003" not in page


def test_the_case_that_shipped_on_12_november(monkeypatch):
    """CHNG 6206 on 6 Nov 2026: same Thursday hour and room, week 10 gone."""
    (case,) = [c for c in FIXTURE["cases"] if "CHNG 6206" in c["name"]]
    (card,) = cards(render(case["before"], case["after"], monkeypatch))
    assert card["kind"] == "weeks changed"
    assert card["notes"] == ["No class in W10"]
