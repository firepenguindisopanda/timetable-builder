"""
The student pages read as one site.

The timetable builder used to wear the extractor's header: "CELCAT Extractor
v1.0.0", Upload, a static "API Online" label, API Docs and a Meme button that
played a sound. A student moving between it and the explorer met two
products. It now shares the explorer's header and freshness line; the
extraction tools keep their own.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import explore_router
import main
from timetable_extractor.database import explore_queries as eq

NOW = datetime(2026, 10, 12, 22, 45, tzinfo=timezone.utc)


@pytest.fixture
def client(monkeypatch):
    def fake(fn, *args):
        if fn is eq.freshness:
            return {"publication_id": 11, "published_at": NOW, "imported_at": NOW,
                    "checked_at": NOW, "resource_count": 1629, "check_count": 39,
                    "publication_count": 11, "update_pending": False}
        raise explore_router.ExplorerUnavailable("not needed here")

    monkeypatch.setattr(explore_router, "query", fake)
    explore_router.clear_cache()
    with TestClient(main.app) as test_client:
        yield test_client
    explore_router.clear_cache()


def test_the_builder_wears_the_explorers_header(client):
    body = client.get("/calendar").text
    assert "UWI St. Augustine" in body
    assert 'href="/calendar" aria-current="page">Build a timetable' in body
    assert 'href="/explore/rooms"' in body


@pytest.mark.parametrize("chrome", ['id="memeBtn"', 'id="healthDot"', "API Docs",
                                    "CELCAT Extractor", "amazin.mp3"])
def test_the_builder_carries_no_developer_chrome(client, chrome):
    assert chrome not in client.get("/calendar").text


def test_the_builder_says_where_its_classes_came_from(client):
    body = client.get("/calendar").text
    assert 'class="rail"' in body
    assert "Up to date" in body


def test_the_builder_has_a_skip_link_to_its_content(client):
    body = client.get("/calendar").text
    assert 'class="skip-link" href="#main"' in body
    assert '<main id="main"' in body


def test_the_builder_is_titled_for_students(client):
    assert "<title>My timetable · UWI St. Augustine</title>" in client.get("/calendar").text


def test_the_tool_pages_keep_their_own_header_without_the_meme(client):
    body = client.get("/extract").text
    assert "CELCAT Extractor" in body
    assert "API Docs" in body
    assert 'id="memeBtn"' not in body
    assert "amazin.mp3" not in body


def test_the_builder_still_renders_with_the_warehouse_down(monkeypatch):
    def down(fn, *args):
        raise explore_router.ExplorerUnavailable("down")

    monkeypatch.setattr(explore_router, "query", down)
    explore_router.clear_cache()
    with TestClient(main.app) as client:
        body = client.get("/calendar").text
    explore_router.clear_cache()
    assert 'id="calendarWrapper"' in body
    assert 'class="rail"' not in body
