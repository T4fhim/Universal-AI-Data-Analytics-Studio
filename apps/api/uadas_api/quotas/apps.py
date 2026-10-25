# File: apps/api/uadas_api/quotas/apps.py
"""AppConfig for ``uadas_api.quotas``.

Why an explicit ``label``: it appears in migration dependencies and table names, so it is spelled
out rather than inferred (same rule as the other apps).
"""

from __future__ import annotations

from django.apps import AppConfig


class QuotasConfig(AppConfig):
    """Per-organization quotas: limit overrides, usage counters and the usage ledger."""

    name = "uadas_api.quotas"
    label = "quotas"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self) -> None:
        # Imported for its side effect: the receiver that gives a deleted dataset's rows and
        # bytes back to its organization's standing totals.
        from uadas_api.quotas import signals  # noqa: F401
