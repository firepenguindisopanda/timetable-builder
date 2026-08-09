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
