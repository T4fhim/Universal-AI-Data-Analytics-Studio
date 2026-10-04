# File: apps/api/uadas_api/exports/apps.py
"""AppConfig for ``uadas_api.exports``.

Why an explicit ``name``/``label``: see ``uadas_api.accounts.apps``.
"""

from __future__ import annotations

from django.apps import AppConfig


class ExportsConfig(AppConfig):
    """Report / chart / dataset exports."""

    name = "uadas_api.exports"
    label = "exports"
    default_auto_field = "django.db.models.BigAutoField"
