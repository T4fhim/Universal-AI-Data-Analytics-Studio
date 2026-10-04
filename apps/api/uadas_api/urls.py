# File: apps/api/uadas_api/urls.py
"""Root URLconf: Django Ninja is mounted at ``/api/``.

Why nothing else lives here: the backend is an API only (the web UI is a separate
Vite/React app), so the whole URL space is the Ninja API defined in
:mod:`uadas_api.api`.
"""

from __future__ import annotations

from django.urls import path

from .api import api

urlpatterns = [
    path("api/", api.urls),
]
