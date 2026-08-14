# File: src/ui/dialogs/settings_dialog.py
"""The application's Settings dialog.

:class:`SettingsDialog` is a thin UI layer over
:class:`~src.services.settings_service.SettingsService` — every value
shown here is read from that service at construction time via
:meth:`~src.services.settings_service.SettingsService.get`, and every
change the user makes is written back via
:meth:`~src.services.settings_service.SettingsService.set` immediately
(so the in-memory settings state is always current, matching what the
widgets show), with persistence to disk deferred until the user clicks
Save.

This gives a real, working Save/Cancel distinction, not just a
close button:

* **Save** calls :meth:`~src.services.settings_service.SettingsService.save`,
  writing the in-memory changes (already applied via ``set()`` as the
  user interacted with the dialog) to ``config.yaml``.
* **Cancel** calls :meth:`~src.services.settings_service.SettingsService.reload`,
  discarding whatever the user changed during this dialog session and
  restoring the settings service's in-memory state to whatever is
  currently on disk — which is exactly what "Cancel" should mean.

This milestone exposes only the settings that already exist in
``config.yaml``'s schema (theme, autosave) as editable controls.
AI/plugin/forecast/report settings are present in the config schema
(see :func:`src.core.config._default_config_dict`) but have no UI here
yet, since building controls for them without the features they
configure existing yet would be UI for behavior that doesn't exist.
"""

from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QSpinBox, QWidget)

from src.core.constants import AVAILABLE_THEMES
from src.core.logger import get_logger
from src.services.settings_service import SettingsService

_logger = get_logger(__name__)


class SettingsDialog(QDialog):
    """A modal dialog for editing application settings.

    Args:
        settings_service: The running application's
            :class:`~src.services.settings_service.SettingsService`
            instance — resolved from the dependency container by
            :mod:`src.ui.main_window`, not constructed here, since
            exactly one instance should exist per process (see
            :mod:`src.core.bootstrap`'s reasoning for why these
            services are container-registered).
        parent: Parent widget, typically the main window.
    """

    def __init__(self, settings_service: SettingsService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._settings_service = settings_service
        self.setWindowTitle("Settings")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QFormLayout(self)

        self._theme_combo = QComboBox(self)
        self._theme_combo.addItems(AVAILABLE_THEMES)
        current_theme = self._settings_service.get("theme", default=AVAILABLE_THEMES[0])
        self._theme_combo.setCurrentText(current_theme)
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        layout.addRow("Theme:", self._theme_combo)

        self._autosave_checkbox = QCheckBox(self)
        self._autosave_checkbox.setChecked(
            self._settings_service.get("autosave", "enabled", default=True)
        )
        self._autosave_checkbox.toggled.connect(self._on_autosave_enabled_changed)
        layout.addRow("Enable autosave:", self._autosave_checkbox)

        self._autosave_interval_spinbox = QSpinBox(self)
        self._autosave_interval_spinbox.setRange(1, 120)
        self._autosave_interval_spinbox.setSuffix(" minutes")
        self._autosave_interval_spinbox.setValue(
            self._settings_service.get("autosave", "interval_minutes", default=5)
        )
        self._autosave_interval_spinbox.valueChanged.connect(
            self._on_autosave_interval_changed
        )
        layout.addRow("Autosave interval:", self._autosave_interval_spinbox)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self._on_cancel)
        layout.addRow(button_box)

        _logger.debug("Settings dialog constructed.")

    def _on_theme_changed(self, theme_name: str) -> None:
        self._settings_service.set("theme", value=theme_name)

    def _on_autosave_enabled_changed(self, checked: bool) -> None:
        self._settings_service.set("autosave", "enabled", value=checked)

    def _on_autosave_interval_changed(self, minutes: int) -> None:
        self._settings_service.set("autosave", "interval_minutes", value=minutes)

    def _on_save(self) -> None:
        self._settings_service.save()
        _logger.info("Settings saved from settings dialog.")
        self.accept()

    def _on_cancel(self) -> None:
        self._settings_service.reload()
        _logger.info("Settings dialog cancelled; in-memory changes discarded.")
        self.reject()
