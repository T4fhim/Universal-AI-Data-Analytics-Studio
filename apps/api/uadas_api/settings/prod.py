# File: apps/api/uadas_api/settings/prod.py
"""Production settings: refuse to start unconfigured, never debug, secure transport.

Why: a mis-configured production process must fail loudly at start-up, not run with a
guessable key, an open host list, a per-process rate-limit cache or no way to send the
verification mail that sign-up now depends on. Importing this module raises
``ImproperlyConfigured`` unless ``DJANGO_SECRET_KEY``, ``DJANGO_ALLOWED_HOSTS``,
``DATABASE_URL``, ``REDIS_URL``, ``DEFAULT_FROM_EMAIL``, ``EMAIL_HOST`` and
``FRONTEND_BASE_URL`` are set and sane. ``DEBUG`` is hard-wired off (``DJANGO_DEBUG`` is
ignored here on purpose -- an env var must not be able to turn tracebacks and settings
dumps on in production), and email verification is hard-wired ``mandatory`` for the same
reason. Cookie, HSTS and redirect hardening is on by default; the knobs that depend on
the deployment topology are env-configurable:

* ``DJANGO_SECURE_SSL_REDIRECT`` (default true) -- set false when TLS terminates at a
  proxy that already redirects.
* ``DJANGO_SECURE_HSTS_SECONDS`` (default one year).
* ``DJANGO_SECURE_PROXY_SSL_HEADER`` (default false) -- opt in only behind a proxy that
  sets ``X-Forwarded-Proto`` and strips it from client requests; trusting it blindly
  lets a client claim a request was HTTPS.
* ``DJANGO_TRUSTED_PROXY_COUNT`` (default 0) -- how many proxies you control in front of
  the app. allauth's per-IP rate limits key on the client address: with 0 behind a proxy
  every client shares the proxy's address (one noisy client locks everyone out), and a
  value larger than the truth lets a client spoof ``X-Forwarded-For`` past the limit.
* ``EMAIL_PORT`` (587), ``EMAIL_USE_TLS`` (true), ``EMAIL_HOST_USER`` and
  ``EMAIL_HOST_PASSWORD`` (no default: unset means an unauthenticated relay).
"""

from __future__ import annotations

from email.utils import parseaddr

from django.core.exceptions import ImproperlyConfigured, ValidationError
from django.core.validators import validate_email

from ._env import get_bool, get_int, get_str
from .base import *  # noqa: F403 - the settings split is a star-import by design
from .base import ALLOWED_HOSTS, DATABASES, FRONTEND_BASE_URL, SECRET_KEY

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
if not get_str("REDIS_URL"):
    raise ImproperlyConfigured(
        "REDIS_URL must be set for production: allauth's rate limits count attempts "
        "in the shared cache, and a per-process cache would multiply every limit by "
        "the number of workers."
    )
if not FRONTEND_BASE_URL:
    raise ImproperlyConfigured(
        "FRONTEND_BASE_URL must be set for production (the SPA's address; verification "
        "and password-reset emails link to it)."
    )
if not FRONTEND_BASE_URL.lower().startswith("https://"):
    raise ImproperlyConfigured(
        "FRONTEND_BASE_URL must be an https:// URL in production: it carries the "
        "single-use verification and password-reset links."
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

# allauth reads this name (without a DJANGO_ prefix); see the module docstring.
ALLAUTH_TRUSTED_PROXY_COUNT = get_int("DJANGO_TRUSTED_PROXY_COUNT", 0)
if ALLAUTH_TRUSTED_PROXY_COUNT < 0:
    raise ImproperlyConfigured("DJANGO_TRUSTED_PROXY_COUNT must not be negative.")

# Sign-up cannot complete without mail, so the relay is mandatory and the account's
# email address must be proven before it can be used to log in. Fixed here, not read
# from the environment (see the module docstring).
ACCOUNT_EMAIL_VERIFICATION = "mandatory"

EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
DEFAULT_FROM_EMAIL = get_str("DEFAULT_FROM_EMAIL")
EMAIL_HOST = get_str("EMAIL_HOST")
if not DEFAULT_FROM_EMAIL:
    raise ImproperlyConfigured("DEFAULT_FROM_EMAIL must be set for production.")
try:
    validate_email(parseaddr(DEFAULT_FROM_EMAIL)[1])
except ValidationError:
    raise ImproperlyConfigured(
        "DEFAULT_FROM_EMAIL must be an address such as 'UADAS <no-reply@example.com>'."
    ) from None
if not EMAIL_HOST:
    raise ImproperlyConfigured(
        "EMAIL_HOST must be set for production (the SMTP relay)."
    )
SERVER_EMAIL = DEFAULT_FROM_EMAIL
EMAIL_PORT = get_int("EMAIL_PORT", 587)
EMAIL_USE_TLS = get_bool("EMAIL_USE_TLS", default=True)
# Credentials come only from the environment and have no default: unset means the relay
# is used without authentication, never a baked-in value.
EMAIL_HOST_USER = get_str("EMAIL_HOST_USER")
EMAIL_HOST_PASSWORD = get_str("EMAIL_HOST_PASSWORD")
