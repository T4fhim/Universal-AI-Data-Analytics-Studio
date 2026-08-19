# File: tests/ui/dialogs/test_settings_dialog.py
"""Milestone 27: SettingsDialog's plugin list shows a real EmptyState, not the old
"(No plugins found in the configured search paths)" QListWidgetItem placeholder text.

Uses a real SettingsService (backed by a tmp_path config.yaml, the same construction pattern
tests/services/test_database_connection_service.py already uses) and a real PluginManager
pointed at an empty search-path directory, so ``list_plugins()`` returning ``[]`` is genuine
plugin-discovery behavior, not a mocked return value.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from src.core.config import AppConfig, load_config
from src.plugins.plugin_manager import PluginManager
from src.services.settings_service import SettingsService
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.widgets.empty_state import EmptyState


@pytest.fixture()
def settings_service(tmp_path: Path) -> SettingsService:
    config_path = tmp_path / "config.yaml"
    config = AppConfig.from_dict(load_config(config_path))
    return SettingsService(config, config_path)


def test_plugin_list_shows_empty_state_when_no_plugins_are_discovered(
    qapp: QApplication, settings_service: SettingsService, tmp_path: Path
) -> None:
    empty_search_dir = tmp_path / "plugins"
    empty_search_dir.mkdir()
    plugin_manager = PluginManager([str(empty_search_dir)], enabled=True)

    dialog = SettingsDialog(settings_service, plugin_manager=plugin_manager)

    assert plugin_manager.list_plugins() == []
    assert dialog._plugin_list_stack.currentWidget() is dialog._plugin_list_empty_state
    assert isinstance(dialog._plugin_list_empty_state, EmptyState)
    assert dialog._plugin_list_empty_state.accessibleName() == "No Plugins Found"
