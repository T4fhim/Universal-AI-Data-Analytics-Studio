# File: apps/api/tests/test_oauth_runtime.py
"""OAuth providers at runtime: present only with credentials, never reaching the network.

Why a subprocess: which providers exist is decided when Django starts (the provider apps are
in ``INSTALLED_APPS``, their URLs are mounted at import time), so it cannot be flipped inside
the running test process. Each test therefore starts a fresh interpreter with a chosen
environment, migrates an in-memory database, and drives the real URLconf with a test client.
Building the provider *redirect* needs no network (it only constructs the authorize URL), and
the credentials are obvious fakes. Paired cases: with credentials the provider is listed and
redirects to the right authorize endpoint; without them it is neither listed nor routable.
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from collections.abc import Callable
from pathlib import Path
from typing import Any

API_ROOT = Path(__file__).resolve().parents[1]
EnvBuilder = Callable[..., dict[str, str]]

PROBE = textwrap.dedent("""
    import json
    import django

    django.setup()
    from django.core.management import call_command
    from django.test import Client

    call_command("migrate", verbosity=0)
    client = Client(enforce_csrf_checks=True)
    config = client.get("/api/auth/browser/v1/config").json()
    token = client.cookies["csrftoken"].value
    out = {"providers": sorted(p["id"] for p in config["data"]["socialaccount"]["providers"])}

    def redirect(provider, csrf=True, callback="/done"):
        headers = {"X-CSRFToken": token} if csrf else {}
        response = client.post(
            "/api/auth/browser/v1/auth/provider/redirect",
            {"provider": provider, "callback_url": callback, "process": "login"},
            headers=headers,
        )
        return response.status_code, response.get("Location", "")

    out["evil_callback"] = redirect("github", callback="https://evil.example/steal")
    out["scheme_relative_callback"] = redirect("github", callback="//evil.example/x")

    for provider in ("github", "google"):
        out[provider] = redirect(provider)
    out["github_without_csrf"] = redirect("github", csrf=False)[0]
    out["callback_route"] = client.get("/api/auth/oauth/github/login/callback/").status_code
    print("PROBE:" + json.dumps(out))
    """)


def _probe(env: dict[str, str]) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=API_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(ln for ln in result.stdout.splitlines() if ln.startswith("PROBE:"))
    parsed: dict[str, Any] = json.loads(line.removeprefix("PROBE:"))
    return parsed


def test_providers_with_credentials_are_listed_and_redirect_to_their_authorize_url(
    subprocess_env: EnvBuilder,
) -> None:
    out = _probe(
        subprocess_env(
            DJANGO_SETTINGS_MODULE="uadas_api.settings.test",
            GITHUB_CLIENT_ID="fake-gh-id",
            GITHUB_CLIENT_SECRET="fake-gh-secret",  # nosec B106
            GOOGLE_CLIENT_ID="fake-g-id",
            GOOGLE_CLIENT_SECRET="fake-g-secret",  # nosec B106
        )
    )
    assert out["providers"] == ["github", "google"]
    status, location = out["github"]
    assert status == 302
    assert location.startswith("https://github.com/login/oauth/authorize?")
    assert "client_id=fake-gh-id" in location
    assert "fake-gh-secret" not in location  # the secret never leaves the server
    # The callback is mounted under /api/auth/oauth/ (a redirect URI to register).
    assert "%2Fapi%2Fauth%2Foauth%2Fgithub%2Flogin%2Fcallback%2F" in location
    status, location = out["google"]
    assert status == 302
    assert location.startswith("https://accounts.google.com/")
    assert "client_id=fake-g-id" in location
    assert out["callback_route"] != 404


def test_the_provider_redirect_is_a_csrf_protected_post(
    subprocess_env: EnvBuilder,
) -> None:
    out = _probe(
        subprocess_env(
            DJANGO_SETTINGS_MODULE="uadas_api.settings.test",
            GITHUB_CLIENT_ID="fake-gh-id",
            GITHUB_CLIENT_SECRET="fake-gh-secret",  # nosec B106
        )
    )
    assert out["github"][0] == 302  # with the token: works
    assert out["github_without_csrf"] == 403  # without: refused


def test_the_post_login_redirect_cannot_be_pointed_at_another_host(
    subprocess_env: EnvBuilder,
) -> None:
    out = _probe(
        subprocess_env(
            DJANGO_SETTINGS_MODULE="uadas_api.settings.test",
            GITHUB_CLIENT_ID="fake-gh-id",
            GITHUB_CLIENT_SECRET="fake-gh-secret",  # nosec B106
        )
    )
    # Positive twin: a same-host callback ("/done", used by the first test) reaches GitHub.
    assert out["github"][1].startswith("https://github.com/login/oauth/authorize?")
    # A callback on another host (open redirect) never starts the flow: allauth bounces
    # to the SPA's own error page, which is built from settings, not from the request.
    for key in ("evil_callback", "scheme_relative_callback"):
        status, location = out[key]
        assert status == 302, key
        assert location.startswith(
            "http://localhost:5173/account/provider/callback"
        ), key
        assert "evil.example" not in location, key


def test_without_credentials_no_provider_exists_or_is_routable(
    subprocess_env: EnvBuilder,
) -> None:
    out = _probe(subprocess_env(DJANGO_SETTINGS_MODULE="uadas_api.settings.test"))
    assert out["providers"] == []
    for provider in ("github", "google"):
        # An unknown provider is bounced to the SPA's error page, never to a provider.
        status, location = out[provider]
        assert status == 302, provider
        assert location.startswith("http://localhost:5173/account/provider/callback")
        assert "error=" in location
        assert "github.com" not in location and "google.com" not in location
    assert out["callback_route"] == 404
