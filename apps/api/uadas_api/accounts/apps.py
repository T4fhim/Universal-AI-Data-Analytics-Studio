# File: apps/api/uadas_api/accounts/apps.py
"""AppConfig for ``uadas_api.accounts``.

Why an explicit ``name``/``label``: the label is a long-lived identifier (it ends up in
migration dependencies and ``AUTH_USER_MODEL``), so it is spelled out rather than left
to Django's inference.
"""

from __future__ import annotations

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    """Users and authentication."""

    name = "uadas_api.accounts"
    label = "accounts"
    default_auto_field = "django.db.models.BigAutoField"
