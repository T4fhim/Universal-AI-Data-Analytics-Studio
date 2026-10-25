# File: apps/api/uadas_api/storage/apps.py
"""AppConfig for ``uadas_api.storage``.

Why an app and not just a package: it owns two tenant-scoped tables (``WorkspaceHead``, the
compare-and-swap pointer of a project's saved workspace, and ``OrphanedObject``, the durable
queue of objects whose deletion is pending). Explicit ``name``/``label``: see
``uadas_api.accounts.apps``. ``ready()`` connects the post-delete signals that queue a
deleted row's objects (``lifecycle``).
"""

from __future__ import annotations

from django.apps import AppConfig


class StorageConfig(AppConfig):
    """Object storage: tenant facade, workspace persistence, row <-> object lifecycle."""

    name = "uadas_api.storage"
    label = "storage"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        from uadas_api.storage import signals  # noqa: F401 - connects the receivers
