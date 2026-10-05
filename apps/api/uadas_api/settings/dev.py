# File: apps/api/uadas_api/settings/dev.py
"""Local-development settings: debug on, an insecure key allowed, SQLite by default.

Why: a fresh clone should reach a running ``manage.py check`` / ``runserver`` with zero
configuration, so this module (and only this one, besides ``test``) relaxes what
``base`` refuses to guess. An explicit ``DJANGO_SECRET_KEY`` or ``DATABASE_URL`` still
wins, so a developer can point at the docker-compose Postgres without editing code.

Auth conveniences: email verification is ``optional`` (the mail is still produced, but
you can sign in without clicking it), mail goes to the console, the rate-limit cache is
the per-process default unless ``REDIS_URL`` points at the docker-compose Redis, and the
SPA is assumed at the Vite dev server's address.
"""

from __future__ import annotations

import dj_database_url

from . import _auth
from ._env import get_str
from .base import *  # noqa: F403 - the settings split is a star-import by design
from .base import BASE_DIR

DEBUG = True

# Not a secret: the "django-insecure-" prefix makes ``check --deploy`` (W009) reject it
# if it ever reaches production, which is the point.
SECRET_KEY = get_str(
    "DJANGO_SECRET_KEY",
    "django-insecure-dev-only-key-never-use-in-production",
)

DATABASES = {
    "default": dj_database_url.config(
        default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}", conn_max_age=0
    )
}

ACCOUNT_EMAIL_VERIFICATION = "optional"
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
DEFAULT_FROM_EMAIL = "UADAS dev <no-reply@localhost>"

FRONTEND_BASE_URL = get_str("FRONTEND_BASE_URL", "http://localhost:5173")
HEADLESS_FRONTEND_URLS = _auth.frontend_urls(FRONTEND_BASE_URL)
