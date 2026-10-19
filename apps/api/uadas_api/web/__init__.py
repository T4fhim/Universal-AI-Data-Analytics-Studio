# File: apps/api/uadas_api/web/__init__.py
"""The HTTP surface of the API (Phase 3.6): routers, schemas, errors, limits.

Not a Django app (no models): it only composes the tenant models of ``workspaces``,
``pipeline``, ``exports`` and ``jobs`` and the core's registries into Django Ninja routers.
Every router here follows the template in :mod:`uadas_api.accounts.api`: the organization is in
the path, the first line of a handler is :func:`uadas_api.web.scope.member`, and every other id is
resolved through ``Model.objects.for_organization(org)`` *and* checked against the path's project.
"""

from __future__ import annotations

from uadas_api.web.runtime import headless_plotting_defaults

# First thing any ``uadas_api.web.*`` import does, so it precedes every import of the core's
# analysis stack (which imports matplotlib): see ``runtime.py``.
headless_plotting_defaults()
