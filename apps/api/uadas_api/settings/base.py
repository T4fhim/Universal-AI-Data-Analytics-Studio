# File: apps/api/uadas_api/settings/base.py
"""Settings shared by every environment -- 12-factor, and secure by omission.

Why: everything environment-specific comes from environment variables
(``DJANGO_SECRET_KEY``, ``DJANGO_DEBUG``, ``DJANGO_ALLOWED_HOSTS``, ``DATABASE_URL``,
``CORS_ALLOWED_ORIGINS``, ``CSRF_TRUSTED_ORIGINS``, ``REDIS_URL``, the OAuth client
credentials ...), and this module supplies **no insecure default for any of them**: the
secret key is empty (Django refuses to start on an empty ``SECRET_KEY``), ``DEBUG`` is
off, no hosts or origins are allowed, no database is configured, and no OAuth provider
exists unless its credentials do. ``dev`` and ``test`` opt in to conveniences
explicitly; ``prod`` additionally refuses to load without the values it needs.

Authentication (3.3) is django-allauth in *headless* mode, browser client only: a SPA
talks JSON to ``/api/auth/browser/v1/...`` and the session lives in an HttpOnly cookie
(no tokens exist to steal). Email is the only login name. Verification mode, the cache
behind the rate limits and the mail backend are decided per environment (``dev`` /
``test`` / ``prod``); the invariants that must hold everywhere are set here.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import dj_database_url

from . import _auth
from ._env import get_bool, get_choice, get_list, get_str

# apps/api/ -- the directory holding manage.py. Anchored on this file, never on the
# current working directory (same rule as uadas_core's PROJECT_ROOT).
BASE_DIR: Path = Path(__file__).resolve().parents[2]

SECRET_KEY: str = get_str("DJANGO_SECRET_KEY")
DEBUG: bool = get_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = get_list("DJANGO_ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS: list[str] = get_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS: list[str] = get_list("CSRF_TRUSTED_ORIGINS")
# The SPA's session cookie must accompany its cross-origin fetches. This is safe only
# because CORS_ALLOW_ALL_ORIGINS stays off and the origin list defaults to empty: a
# credentialed response is only ever granted to an origin the operator listed.
CORS_ALLOW_CREDENTIALS: bool = True

# The custom user model (email login, UUID primary key). Django cannot swap the user
# model once migrations that reference ``auth.User`` exist without a painful manual
# rewrite, so this was set in the same change (3.2) that created the first migrations,
# not after. Never remove or repoint it once those migrations are applied anywhere.
AUTH_USER_MODEL: str = "accounts.User"

# OAuth providers exist only when their credentials do (see _auth.social_providers).
SOCIALACCOUNT_PROVIDERS: dict[str, dict[str, Any]] = _auth.social_providers(os.environ)

INSTALLED_APPS: list[str] = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    # Needed so Django Ninja's interactive docs template can be found (dev only --
    # see api.py); harmless otherwise.
    "ninja",
    "corsheaders",
    # Authentication: allauth, headless (JSON) only. `allauth.socialaccount` is always
    # installed (it is cheap and keeps the schema stable); a provider app is added
    # only when that provider has credentials.
    "allauth",
    "allauth.account",
    "allauth.headless",
    "allauth.socialaccount",
    *_auth.social_provider_apps(SOCIALACCOUNT_PROVIDERS),
    # Local apps (models since 3.2; `ai` has none yet).
    "uadas_api.accounts",
    "uadas_api.workspaces",
    "uadas_api.pipeline",
    "uadas_api.ai",
    "uadas_api.exports",
]

MIDDLEWARE: list[str] = [
    "django.middleware.security.SecurityMiddleware",
    # CorsMiddleware must sit above anything that can generate a response (Common).
    "corsheaders.middleware.CorsMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    # allauth requires this, after AuthenticationMiddleware.
    "allauth.account.middleware.AccountMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF: str = "uadas_api.urls"
WSGI_APPLICATION: str = "uadas_api.wsgi.application"
ASGI_APPLICATION: str = "uadas_api.asgi.application"

TEMPLATES: list[dict[str, object]] = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    }
]

# Parsed from DATABASE_URL. Unset yields no databases (Django substitutes its dummy
# backend), so a process that forgot to configure one fails on first use instead of
# silently writing to a local SQLite file. `dev` and `test` supply their own defaults.
# (Guarded rather than calling config() unconditionally: that logs a root-logger
# warning on every import when the variable is unset.)
DATABASES: dict[str, Any] = (
    {"default": dj_database_url.config(conn_max_age=600, conn_health_checks=True)}
    if get_str("DATABASE_URL")
    else {}
)

# Redis when REDIS_URL is set, else a per-process cache (dev/test only: prod requires
# REDIS_URL, because allauth's rate-limit counters live here and must be shared).
CACHES: dict[str, dict[str, Any]] = _auth.cache_settings(os.environ)

DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

LANGUAGE_CODE: str = "en-us"
TIME_ZONE: str = "UTC"
USE_I18N: bool = True
USE_TZ: bool = True

# --- sessions, CSRF, passwords ------------------------------------------------------

# ModelBackend first: it looks the user up with ``UserManager.get_by_natural_key`` (NFKC
# normalisation + the ``LOWER(email)`` rule the unique constraint uses), so every spelling
# of an address the database treats as one account can log in. allauth's own backend
# (EmailAddress-aware lookup) follows. The failed-login rate limit does not live in a
# backend -- allauth applies it in ``adapter.authenticate`` before any backend runs -- so
# listing both does not weaken it.
AUTHENTICATION_BACKENDS: list[str] = [
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

AUTH_PASSWORD_VALIDATORS: list[dict[str, Any]] = [
    {
        "NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"
    },
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 12},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

SESSION_COOKIE_HTTPONLY: bool = True
SESSION_COOKIE_SAMESITE: str = "Lax"
SESSION_COOKIE_AGE: int = 60 * 60 * 24 * 7
CSRF_COOKIE_SAMESITE: str = "Lax"
# The SPA reads the CSRF cookie and echoes it in `X-CSRFToken`, so this cookie cannot be
# HttpOnly. It is not a secret on its own (an attacker needs the *matching* header from
# a page of the right origin); the session cookie, which is, stays HttpOnly.
CSRF_COOKIE_HTTPONLY: bool = False

# --- allauth (headless, browser client, email login) -------------------------------

HEADLESS_ONLY: bool = True
# "browser" only: session cookies + CSRF. The "app" client (bearer session tokens) is
# not exposed, so there is no token to leak or to forget to revoke.
HEADLESS_CLIENTS: tuple[str, ...] = ("browser",)

ACCOUNT_ADAPTER: str = "uadas_api.accounts.adapters.AccountAdapter"
SOCIALACCOUNT_ADAPTER: str = "uadas_api.accounts.adapters.SocialAccountAdapter"

ACCOUNT_LOGIN_METHODS: set[str] = {"email"}
ACCOUNT_SIGNUP_FIELDS: list[str] = ["email*", "password1*"]
ACCOUNT_USER_MODEL_USERNAME_FIELD: str | None = None  # the user has no username
# ACCOUNT_PREVENT_ENUMERATION is deliberately NOT set: its default (True) is the
# behaviour wanted, and tests/test_auth_settings.py fails if anyone turns it off.

# Per-IP limits stop a single client; the "/key" limits (per target email) stop a
# distributed guesser. Counters live in CACHES["default"].
# (Built from pairs, not a dict literal: bandit's B105 mistakes the action name
# "reset_password" used as a dict key for a hardcoded password, and suppressing that with
# an inline marker makes bandit warn about the marker on the neighbouring lines.)
ACCOUNT_RATE_LIMITS: dict[str, str] = dict(
    [
        ("login", "20/m/ip"),
        ("login_failed", "10/m/ip,5/5m/key"),
        ("signup", "10/m/ip"),
        ("reset_password", "10/m/ip,3/m/key"),
    ]
)

# No provider tokens are stored (nothing in the product calls a provider API), and a
# provider-asserted email never silently attaches to an existing local account.
SOCIALACCOUNT_STORE_TOKENS: bool = False
SOCIALACCOUNT_EMAIL_AUTHENTICATION: bool = False

# Where the SPA lives: the links in verification / password-reset emails point there.
# `dev` / `test` supply a default; `prod` requires it.
FRONTEND_BASE_URL: str = get_str("FRONTEND_BASE_URL")
HEADLESS_FRONTEND_URLS: dict[str, str] = (
    _auth.frontend_urls(FRONTEND_BASE_URL) if FRONTEND_BASE_URL else {}
)

# The framework-free core's log level (core session seam). The core runs in *server
# mode* here (see uadas_api/core_bridge.py): it logs to stderr only, reads and writes no
# YAML, loads no plugins -- so the only core setting the API needs is this one, and it
# comes from the environment like everything else in this module.
UADAS_CORE_LOG_LEVEL: str = get_choice(
    "UADAS_CORE_LOG_LEVEL",
    ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
    default="INFO",
)
