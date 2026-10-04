# File: apps/api/uadas_api/wsgi.py
"""WSGI entry point for synchronous servers (gunicorn, uWSGI).

Why it defaults to the *prod* settings: a container that forgot to choose a settings
module should fail closed (``prod`` refuses to import without its secret and hosts),
not start in debug mode. ``manage.py`` is the entry point that defaults to ``dev``.
"""

from __future__ import annotations

import os

from django.core.handlers.wsgi import WSGIHandler
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "uadas_api.settings.prod")

application: WSGIHandler = get_wsgi_application()
