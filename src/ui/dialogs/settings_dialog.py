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

Through milestone 6 this dialog exposed only theme/autosave. Milestone
7 adds a second tab covering ``ai.*`` — the first UI surface the AI
layer gets at all (the full chat panel is milestone 10) — since
provider-agnostic config + Groq multi-key rotation are meaningless to
a user with no way to enter provider profiles or API key environment
variable names. Plugin/forecast/report settings still have no UI here
yet, for the same "no controls for features that don't exist yet"
reason the milestone-6 docstring above originally gave for AI too.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from src.core.constants import AVAILABLE_THEMES
from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.plugins.plugin_manager import PluginManager
from src.services.settings_service import SettingsService
from src.ui.widgets.empty_state import EmptyState

_logger = get_logger(__name__)

_PROVIDER_TYPES = ("groq", "anthropic", "gemini", "ollama")


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

    def __init__(
        self,
        settings_service: SettingsService,
        parent: QWidget | None = None,
        plugin_manager: PluginManager | None = None,
    ) -> None:
        super().__init__(parent)
        self._settings_service = settings_service
        self._plugin_manager = plugin_manager
        self.setWindowTitle(self.tr("Settings"))
        self.setModal(True)
        self.setMinimumWidth(420)

        outer_layout = QVBoxLayout(self)

        tabs = QTabWidget(self)
        tabs.addTab(self._build_general_tab(), "General")
        tabs.addTab(self._build_ai_tab(), "AI")
        # Milestone 12: only shown when a PluginManager was actually
        # resolved and handed in — main_window.py always has one
        # available (registered unconditionally in bootstrap.py), but
        # this dialog is also constructed directly in tests without
        # one, and a Plugins tab with nothing behind it would be
        # actively misleading rather than merely empty.
        if self._plugin_manager is not None:
            tabs.addTab(self._build_plugins_tab(), "Plugins")
        outer_layout.addWidget(tabs)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_save)
        button_box.rejected.connect(self._on_cancel)
        outer_layout.addWidget(button_box)

        _logger.debug("Settings dialog constructed.")

    def _build_general_tab(self) -> QWidget:
        tab = QWidget(self)
        layout = QFormLayout(tab)

        self._theme_combo = QComboBox(tab)
        self._theme_combo.addItems(AVAILABLE_THEMES)
        current_theme = self._settings_service.get("theme", default=AVAILABLE_THEMES[0])
        self._theme_combo.setCurrentText(current_theme)
        self._theme_combo.currentTextChanged.connect(self._on_theme_changed)
        layout.addRow("Theme:", self._theme_combo)

        self._autosave_checkbox = QCheckBox(tab)
        self._autosave_checkbox.setChecked(
            self._settings_service.get("autosave", "enabled", default=True)
        )
        self._autosave_checkbox.toggled.connect(self._on_autosave_enabled_changed)
        layout.addRow("Enable autosave:", self._autosave_checkbox)

        self._autosave_interval_spinbox = QSpinBox(tab)
        self._autosave_interval_spinbox.setRange(1, 120)
        self._autosave_interval_spinbox.setSuffix(" minutes")
        self._autosave_interval_spinbox.setValue(
            self._settings_service.get("autosave", "interval_minutes", default=5)
        )
        self._autosave_interval_spinbox.valueChanged.connect(
            self._on_autosave_interval_changed
        )
        layout.addRow("Autosave interval:", self._autosave_interval_spinbox)

        # Milestone 28: reduced-motion and base-font-size are read/applied
        # live by ThemeController.apply_theme_from_settings once this
        # dialog is accepted -- see that method and
        # src/ui/theme_manager.py's set_reduced_motion/set_base_font_size.
        self._reduced_motion_checkbox = QCheckBox(tab)
        self._reduced_motion_checkbox.setChecked(
            self._settings_service.get("accessibility", "reduced_motion", default=False)
        )
        self._reduced_motion_checkbox.toggled.connect(self._on_reduced_motion_changed)
        layout.addRow("Reduce motion:", self._reduced_motion_checkbox)

        self._base_font_size_spinbox = QSpinBox(tab)
        # Floor of 10px matches ThemeTokens.with_base_font_size's own
        # smallest-legible floor minus the -1 sm offset it derives from
        # this value; ceiling of 24px is this application's own
        # ThemeTokens.font_size_lg default doubled, a generous but not
        # unbounded upper end for "text resize to 200%" (WCAG 1.4.4).
        self._base_font_size_spinbox.setRange(10, 24)
        self._base_font_size_spinbox.setSuffix(" px")
        self._base_font_size_spinbox.setValue(
            self._settings_service.get("accessibility", "base_font_size", default=13)
        )
        self._base_font_size_spinbox.valueChanged.connect(
            self._on_base_font_size_changed
        )
        layout.addRow("Base font size:", self._base_font_size_spinbox)

        return tab

    def _build_ai_tab(self) -> QWidget:
        """Provider profiles (milestone 7): add/remove/reorder, rotation toggle.

        Reads/writes ``ai.providers`` as one list value via
        ``SettingsService.get``/``set`` rather than per-field paths —
        the list itself is the unit of change (adding, removing, or
        reordering a profile all replace the whole list), unlike
        ``theme``/``autosave.*`` above, which are genuinely independent
        scalars.
        """
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        form = QFormLayout()
        self._ai_enabled_checkbox = QCheckBox(tab)
        self._ai_enabled_checkbox.setChecked(
            self._settings_service.get("ai", "enabled", default=False)
        )
        self._ai_enabled_checkbox.toggled.connect(
            lambda checked: self._settings_service.set("ai", "enabled", value=checked)
        )
        form.addRow("Enable AI assistant:", self._ai_enabled_checkbox)

        self._rotation_checkbox = QCheckBox(tab)
        self._rotation_checkbox.setChecked(
            self._settings_service.get("ai", "rotation_enabled", default=False)
        )
        self._rotation_checkbox.setToolTip(
            "When enabled, a rate-limited provider automatically fails over "
            "to the next profile in the list below (e.g. several Groq keys)."
        )
        self._rotation_checkbox.toggled.connect(
            lambda checked: self._settings_service.set(
                "ai", "rotation_enabled", value=checked
            )
        )
        form.addRow("Enable key/provider rotation:", self._rotation_checkbox)

        # Milestone 8: drives the AI system prompt's register/depth (see
        # assistant_service._build_system_prompt) — displayed as the
        # enum's readable member names, stored as its lowercase value
        # (ExpertiseLevel subclasses str for exactly this: no manual
        # value<->label conversion needed beyond this cosmetic mapping).
        self._expertise_combo = QComboBox(tab)
        for level in ExpertiseLevel:
            self._expertise_combo.addItem(
                level.name.replace("_", " ").title(), level.value
            )
        current_level = self._settings_service.get(
            "ai", "expertise_level", default=ExpertiseLevel.BEGINNER.value
        )
        index = self._expertise_combo.findData(current_level)
        if index >= 0:
            self._expertise_combo.setCurrentIndex(index)
        self._expertise_combo.currentIndexChanged.connect(
            self._on_expertise_level_changed
        )
        form.addRow("Explain results for:", self._expertise_combo)

        layout.addLayout(form)

        self._provider_list = QListWidget(tab)
        self._provider_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        for profile in self._settings_service.get("ai", "providers", default=[]):
            self._provider_list.addItem(_provider_list_item(profile))
        layout.addWidget(self._provider_list)

        buttons_row = QHBoxLayout()
        add_button = QPushButton("Add…", tab)
        add_button.clicked.connect(self._on_add_provider)
        remove_button = QPushButton("Remove", tab)
        remove_button.clicked.connect(self._on_remove_provider)
        move_up_button = QPushButton("Move Up", tab)
        move_up_button.clicked.connect(lambda: self._on_move_provider(-1))
        move_down_button = QPushButton("Move Down", tab)
        move_down_button.clicked.connect(lambda: self._on_move_provider(1))
        for button in (add_button, remove_button, move_up_button, move_down_button):
            buttons_row.addWidget(button)
        layout.addLayout(buttons_row)

        return tab

    def _build_plugins_tab(self) -> QWidget:
        """List discovered plugins with load status/errors, and let each be enabled/disabled.

        Reads from :attr:`_plugin_manager` (already loaded once during
        :func:`~src.core.bootstrap.bootstrap`) rather than triggering a
        fresh scan itself — opening the Settings dialog should show
        what's actually running, not silently re-discover plugins as a
        side effect of the user looking at a settings panel.
        """
        tab = QWidget(self)
        layout = QVBoxLayout(tab)

        self._plugin_list = QListWidget(tab)
        # Milestone 27: the old "(No plugins found...)" QListWidgetItem placeholder is
        # replaced by a real EmptyState, shown via a QStackedWidget page swap -- see
        # DockManager._build_dataset_explorer_dock's own comment for why an illustrated
        # empty state cannot live inside a single list item.
        self._plugin_list_empty_state = EmptyState(
            heading=self.tr("No Plugins Found"),
            message=self.tr(
                "No plugins were discovered in the configured search paths -- see "
                "Settings > Plugins in the manual for how to add one."
            ),
            illustration="empty-search",
            parent=tab,
        )
        self._plugin_list_stack = QStackedWidget(tab)
        self._plugin_list_stack.addWidget(self._plugin_list)
        self._plugin_list_stack.addWidget(self._plugin_list_empty_state)
        self._refresh_plugin_list()
        layout.addWidget(self._plugin_list_stack)

        buttons_row = QHBoxLayout()
        toggle_button = QPushButton(self.tr("Enable/Disable Selected"), tab)
        toggle_button.clicked.connect(self._on_toggle_plugin)
        buttons_row.addWidget(toggle_button)
        layout.addLayout(buttons_row)

        return tab

    def _refresh_plugin_list(self) -> None:
        self._plugin_list.clear()
        assert self._plugin_manager is not None  # guarded by the caller
        plugins = self._plugin_manager.list_plugins()
        if not plugins:
            self._plugin_list_stack.setCurrentWidget(self._plugin_list_empty_state)
            return
        self._plugin_list_stack.setCurrentWidget(self._plugin_list)
        for loaded in plugins:
            manifest = loaded.manifest
            disabled = self._plugin_manager.is_disabled(manifest.name)
            status = (
                "disabled"
                if disabled
                else ("OK" if loaded.loaded_successfully else "error")
            )
            item = QListWidgetItem(f"{manifest.name} ({manifest.version}) — {status}")
            if loaded.errors:
                item.setToolTip("\n".join(loaded.errors))
            self._plugin_list.addItem(item)

    def _on_toggle_plugin(self) -> None:
        row = self._plugin_list.currentRow()
        assert self._plugin_manager is not None  # guarded: tab only built when set
        plugins = self._plugin_manager.list_plugins()
        if row < 0 or row >= len(plugins):
            QMessageBox.information(
                self, "No Plugin Selected", "Select a plugin first."
            )
            return

        plugin_name = plugins[row].manifest.name
        if self._plugin_manager.is_disabled(plugin_name):
            self._plugin_manager.enable_plugin(plugin_name)
        else:
            self._plugin_manager.disable_plugin(plugin_name)

        disabled_names = [
            p.manifest.name
            for p in self._plugin_manager.list_plugins()
            if self._plugin_manager.is_disabled(p.manifest.name)
        ]
        self._settings_service.set(
            "plugins", "disabled_plugin_names", value=disabled_names
        )
        self._refresh_plugin_list()

    # -- AI tab: provider profile list management --------------------------

    def _current_providers(self) -> list[dict[str, Any]]:
        return list(self._settings_service.get("ai", "providers", default=[]))

    def _write_providers(self, providers: list[dict[str, Any]]) -> None:
        self._settings_service.set("ai", "providers", value=providers)
        self._provider_list.clear()
        for profile in providers:
            self._provider_list.addItem(_provider_list_item(profile))

    def _on_add_provider(self) -> None:
        dialog = _ProviderProfileDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        providers = self._current_providers()
        providers.append(dialog.get_profile())
        self._write_providers(providers)

    def _on_remove_provider(self) -> None:
        row = self._provider_list.currentRow()
        if row < 0:
            QMessageBox.information(
                self, "No Profile Selected", "Select a provider profile to remove."
            )
            return
        providers = self._current_providers()
        del providers[row]
        self._write_providers(providers)

    def _on_move_provider(self, delta: int) -> None:
        row = self._provider_list.currentRow()
        new_row = row + delta
        providers = self._current_providers()
        if row < 0 or not (0 <= new_row < len(providers)):
            return  # nothing selected, or already at the list's edge
        providers[row], providers[new_row] = providers[new_row], providers[row]
        self._write_providers(providers)
        self._provider_list.setCurrentRow(new_row)

    def _on_expertise_level_changed(self, index: int) -> None:
        self._settings_service.set(
            "ai", "expertise_level", value=self._expertise_combo.itemData(index)
        )

    def _on_theme_changed(self, theme_name: str) -> None:
        self._settings_service.set("theme", value=theme_name)

    def _on_autosave_enabled_changed(self, checked: bool) -> None:
        self._settings_service.set("autosave", "enabled", value=checked)

    def _on_autosave_interval_changed(self, minutes: int) -> None:
        self._settings_service.set("autosave", "interval_minutes", value=minutes)

    def _on_reduced_motion_changed(self, checked: bool) -> None:
        self._settings_service.set("accessibility", "reduced_motion", value=checked)

    def _on_base_font_size_changed(self, size: int) -> None:
        self._settings_service.set("accessibility", "base_font_size", value=size)

    def _on_save(self) -> None:
        self._settings_service.save()
        _logger.info("Settings saved from settings dialog.")
        self.accept()

    def _on_cancel(self) -> None:
        self._settings_service.reload()
        _logger.info("Settings dialog cancelled; in-memory changes discarded.")
        self.reject()


def _provider_list_item(profile: dict[str, Any]) -> QListWidgetItem:
    """Build one QListWidgetItem's display text for a provider profile dict.

    Module-level (not a method) since it has no dependency on
    ``SettingsDialog`` state — used by both the initial population loop
    and :meth:`SettingsDialog._write_providers`, and keeping it a plain
    function makes that shared formatting rule visible at a glance
    rather than buried as another private method among the dialog's
    many event handlers.
    """
    model_suffix = f" ({profile['model']})" if profile.get("model") else ""
    return QListWidgetItem(
        f"{profile['name']} — {profile['provider_type']}{model_suffix}"
    )


class _ProviderProfileDialog(QDialog):
    """A small modal form for entering one AI provider profile.

    Private to this module (leading underscore, not exported) —
    :class:`SettingsDialog` is the only intended caller; this exists
    purely to keep :meth:`SettingsDialog._build_ai_tab` from growing a
    second, more complex form inline where the provider list buttons
    already are.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.tr("Add AI Provider Profile"))
        self.setModal(True)

        layout = QFormLayout(self)

        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("e.g. Groq key 1")
        layout.addRow("Name:", self._name_edit)

        self._provider_type_combo = QComboBox(self)
        self._provider_type_combo.addItems(_PROVIDER_TYPES)
        layout.addRow("Provider:", self._provider_type_combo)

        self._api_key_env_var_edit = QLineEdit(self)
        self._api_key_env_var_edit.setPlaceholderText(
            "e.g. GROQ_API_KEY_1 (not needed for ollama)"
        )
        layout.addRow("API key env var:", self._api_key_env_var_edit)

        self._model_edit = QLineEdit(self)
        self._model_edit.setPlaceholderText("Leave blank for provider default")
        layout.addRow("Model override:", self._model_edit)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

    def _on_accept(self) -> None:
        if not self._name_edit.text().strip():
            QMessageBox.warning(
                self, "Name Required", "Give this provider profile a name."
            )
            return
        self.accept()

    def get_profile(self) -> dict[str, Any]:
        """Return the entered profile as an ``ai.providers`` list entry.

        Only valid to call after :meth:`exec` returned
        ``QDialog.DialogCode.Accepted`` — :meth:`_on_accept` is what
        enforces the one required field (name) before allowing that.
        """
        return {
            "name": self._name_edit.text().strip(),
            "provider_type": self._provider_type_combo.currentText(),
            "api_key_env_var": self._api_key_env_var_edit.text().strip() or None,
            "model": self._model_edit.text().strip() or None,
        }
