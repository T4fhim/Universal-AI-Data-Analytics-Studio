# File: tests/ui/controllers/test_theme_controller.py
"""Tests for ThemeController's theme-manipulation methods (milestone 26 extraction).

Covers ``toggle_theme``/``apply_theme_from_settings`` -- the two methods here that need no
real modal dialog (``open_settings``/``open_about`` construct real ``QDialog`` subclasses and
call ``exec()``, which is untested here for the same reason it was never tested before this
milestone's extraction: this logic moved verbatim out of ``main_window.py``, unchanged, and
had no dedicated test coverage there either -- confirmed by grep before writing this file).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QWidget

from src.core.bootstrap import bootstrap
from src.plugins.plugin_manager import PluginManager
from src.services.settings_service import SettingsService
from src.ui.controllers.theme_controller import ThemeController
from src.ui.theme_manager import ThemeManager


def test_apply_theme_from_settings_is_a_safe_no_op_before_a_theme_manager_is_attached(
    qapp: QApplication, config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    settings_service = context.container.resolve(SettingsService)
    plugin_manager = context.container.resolve(PluginManager)
    controller = ThemeController(QWidget(), settings_service, plugin_manager)

    controller.apply_theme_from_settings()  # must not raise


def test_toggle_theme_flips_between_dark_and_light(
    qapp: QApplication, config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    settings_service = context.container.resolve(SettingsService)
    plugin_manager = context.container.resolve(PluginManager)
    parent = QWidget()
    theme_manager = ThemeManager(qapp)
    theme_manager.apply_theme(settings_service.get("theme", default="dark"))
    parent.setProperty("theme_manager", theme_manager)
    controller = ThemeController(parent, settings_service, plugin_manager)

    starting_theme = settings_service.get("theme", default="dark")
    controller.toggle_theme()

    new_theme = settings_service.get("theme", default="dark")
    assert new_theme != starting_theme
    assert theme_manager.current_theme() == new_theme


def test_apply_theme_from_settings_applies_the_persisted_theme(
    qapp: QApplication, config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    settings_service = context.container.resolve(SettingsService)
    plugin_manager = context.container.resolve(PluginManager)
    parent = QWidget()
    theme_manager = ThemeManager(qapp)
    theme_manager.apply_theme("dark")
    parent.setProperty("theme_manager", theme_manager)
    controller = ThemeController(parent, settings_service, plugin_manager)

    settings_service.set("theme", value="light")
    controller.apply_theme_from_settings()

    assert theme_manager.current_theme() == "light"


def test_apply_theme_from_settings_applies_accessibility_settings(
    qapp: QApplication, config_path: Path, log_dir: Path, reset_logging_state
) -> None:
    """Milestone 28: reduced_motion/base_font_size are pushed into the live
    ThemeManager the same call that applies the theme name does -- see
    ThemeController.apply_theme_from_settings's own comment for why both are
    set before, not after, the apply_theme() call."""
    context = bootstrap(config_path=config_path, log_dir=log_dir)
    settings_service = context.container.resolve(SettingsService)
    plugin_manager = context.container.resolve(PluginManager)
    parent = QWidget()
    theme_manager = ThemeManager(qapp)
    theme_manager.apply_theme("dark")
    parent.setProperty("theme_manager", theme_manager)
    controller = ThemeController(parent, settings_service, plugin_manager)

    settings_service.set("accessibility", "reduced_motion", value=True)
    settings_service.set("accessibility", "base_font_size", value=18)
    controller.apply_theme_from_settings()

    assert theme_manager.reduced_motion() is True
    assert theme_manager.current_tokens().font_size_md == 18
