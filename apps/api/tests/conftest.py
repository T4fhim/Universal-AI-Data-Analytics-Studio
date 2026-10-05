# File: apps/api/tests/conftest.py
"""Shared fixtures for the ``uadas_api`` test suite.

Why this exists: the settings modules read their configuration from environment
variables at import time (12-factor), so testing them means importing them again under
a controlled environment. :func:`load_settings` does that without leaking the result
into other tests, and :func:`subprocess_env` builds a scrubbed environment for the
tests that must run ``manage.py`` or ``python -c`` in a real child process (where
nothing the parent imported can hide a problem).
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType

import pytest

API_ROOT = Path(__file__).resolve().parents[1]

# Every variable the settings modules read. Cleared before each settings load so a
# developer's (or CI's) own shell environment can never decide a test's outcome.
SETTINGS_ENV_VARS: tuple[str, ...] = (
    "DJANGO_SETTINGS_MODULE",
    "DJANGO_SECRET_KEY",
    "DJANGO_DEBUG",
    "DJANGO_ALLOWED_HOSTS",
    "DATABASE_URL",
    "CORS_ALLOWED_ORIGINS",
    "CSRF_TRUSTED_ORIGINS",
    "DJANGO_SECURE_SSL_REDIRECT",
    "DJANGO_SECURE_HSTS_SECONDS",
    "DJANGO_SECURE_PROXY_SSL_HEADER",
    "DJANGO_TRUSTED_PROXY_COUNT",
    "REDIS_URL",
    "FRONTEND_BASE_URL",
    "DEFAULT_FROM_EMAIL",
    "EMAIL_HOST",
    "EMAIL_PORT",
    "EMAIL_HOST_USER",
    "EMAIL_HOST_PASSWORD",
    "EMAIL_USE_TLS",
    "GITHUB_CLIENT_ID",
    "GITHUB_CLIENT_SECRET",
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "UADAS_CORE_LOG_LEVEL",
)

_SETTINGS_PACKAGE = "uadas_api.settings"


def _purge_settings_modules() -> None:
    for name in [m for m in sys.modules if m.startswith(f"{_SETTINGS_PACKAGE}.")]:
        del sys.modules[name]


@pytest.fixture
def load_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[Callable[..., ModuleType]]:
    """Return ``load(name, **env)``: import ``uadas_api.settings.<name>`` afresh.

    The environment is scrubbed of every settings variable first, then ``env`` is
    applied. The freshly imported module is dropped again on teardown so the next
    test (and the live Django settings object, which keeps its own values) is
    unaffected.
    """
    import importlib

    def load(name: str, **env: str) -> ModuleType:
        for var in SETTINGS_ENV_VARS:
            monkeypatch.delenv(var, raising=False)
        for var, value in env.items():
            monkeypatch.setenv(var, value)
        _purge_settings_modules()
        return importlib.import_module(f"{_SETTINGS_PACKAGE}.{name}")

    yield load
    _purge_settings_modules()


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    """Empty the default cache around every test.

    allauth's rate limits (and anything else cached) live in the process-wide locmem
    cache, so a test that burns through the login limit would otherwise make a later
    test's perfectly legitimate login answer 429.
    """
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def subprocess_env() -> Callable[..., dict[str, str]]:
    """Return ``build(**env)``: ``os.environ`` minus settings variables, plus ``env``."""

    def build(**env: str) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_VARS}
        base.update(env)
        return base

    return build
