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

from uadas_api.sandbox import limits as _sandbox_limits

API_ROOT = Path(__file__).resolve().parents[1]

# The real platform check, captured at import so `load_settings` can tell whether a test has
# replaced it (see the comment in `load`).
_REAL_LIMITS_ENFORCEABLE = _sandbox_limits.limits_enforceable

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
    "STORAGE_BUCKET",
    "STORAGE_ENDPOINT_URL",
    "STORAGE_ACCESS_KEY_ID",
    "STORAGE_SECRET_ACCESS_KEY",
    "STORAGE_REGION",
    "STORAGE_ADDRESSING",
    "STORAGE_SSE",
    "STORAGE_PRESIGN_SECONDS",
    "STORAGE_MAX_OBJECT_BYTES",
    "STORAGE_GC_GRACE_SECONDS",
    "STORAGE_ENCRYPTION_ACKNOWLEDGED",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    # 3.5: the job queue and the parser sandbox.
    "CELERY_BROKER_URL",
    "JOBS_EAGER",
    "JOBS_QUEUE",
    "JOBS_MAX_ATTEMPTS",
    "JOBS_STALE_AFTER_SECONDS",
    "JOBS_SOFT_TIME_LIMIT_SECONDS",
    "JOBS_TIME_LIMIT_SECONDS",
    "JOBS_VISIBILITY_TIMEOUT_SECONDS",
    "JOBS_RETRY_BACKOFF_BASE_SECONDS",
    "JOBS_RETRY_BACKOFF_MAX_SECONDS",
    "JOBS_REQUEUE_AFTER_SECONDS",
    "JOBS_PROGRESS_INTERVAL_MS",
    "SANDBOX_WALL_SECONDS",
    "SANDBOX_CPU_SECONDS",
    "SANDBOX_MEMORY_MB",
    "SANDBOX_MAX_INPUT_MB",
    "SANDBOX_MAX_OUTPUT_MB",
    "SANDBOX_MAX_ROWS",
    "SANDBOX_MAX_COLUMNS",
    "SANDBOX_PROCESS_HEADROOM",
    "SANDBOX_MAX_ARCHIVE_ENTRIES",
    "SANDBOX_MAX_DECOMPRESSED_MB",
    "SANDBOX_MAX_COMPRESSION_RATIO",
    "SANDBOX_TMP_ROOT",
    "SANDBOX_CHILD_UID",
    "SANDBOX_CHILD_GID",
    "SANDBOX_NETWORK_ISOLATION",
    "SANDBOX_ISOLATION_ACKNOWLEDGED",
    # 3.7: the AI assistant's provider.
    "ASSISTANT_PROVIDER",
    "ASSISTANT_API_KEY",
    "ASSISTANT_MODEL",
    # 3.8: per-tenant quotas.
    "QUOTA_MAX_ROWS",
    "QUOTA_MAX_STORAGE_MB",
    "QUOTA_MAX_JOB_MINUTES",
    "QUOTA_MAX_LLM_TOKENS",
    "QUOTA_UNLIMITED_ACKNOWLEDGED",
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
        # `prod` refuses to start where the sandbox cannot enforce its limits (anywhere but
        # Linux). The tests of *other* production settings must still run on a laptop, so
        # unless a test has already chosen the platform answer itself, pretend it is Linux.
        from uadas_api.sandbox import limits as sandbox_limits

        if sandbox_limits.limits_enforceable is _REAL_LIMITS_ENFORCEABLE:
            monkeypatch.setattr(
                sandbox_limits, "limits_enforceable", lambda *a, **k: True
            )
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


@pytest.fixture(autouse=True)
def _fresh_object_store() -> Iterator[None]:
    """Give every test an empty in-memory object store (``test`` settings select it).

    The store is a process-wide singleton (like the real client), so without this one
    test's objects -- or an injected fault -- would be visible to the next.
    """
    from uadas_api.storage.store import reset_backend

    reset_backend()
    yield
    reset_backend()


@pytest.fixture
def subprocess_env() -> Callable[..., dict[str, str]]:
    """Return ``build(**env)``: ``os.environ`` minus settings variables, plus ``env``."""

    def build(**env: str) -> dict[str, str]:
        base = {k: v for k, v in os.environ.items() if k not in SETTINGS_ENV_VARS}
        base.update(env)
        return base

    return build
