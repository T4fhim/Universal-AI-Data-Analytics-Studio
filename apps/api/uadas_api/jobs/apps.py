# File: apps/api/uadas_api/jobs/apps.py
"""AppConfig for ``uadas_api.jobs``.

Why an explicit ``label``: it appears in migration dependencies and the table name, so it is
spelled out rather than inferred (same rule as the other apps).
"""

from __future__ import annotations

from django.apps import AppConfig


class JobsConfig(AppConfig):
    """Background jobs: the ``Job`` table, its services and the queue facade."""

    name = "uadas_api.jobs"
    label = "jobs"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Register the system checks (imported for their side effect, like the other apps'
        # signal modules). No Celery import here: the app must load without a broker.
        from uadas_api.jobs import checks  # noqa: F401
