"""
The course, room and staff tables on a phone.

Below 620px each row of `table.sessions` is laid out as a card, and every
line on it is labelled from its cell's `data-label`. Until 13 Nov 2026 the
table kept its 720px width inside a sideways scroller, and Weeks, its last
column, was off-screen on every row: the same layout that hid the weeks on
the changes page on 12 Nov. A column added without a label would print an
unlabelled line on a phone and nothing would fail, so this pins it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).parent.parent / "templates" / "explore"

_TABLE = re.compile(r'<table class="sessions">(.*?)</table>', re.S)
_HEADER = re.compile(r"<th scope=\"col\">(.*?)</th>|ui\.th_(weeks|sources)\(\)")
_CELL = re.compile(r"<td([^>]*)>")


@pytest.mark.parametrize("page", ["course", "room", "staff"])
def test_every_column_is_labelled_for_the_phone_layout(page):
    (table,) = _TABLE.findall((TEMPLATES / f"{page}.html").read_text(encoding="utf-8"))
    head, body = table.split("<tbody>")
    headers = [plain or macro.title() for plain, macro in _HEADER.findall(head)]

    labels = []
    for attrs in _CELL.findall(body):
        if re.search(r'class="cell-(day|time)"', attrs):
            continue  # the card's heading, which needs no label
        match = re.search(r'data-label="([^"]+)"', attrs)
        assert match, f"{page}: a cell with no data-label"
        labels.append(match.group(1))

    assert labels == headers[2:], f"{page}: labels do not follow the header row"
