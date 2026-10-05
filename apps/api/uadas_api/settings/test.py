# File: apps/api/uadas_api/settings/test.py
"""Test settings: hermetic secret, fast password hashing, in-memory SQLite.

Why: the suite must run anywhere with nothing configured, and quickly. The secret key
is a fixed throwaway (never read from the environment, so a developer's real key can
not leak into test output) and the MD5 hasher keeps ``create_user`` from dominating
test time from 3.3 on. The database is in-memory SQLite *unless* ``DATABASE_URL`` is
set -- CI's ``api-test`` job points it at its Postgres 17 service container so the same
tests exercise the production engine. pytest-django always creates a separate
``test_``-prefixed database, so a stray ``DATABASE_URL`` never touches real data.

Auth: email verification is off (``none``) so most tests can sign up and log straight in;
the tests of the verification flow switch it to ``mandatory`` with the ``settings``
fixture. Mail goes to the in-memory outbox, and the cache is always the per-process
default (a developer's ``REDIS_URL`` must not make a test run touch a real server).
"""

from __future__ import annotations

import dj_database_url

from . import _auth
from .base import *  # noqa: F403 - the settings split is a star-import by design

DEBUG = False
SECRET_KEY = "test-only-secret-key-not-used-anywhere-else"  # nosec B105
ALLOWED_HOSTS = ["testserver", "localhost"]

DATABASES = {"default": dj_database_url.config(default="sqlite://:memory:")}

PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]

CACHES = _auth.cache_settings({})
ACCOUNT_EMAIL_VERIFICATION = "none"
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
DEFAULT_FROM_EMAIL = "UADAS test <no-reply@example.test>"

FRONTEND_BASE_URL = "http://localhost:5173"
HEADLESS_FRONTEND_URLS = _auth.frontend_urls(FRONTEND_BASE_URL)
