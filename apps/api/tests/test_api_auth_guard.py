# File: apps/api/tests/test_api_auth_guard.py
"""Every Ninja operation is authenticated and CSRF-protected unless explicitly public.

Why: Django Ninja marks *all* its views ``csrf_exempt`` at the Django-middleware level and
leaves CSRF to the authentication class (``SessionAuth(csrf=True)`` calls Django's CSRF
check itself). So a route declared without ``auth=`` is silently both unauthenticated and
CSRF-free. The API therefore sets ``auth=session_auth`` globally and opts the one public
route (the liveness probe) out; this test walks every registered operation so that a future
router cannot forget -- it fails on any operation that is neither the allow-listed public
route nor protected by a CSRF-enforcing cookie auth. The final test shows the behaviour is
real, not just declared.
"""

from __future__ import annotations

import pytest
from apihelpers import Api
from ninja.security import SessionAuth
from ninja.security.apikey import APIKeyCookie

from uadas_api.accounts.security import session_auth
from uadas_api.api import api, build_api

# The CSRF bootstrap (allauth's /config) reads the SocialApp table, so the behavioural test
# needs the database; the structural tests do not touch it.
pytestmark = pytest.mark.django_db

PUBLIC = {("GET", "/health")}


def _operations() -> list[tuple[str, str, list[object]]]:
    found: list[tuple[str, str, list[object]]] = []
    # The *bound* routers carry each operation with the API-wide default auth applied (the
    # template routers in ``api._routers`` do not). Building the URLs binds them; do it
    # explicitly so the result never depends on whether another test already did.
    _ = api.urls
    for bound in api._get_bound_routers():
        for path, path_view in bound.path_operations.items():
            for op in path_view.operations:
                for method in op.methods:
                    found.append(
                        (method, f"{bound.prefix}{path}", list(op.auth_callbacks))
                    )
    return found


def test_the_registered_operations_are_discovered() -> None:
    methods_and_paths = {(m, p) for m, p, _ in _operations()}
    # Guards the guard: if discovery silently found nothing, the checks below would pass.
    assert ("GET", "/health") in methods_and_paths
    assert ("GET", "/me") in methods_and_paths
    assert ("POST", "/organizations") in methods_and_paths
    assert (
        "PATCH",
        "/organizations/{org_id}/members/{membership_id}",
    ) in methods_and_paths
    assert (
        "DELETE",
        "/organizations/{org_id}/members/{membership_id}",
    ) in methods_and_paths


def test_only_the_allow_listed_routes_are_public() -> None:
    public = {(m, p) for m, p, auth in _operations() if not auth}
    assert public == PUBLIC


def test_every_protected_operation_uses_csrf_enforcing_cookie_auth() -> None:
    for method, path, auth in _operations():
        if (method, path) in PUBLIC:
            continue
        assert auth, (method, path)
        for callback in auth:
            assert isinstance(callback, APIKeyCookie), (method, path)
            assert callback.csrf is True, (method, path)
            assert isinstance(callback, SessionAuth), (method, path)


def test_a_freshly_built_api_has_the_same_default() -> None:
    for debug in (False, True):
        configured = build_api(debug=debug).auth  # Ninja keeps the default as a list
        assert isinstance(configured, list)
        (default,) = configured
        assert default is session_auth  # the one CSRF-enforcing session instance
        assert isinstance(default, SessionAuth)
        assert default.csrf is True


def test_the_public_route_works_without_a_session_and_protected_ones_do_not() -> None:
    anonymous = Api()
    assert anonymous.get("/api/health").status_code == 200
    assert anonymous.get("/api/me").status_code == 401
    assert (
        anonymous.post("/api/organizations", {"name": "x"}, csrf=False).status_code
        == 403
    )
