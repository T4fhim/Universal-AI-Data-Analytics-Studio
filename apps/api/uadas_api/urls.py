# File: apps/api/uadas_api/urls.py
"""Root URLconf: allauth's headless auth under ``/api/auth/``, Django Ninja under ``/api/``.

Why nothing else lives here: the backend is an API only (the web UI is a separate
Vite/React app), so the whole URL space is JSON.

* ``/api/auth/browser/v1/...`` -- allauth headless, browser client (session cookie + CSRF):
  ``config`` (also sets the CSRF cookie the SPA must echo), ``auth/signup``, ``auth/login``,
  ``auth/session`` (GET state / DELETE logout), ``auth/email/verify``,
  ``auth/password/request`` + ``auth/password/reset``, ``auth/provider/redirect`` ...
  The ``app`` (bearer-token) client is disabled in settings, so ``/api/auth/app/...`` is 404.
* ``/api/auth/oauth/<provider>/login/callback/`` -- the provider redirect URIs (the only
  non-JSON-API endpoints allauth needs, even in headless mode). Provider apps are installed
  only when their credentials exist, so with none configured this mounts nothing.
* ``/api/...`` -- everything else, the Ninja API (:mod:`uadas_api.api`). It is listed last:
  Django tries patterns in order and falls through when a Ninja route does not match.
"""

from __future__ import annotations

from django.urls import include, path

from .api import api

urlpatterns = [
    path("api/auth/oauth/", include("allauth.urls")),
    path("api/auth/", include("allauth.headless.urls")),
    path("api/", api.urls),
]
