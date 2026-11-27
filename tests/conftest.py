"""
Shared fixtures.

The default term is chosen by date (SEMESTERS-SPEC.md 7.1): semester 1
2026/27 until its teaching ended on 20 Nov 2026, semester 2 after. Every test
runs on a fixed campus day during semester 1's teaching, so what a page
serves when no term is named does not change with the day the suite is run.
A test about the default term moves the clock itself.
"""

from __future__ import annotations

from datetime import date

import pytest

import explore_router

#: A Tuesday in semester 1 2026/27's week 11.
SEMESTER_1_DAY = date(2026, 11, 10)


@pytest.fixture(autouse=True)
def campus_day(monkeypatch):
    monkeypatch.setattr(explore_router, "campus_today", lambda: SEMESTER_1_DAY)
    return SEMESTER_1_DAY
