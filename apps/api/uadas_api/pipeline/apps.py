# File: apps/api/uadas_api/pipeline/apps.py
"""AppConfig for ``uadas_api.pipeline``.

Why an explicit ``name``/``label``: see ``uadas_api.accounts.apps``.
"""

from __future__ import annotations

from django.apps import AppConfig


class PipelineConfig(AppConfig):
    """Import / clean / analyse / forecast pipeline."""

    name = "uadas_api.pipeline"
    label = "pipeline"
    default_auto_field = "django.db.models.BigAutoField"
