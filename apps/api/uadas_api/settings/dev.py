# File: apps/api/uadas_api/settings/dev.py
"""Local-development settings: debug on, an insecure key allowed, SQLite by default.

Why: a fresh clone should reach a running ``manage.py check`` / ``runserver`` with zero
configuration, so this module (and only this one, besides ``test``) relaxes what
``base`` refuses to guess. An explicit ``DJANGO_SECRET_KEY`` or ``DATABASE_URL`` still
wins, so a developer can point at the docker-compose Postgres without editing code.
"""

from __future__ import annotations

import dj_database_url

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
