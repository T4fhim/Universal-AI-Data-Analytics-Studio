# File: apps/api/tests/apihelpers.py
"""A browser-like API client for the 3.3 tests: session cookie plus real CSRF enforcement.

Why: Django's test ``Client`` skips CSRF checks by default, which would make every
"state-changing request needs the token" test pass vacuously. :class:`Api` therefore
builds the client with ``enforce_csrf_checks=True`` and behaves like the SPA: it first
calls allauth's ``GET /api/auth/browser/v1/config`` (which sets the ``csrftoken`` cookie)
and echoes the *current* cookie in ``X-CSRFToken`` on unsafe methods (a login rotates it,
so it is re-read for every request). ``csrf=False`` sends the same request *without* the
header, to prove the server refuses it.

Responses are typed ``Any``: the test client returns Django's monkey-patched response
(with ``.json()``), a class django-stubs only exposes privately.
"""

from __future__ import annotations

import json
from typing import Any

from django.test import Client

from uadas_api.accounts.models import User

CONFIG_URL = "/api/auth/browser/v1/config"
_JSON = "application/json"


class Api:
    """One browser session: an optional logged-in user, a CSRF cookie, JSON helpers."""

    def __init__(self, user: User | None = None) -> None:
        self.client = Client(enforce_csrf_checks=True)
        if user is not None:
            self.client.force_login(user)
        self.client.get(CONFIG_URL)  # sets the csrftoken cookie, as the SPA does first

    @property
    def token(self) -> str:
        """The *current* CSRF cookie value (login rotates it, so never cache it)."""
        return self.client.cookies["csrftoken"].value

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        csrf: bool = True,
    ) -> Any:
        headers = {"X-CSRFToken": self.token} if csrf else {}
        data = json.dumps(body) if body is not None else ""
        return self.client.generic(
            method, path, data, content_type=_JSON, headers=headers
        )

    def get(self, path: str) -> Any:
        return self.request("GET", path)

    def post(
        self, path: str, body: dict[str, Any] | None = None, *, csrf: bool = True
    ) -> Any:
        return self.request("POST", path, body, csrf=csrf)

    def patch(
        self, path: str, body: dict[str, Any] | None = None, *, csrf: bool = True
    ) -> Any:
        return self.request("PATCH", path, body, csrf=csrf)

    def delete(self, path: str, *, csrf: bool = True) -> Any:
        return self.request("DELETE", path, csrf=csrf)
