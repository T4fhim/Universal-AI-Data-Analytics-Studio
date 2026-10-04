# File: apps/api/uadas_api/settings/prod.py
"""Production settings: refuse to start unconfigured, never debug, secure transport.

Why: a mis-configured production process must fail loudly at start-up, not run with a
guessable key or an open host list. Importing this module raises
``ImproperlyConfigured`` unless ``DJANGO_SECRET_KEY`` and ``DJANGO_ALLOWED_HOSTS`` are
set. ``DEBUG`` is hard-wired off (``DJANGO_DEBUG`` is ignored here on purpose -- an
env var must not be able to turn tracebacks and settings dumps on in production).
Cookie, HSTS and redirect hardening is on by default; the three knobs that depend on
the deployment topology are env-configurable:

* ``DJANGO_SECURE_SSL_REDIRECT`` (default true) -- set false when TLS terminates at a
  proxy that already redirects.
* ``DJANGO_SECURE_HSTS_SECONDS`` (default one year).
* ``DJANGO_SECURE_PROXY_SSL_HEADER`` (default false) -- opt in only behind a proxy that
  sets ``X-Forwarded-Proto`` and strips it from client requests; trusting it blindly
  lets a client claim a request was HTTPS.
"""

from __future__ import annotations

from django.core.exceptions import ImproperlyConfigured

from ._env import get_bool, get_int
from .base import *  # noqa: F403 - the settings split is a star-import by design
from .base import ALLOWED_HOSTS, DATABASES, SECRET_KEY

# Django's own deployment check (W009) wants at least 50 characters; refuse anything
# weaker here, because CI runs `check --deploy` against its own throwaway key, not
# against a real deployment's.
_MIN_SECRET_KEY_LENGTH = 50

if not SECRET_KEY:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set for production.")
if len(SECRET_KEY) < _MIN_SECRET_KEY_LENGTH or SECRET_KEY.startswith(
    "django-insecure-"
):
    raise ImproperlyConfigured(
        f"DJANGO_SECRET_KEY must be a random value of at least {_MIN_SECRET_KEY_LENGTH} "
        "characters and must not be a django-insecure- placeholder."
    )
if not ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must be set for production "
        "(comma-separated host names)."
    )
if "*" in ALLOWED_HOSTS:
    raise ImproperlyConfigured(
        "DJANGO_ALLOWED_HOSTS must list explicit host names in production, not '*'."
    )
if not DATABASES:
    raise ImproperlyConfigured(
        "DATABASE_URL must be set for production (no database is configured)."
    )

DEBUG = False

SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True

SECURE_SSL_REDIRECT = get_bool("DJANGO_SECURE_SSL_REDIRECT", default=True)
SECURE_HSTS_SECONDS = get_int("DJANGO_SECURE_HSTS_SECONDS", 31536000)
if SECURE_HSTS_SECONDS <= 0:
    raise ImproperlyConfigured(
        "DJANGO_SECURE_HSTS_SECONDS must be positive in production."
    )
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_PROXY_SSL_HEADER = (
    ("HTTP_X_FORWARDED_PROTO", "https")
    if get_bool("DJANGO_SECURE_PROXY_SSL_HEADER", default=False)
    else None
)
