# File: apps/api/uadas_api/settings/__init__.py
"""Split settings: ``base`` (shared, no insecure defaults), ``dev``, ``test``, ``prod``.

Why a package and no re-export here: which settings module is active must be an
explicit decision (``DJANGO_SETTINGS_MODULE``), never an import side effect. ``manage.py``
defaults to ``dev`` for convenience; ``wsgi`` / ``asgi`` default to ``prod`` so a
container that forgot to choose fails closed rather than starting in debug mode.
"""

from __future__ import annotations
