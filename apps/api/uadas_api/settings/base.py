# File: apps/api/uadas_api/settings/base.py
"""Settings shared by every environment -- 12-factor, and secure by omission.

Why: everything environment-specific comes from environment variables
(``DJANGO_SECRET_KEY``, ``DJANGO_DEBUG``, ``DJANGO_ALLOWED_HOSTS``, ``DATABASE_URL``,
``CORS_ALLOWED_ORIGINS``, ``CSRF_TRUSTED_ORIGINS``), and this module supplies **no
insecure default for any of them**: the secret key is empty (Django refuses to start
on an empty ``SECRET_KEY``), ``DEBUG`` is off, no hosts or origins are allowed, and no
database is configured. ``dev`` and ``test`` opt in to conveniences explicitly;
``prod`` additionally refuses to load without the values it needs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import dj_database_url

from ._env import get_bool, get_list, get_str

# apps/api/ -- the directory holding manage.py. Anchored on this file, never on the
# current working directory (same rule as uadas_core's PROJECT_ROOT).
BASE_DIR: Path = Path(__file__).resolve().parents[2]

SECRET_KEY: str = get_str("DJANGO_SECRET_KEY")
DEBUG: bool = get_bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS: list[str] = get_list("DJANGO_ALLOWED_HOSTS")

CORS_ALLOWED_ORIGINS: list[str] = get_list("CORS_ALLOWED_ORIGINS")
CSRF_TRUSTED_ORIGINS: list[str] = get_list("CSRF_TRUSTED_ORIGINS")

# The custom user model (email login, UUID primary key). Django cannot swap the user
# model once migrations that reference ``auth.User`` exist without a painful manual
# rewrite, so this was set in the same change (3.2) that created the first migrations,
# not after. Never remove or repoint it once those migrations are applied anywhere.
AUTH_USER_MODEL: str = "accounts.User"

INSTALLED_APPS: list[str] = [
    "django.contrib.contenttypes",
    "django.contrib.auth",
    "django.contrib.sessions",
    # Needed so Django Ninja's interactive docs template can be found (dev only --
    # see api.py); harmless otherwise.
    "ninja",
    "corsheaders",
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

DEFAULT_AUTO_FIELD: str = "django.db.models.BigAutoField"

LANGUAGE_CODE: str = "en-us"
TIME_ZONE: str = "UTC"
USE_I18N: bool = True
USE_TZ: bool = True
