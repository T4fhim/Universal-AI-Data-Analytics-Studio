# File: src/ui/controllers/theme_controller.py
"""Owns the settings dialog, theme toggle, and about dialog handlers.

Split out of ``main_window.py`` in milestone 26 -- not because these handlers are new (they
predate this milestone unchanged, moved verbatim, the same "same logic, new home" reasoning
milestone 19's own controller extraction used for every other handler that used to live
directly on ``MainWindow``), but because milestone 26's own new wiring
(:class:`~src.ui.controllers.guidance_controller.GuidanceController`'s construction and three
call sites) pushed ``main_window.py`` over ``tests.ui.test_module_size``'s 400-line budget with
zero headroom to spare (the file sat at exactly 400 non-docstring lines as of milestone 25).
This is the smallest, most self-contained group of existing handlers available to extract --
none of the three methods here touch ``Workbench``, any other controller, or ``__init__``-only
state, unlike ``MainWindow.attach_theme_manager`` (which stays on ``MainWindow`` itself: it is
called externally by :mod:`src.core.app`, and mutates ``self._icon_provider``/
``self._dock_manager`` state that only ``MainWindow`` holds).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QWidget

from src.plugins.plugin_manager import PluginManager
from src.services.settings_service import SettingsService
from src.ui.dialogs.about_dialog import AboutDialog
from src.ui.dialogs.settings_dialog import SettingsDialog

if TYPE_CHECKING:
    from src.ui.theme_manager import ThemeManager


class ThemeController:
    """Handles Settings/Toggle Theme/About -- unchanged logic, just no longer inline on MainWindow.

    Args:
        parent: The window dialogs are parented to, and whose ``property("theme_manager")``
            this reads -- kept as a plain ``QWidget`` reference (not the live
            :class:`~src.ui.theme_manager.ThemeManager` itself) for the exact reason
            ``MainWindow.attach_theme_manager``'s own docstring gives: the manager does not
            exist yet when this controller is constructed, and ``QWidget.setProperty`` is
            already the established "has it been attached yet" check.
        settings_service: Where the ``theme`` setting is read from and written to.
        plugin_manager: Passed straight through to :class:`~src.ui.dialogs.settings_dialog.
            SettingsDialog`, unchanged from the pre-milestone-26 call site.
    """

    def __init__(
        self,
        parent: QWidget,
        settings_service: SettingsService,
        plugin_manager: PluginManager,
    ) -> None:
        self._parent = parent
        self._settings_service = settings_service
        self._plugin_manager = plugin_manager

    def open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings_service, self._parent, plugin_manager=self._plugin_manager
        )
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self.apply_theme_from_settings()

    def toggle_theme(self) -> None:
        current = self._settings_service.get("theme", default="dark")
        new_theme = "light" if current == "dark" else "dark"
        self._settings_service.set("theme", value=new_theme)
        self._settings_service.save()
        self.apply_theme_from_settings()

    def apply_theme_from_settings(self) -> None:
        theme_manager: ThemeManager = self._parent.property("theme_manager")
        if theme_manager is None:
            return  # not yet attached -- see MainWindow.attach_theme_manager's own docstring
        theme_name = self._settings_service.get("theme", default="dark")
        theme_manager.apply_theme(theme_name)

    def open_about(self) -> None:
        AboutDialog(self._parent).exec()
