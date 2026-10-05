# File: apps/api/uadas_api/settings/_auth.py
"""Environment-driven pieces of the authentication settings, as plain functions.

Why a separate module: three decisions in the auth configuration depend on the
environment -- which OAuth providers exist, which cache backs the rate limits, and what
the SPA's address is -- and each is easy to get subtly wrong (a half-configured provider
silently vanishing, a per-process cache quietly defeating a rate limit). Keeping them as
small pure functions of an ``environ`` mapping lets the tests exercise every branch
without a network, a Redis server or a process restart, while ``base`` / ``prod`` just
call them with ``os.environ``.

Nothing here has a default for a secret: a provider is on only when its id AND secret are
both present in the environment.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlsplit

from django.core.exceptions import ImproperlyConfigured

# provider key -> (INSTALLED_APPS entry, id variable, secret variable, provider settings)
_PROVIDERS: dict[str, tuple[str, str, str, dict[str, Any]]] = {
    "github": (
        "allauth.socialaccount.providers.github",
        "GITHUB_CLIENT_ID",
        "GITHUB_CLIENT_SECRET",
        # `user:email` lets allauth read the primary email and, importantly, GitHub's own
        # "verified" flag; VERIFIED_EMAIL is deliberately NOT forced on.
        {"SCOPE": ["user:email"]},
    ),
    "google": (
        "allauth.socialaccount.providers.google",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        {
            "SCOPE": ["profile", "email"],
            "AUTH_PARAMS": {"access_type": "online"},
            "OAUTH_PKCE_ENABLED": True,
        },
    ),
}


def _clean(environ: Mapping[str, str], name: str) -> str:
    return environ.get(name, "").strip()


def social_providers(environ: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """Return allauth's ``SOCIALACCOUNT_PROVIDERS`` for the providers whose credentials exist.

    A provider needs both ``<NAME>_CLIENT_ID`` and ``<NAME>_CLIENT_SECRET``; blank counts as
    unset. Exactly one of the two raises :class:`ImproperlyConfigured`: skipping the
    provider would turn a forgotten secret into a silently missing sign-in button.
    """
    providers: dict[str, dict[str, Any]] = {}
    for key, (_, id_var, secret_var, extra) in _PROVIDERS.items():
        client_id, secret = _clean(environ, id_var), _clean(environ, secret_var)
        if not client_id and not secret:
            continue
        if not client_id or not secret:
            raise ImproperlyConfigured(
                f"{id_var} and {secret_var} must be set together "
                f"(only one of the {key} OAuth credentials is present)."
            )
        providers[key] = {
            **extra,
            "APPS": [{"client_id": client_id, "secret": secret, "key": ""}],
        }
    return providers


def social_provider_apps(providers: Mapping[str, Any]) -> list[str]:
    """The ``INSTALLED_APPS`` entries (one per enabled provider) that go with ``providers``."""
    return [_PROVIDERS[key][0] for key in _PROVIDERS if key in providers]


def cache_settings(environ: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    """``CACHES``: Redis when ``REDIS_URL`` is set, otherwise a per-process cache.

    allauth's rate limits count attempts in the default cache. A per-process cache is
    correct for one dev process but useless behind several workers (each keeps its own
    counter, so the limit is multiplied by the worker count), which is why ``prod`` makes
    ``REDIS_URL`` mandatory.
    """
    url = _clean(environ, "REDIS_URL")
    if url:
        return {
            "default": {
                "BACKEND": "django.core.cache.backends.redis.RedisCache",
                "LOCATION": url,
            }
        }
    return {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "uadas-default",
        }
    }


def frontend_urls(base_url: str) -> dict[str, str]:
    """allauth headless ``HEADLESS_FRONTEND_URLS`` for an SPA served at ``base_url``.

    These are the links placed inside verification and password-reset emails, so they
    must point at the SPA (which then calls the API), not at the API host.
    """
    parts = urlsplit(base_url)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ImproperlyConfigured(
            "FRONTEND_BASE_URL must be an absolute http(s) URL, e.g. https://app.example.com."
        )
    base = base_url.rstrip("/")
    return {
        "account_confirm_email": f"{base}/account/verify-email/{{key}}",
        "account_reset_password": f"{base}/account/password/reset",
        "account_reset_password_from_key": f"{base}/account/password/reset/key/{{key}}",
        "account_signup": f"{base}/account/signup",
        "socialaccount_login_error": f"{base}/account/provider/callback",
    }
