# File: apps/api/tests/test_apps.py
"""The five (empty) Django apps are registered with the labels later phases rely on.

Why: Phase 3.2+ attach models, migrations and ``AUTH_USER_MODEL`` to these apps by
label. A wrong ``AppConfig.name`` / ``label`` now would force a migration-breaking
rename later, so the contract is pinned while the apps are still empty.
"""

from __future__ import annotations

import importlib

import pytest
from django.apps import apps

APP_LABELS = ("accounts", "workspaces", "pipeline", "ai", "exports")


@pytest.mark.parametrize("label", APP_LABELS)
def test_app_is_registered_with_expected_name_and_label(label: str) -> None:
    config = apps.get_app_config(label)
    assert config.name == f"uadas_api.{label}"
    assert config.label == label
    assert config.default_auto_field == "django.db.models.BigAutoField"


@pytest.mark.parametrize("label", APP_LABELS)
def test_app_has_a_migrations_package(label: str) -> None:
    module = importlib.import_module(f"uadas_api.{label}.migrations")
    assert module.__file__ is not None


def test_no_unexpected_local_apps_are_registered() -> None:
    local = sorted(
        c.label for c in apps.get_app_configs() if c.name.startswith("uadas_api.")
    )
    assert local == sorted(APP_LABELS)
