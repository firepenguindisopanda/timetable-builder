"""
Endpoint exposure tests.

Three endpoints read a caller-supplied filesystem path or make the server
fetch the whole CELCAT site. The nav hides their pages behind an `.admin-only`
CSS class, which is not access control: the routes themselves were reachable
by anyone. These tests pin the guard so it cannot quietly come off again.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import main

VALID_KEY = "test-admin-key"


class FakeSettings:
    admin_api_key = VALID_KEY


@pytest.fixture
def client():
    main.app.dependency_overrides[main.get_admin_settings] = lambda: FakeSettings()
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


# The endpoints that must never be open, and a body each accepts.
GUARDED = [
    ("/extract/batch", {"pdf_dir": "/etc"}),
    ("/download", {"codes": ["COMP2601"], "dry_run": True}),
    ("/evaluate", {"pdf_dir": "/etc"}),
]


class TestAdminOnlyEndpoints:
    @pytest.mark.parametrize("path, body", GUARDED)
    def test_rejected_without_a_key(self, client, path, body):
        response = client.post(path, json=body)
        assert response.status_code == 401

    @pytest.mark.parametrize("path, body", GUARDED)
    def test_rejected_with_a_wrong_key(self, client, path, body):
        response = client.post(path, json=body, headers={"X-API-Key": "nope"})
        assert response.status_code == 403

    @pytest.mark.parametrize("path, _body", GUARDED)
    def test_the_guard_is_wired_to_the_route(self, path, _body):
        """
        Assert on the route's dependencies rather than by calling it.

        Calling these for real would glob a directory or fetch from UWI, so
        the wiring is checked directly: the dependency is either on the route
        or it is not.
        """
        route = next(
            r for r in main.app.routes
            if getattr(r, "path", None) == path and "POST" in getattr(r, "methods", ())
        )
        guards = [d.call for d in route.dependant.dependencies]

        assert main.require_admin_key in guards

    def test_a_path_the_caller_supplies_is_not_probed_anonymously(self, client):
        """A 404 here would confirm whether a directory exists on the server."""
        response = client.post("/extract/batch", json={"pdf_dir": "/root/secret"})
        assert response.status_code == 401


class TestAdminDisabled:
    """
    A deployment serving only the public timetable leaves ADMIN_API_KEY unset.

    That has to close the admin surface rather than open it, and has to be
    distinguishable from the server being broken.
    """

    @pytest.fixture
    def no_key_client(self):
        class Unset:
            admin_api_key = ""

        main.app.dependency_overrides[main.get_admin_settings] = lambda: Unset()
        with TestClient(main.app) as test_client:
            yield test_client
        main.app.dependency_overrides.clear()

    @pytest.mark.parametrize("path, body", GUARDED)
    def test_endpoints_are_closed_not_open(self, no_key_client, path, body):
        response = no_key_client.post(path, json=body)
        assert response.status_code == 503

    def test_even_a_guessed_key_is_refused(self, no_key_client):
        response = no_key_client.post(
            "/extract/batch", json={"pdf_dir": "/etc"}, headers={"X-API-Key": ""}
        )
        assert response.status_code == 503

    def test_the_message_says_which_setting_is_missing(self, no_key_client):
        detail = no_key_client.post("/download", json={}).json()["detail"]
        assert "ADMIN_API_KEY" in detail

    def test_the_public_timetable_is_unaffected(self, no_key_client):
        assert no_key_client.get("/health").status_code == 200


class TestKeyComparison:
    """
    The key is compared in constant time.

    Timing cannot be asserted on reliably in a test suite, so these pin the
    two things that can be: the comparison is the constant-time one, and it
    survives the inputs that would make it raise instead of returning False.
    """

    def test_the_right_key_is_accepted(self, client):
        response = client.post("/admin/verify", json={"api_key": VALID_KEY})

        assert response.status_code == 200
        assert response.json()["valid"] is True

    def test_a_wrong_key_of_the_same_length_is_refused(self, client):
        wrong = "x" * len(VALID_KEY)

        assert client.post("/admin/verify", json={"api_key": wrong}).status_code == 403

    @pytest.mark.parametrize(
        "supplied",
        [
            "",
            "test-admin-ke",          # one character short
            "test-admin-keys",        # one character long
            "test-admin-key ",        # trailing space
            "TEST-ADMIN-KEY",         # wrong case
        ],
    )
    def test_near_misses_are_refused(self, client, supplied):
        response = client.post("/admin/verify", json={"api_key": supplied})

        assert response.status_code == 403

    @pytest.mark.parametrize("supplied", ["café", "ключ", "🔑", "test-admin-keyé"])
    def test_a_non_ascii_key_is_refused_rather_than_crashing(self, client, supplied):
        """
        `secrets.compare_digest` raises TypeError on a `str` holding anything
        outside ASCII, which would turn a wrong key into a 500 and hand an
        anonymous caller a way to raise errors on the server. Both sides are
        encoded to bytes to keep it a plain refusal.
        """
        response = client.post("/admin/verify", json={"api_key": supplied})

        assert response.status_code == 403

    def test_a_non_ascii_header_key_is_refused_rather_than_crashing(self, client):
        """
        Sent as raw latin-1 bytes, which is how a header can carry a byte
        above 0x7F at all. Starlette decodes it back to a `str` with a
        non-ASCII character in it, and an unencoded `compare_digest` would
        raise TypeError there and answer 500.

        The header is bytes rather than `str` because httpx refuses to send
        the latter, not because the server would not see it.
        """
        response = client.post(
            "/extract/batch",
            json={"pdf_dir": "/etc"},
            headers={"X-API-Key": "café".encode("latin-1")},
        )

        assert response.status_code == 403

    def test_the_comparison_helper_is_constant_time(self):
        """
        Read the source rather than the clock: a timing measurement here would
        be flaky, but a reintroduced `==` is a plain text match away.
        """
        import inspect

        source = inspect.getsource(main.admin_key_matches)

        assert "compare_digest" in source

    @pytest.mark.parametrize("name", ["require_admin_key", "admin_verify_key"])
    def test_neither_call_site_compares_keys_with_equality(self, name):
        """The helper is worthless if a call site goes back to `==`."""
        import inspect
        import re

        source = inspect.getsource(getattr(main, name))

        assert not re.search(r"[!=]=\s*settings\.admin_api_key", source), (
            f"{name} compares the admin key with equality"
        )
        assert "admin_key_matches" in source, f"{name} does not use the helper"


class TestPublicEndpoints:
    """The student-facing routes must stay open."""

    @pytest.mark.parametrize("path", ["/health", "/", "/calendar", "/extract"])
    def test_still_reachable_without_a_key(self, client, path):
        assert client.get(path).status_code == 200

    def test_uploading_your_own_pdf_needs_no_key(self, client):
        """`/extract` takes an upload, not a server path, so it stays public."""
        response = client.post("/extract", files={})
        # Rejected for having no file, not for having no key.
        assert response.status_code == 422


class TestCors:
    def test_credentials_are_not_allowed_cross_origin(self, client):
        """
        Wildcard origin plus credentials is rejected by browsers anyway, and
        would be unsafe if it were not. Nothing here authenticates by cookie.
        """
        response = client.get("/health", headers={"Origin": "https://evil.example"})

        assert response.headers.get("access-control-allow-credentials") is None
        assert response.headers.get("access-control-allow-origin") == "*"

    def test_preflight_advertises_only_the_headers_in_use(self, client):
        response = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-api-key",
            },
        )
        allowed = response.headers.get("access-control-allow-headers", "").lower()

        assert response.status_code == 200
        assert "x-api-key" in allowed
        assert "access-control-allow-credentials" not in response.headers

    def test_delete_is_not_an_allowed_method(self, client):
        response = client.options(
            "/health",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        assert "DELETE" not in response.headers.get("access-control-allow-methods", "")
