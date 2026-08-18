# File: tests/ui/dialogs/test_connect_database_dialog.py
"""Tests for ConnectDatabaseDialog's "Delete Profile" button -- milestone 23 acceptance criterion 3.

"delete_profile is reachable from UI -- test that triggering the UI action actually calls
through to the DatabaseConnectionService method with the right id." Uses a real
:class:`~src.services.database_connection_service.DatabaseConnectionService` backed by a real
``tmp_path`` config file (the same construction pattern
``tests/services/test_database_connection_service.py`` already established), not a mock -- so
this proves the button reaches real persistence, not just a stub method.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.config import AppConfig, load_config
from src.database.connection_profile import ConnectionProfile, DatabaseType
from src.services.database_connection_service import DatabaseConnectionService
from src.services.settings_service import SettingsService
from src.ui.dialogs.connect_database_dialog import ConnectDatabaseDialog


@pytest.fixture()
def database_service(tmp_path: Path) -> DatabaseConnectionService:
    config_path = tmp_path / "config.yaml"
    config = AppConfig.from_dict(load_config(config_path))
    settings_service = SettingsService(config, config_path)
    return DatabaseConnectionService(settings_service)


def _saved_profile(tmp_path: Path) -> ConnectionProfile:
    return ConnectionProfile(
        name="deletable",
        db_type=DatabaseType.DUCKDB,
        database=str(tmp_path / "deletable.duckdb"),
    )


def test_delete_profile_button_calls_through_to_the_service_with_the_right_id(
    qapp: QApplication,
    database_service: DatabaseConnectionService,
    tmp_path: Path,
    block_modals,
) -> None:
    profile = _saved_profile(tmp_path)
    database_service.save_profile(profile)
    assert database_service.list_profiles() != []

    dialog = ConnectDatabaseDialog(database_service)
    # Index 0 is "(New profile)"; the just-saved profile is index 1.
    dialog._saved_profile_combo.setCurrentIndex(1)

    dialog._on_delete_profile()

    assert database_service.list_profiles() == []
    assert not block_modals  # no "no profile selected" message was shown


def test_delete_profile_with_none_selected_shows_an_informative_message(
    qapp: QApplication, database_service: DatabaseConnectionService, block_modals
) -> None:
    dialog = ConnectDatabaseDialog(database_service)
    # Index 0, "(New profile)", is selected by default -- currentData() is None.

    dialog._on_delete_profile()

    assert any(call.kind == "information" for call in block_modals)
