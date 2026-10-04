# File: apps/api/uadas_api/ai/apps.py
"""AppConfig for ``uadas_api.ai``.

Why an explicit ``name``/``label``: see ``uadas_api.accounts.apps``.
"""

from __future__ import annotations

from django.apps import AppConfig


class AiConfig(AppConfig):
    """AI assistant."""

    name = "uadas_api.ai"
    label = "ai"
    default_auto_field = "django.db.models.BigAutoField"
