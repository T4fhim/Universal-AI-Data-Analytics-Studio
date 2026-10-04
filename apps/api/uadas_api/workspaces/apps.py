# File: apps/api/uadas_api/workspaces/apps.py
"""AppConfig for ``uadas_api.workspaces``.

Why an explicit ``name``/``label``: see ``uadas_api.accounts.apps``.
"""

from __future__ import annotations

from django.apps import AppConfig


class WorkspacesConfig(AppConfig):
    """Tenant-scoped workspaces."""

    name = "uadas_api.workspaces"
    label = "workspaces"
    default_auto_field = "django.db.models.BigAutoField"
