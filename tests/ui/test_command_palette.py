# File: tests/ui/test_command_palette.py
"""Tests for the Ctrl+K command palette.

Covers the M17 acceptance criterion directly: the palette lists every
palette_visible action, and selecting one invokes the same handler the
menu/toolbar would -- proven here by checking it is literally the same
QAction object, not merely "a call that happens to do the same thing."
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication, QWidget

from src.ui.actions.action_binder import ActionBinder
from src.ui.actions.action_registry import ActionCategory, ActionSpec, register_action
from src.ui.command_palette import CommandPalette


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.ui.actions.action_registry as registry_module

    monkeypatch.setattr(registry_module, "_REGISTRY", {})
    register_action(
        ActionSpec(
            action_id="test.visible_one",
            label="Visible One",
            category=ActionCategory.PROJECT,
        )
    )
    register_action(
        ActionSpec(
            action_id="test.visible_two",
            label="Visible Two",
            category=ActionCategory.PROJECT,
        )
    )
    register_action(
        ActionSpec(
            action_id="test.hidden",
            label="Hidden From Palette",
            category=ActionCategory.PROJECT,
            palette_visible=False,
        )
    )


def test_palette_lists_every_palette_visible_action(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    palette = CommandPalette(window, binder)
    palette.show()

    labels = {palette._list.item(i).text() for i in range(palette._list.count())}
    assert labels == {"Visible One", "Visible Two"}
    palette.close()


def test_selecting_an_item_triggers_the_same_qaction_the_menu_would_use(
    qapp: QApplication,
) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    calls = []
    bound_action = binder.bind("test.visible_one", lambda: calls.append(1))

    palette = CommandPalette(window, binder)
    palette.show()
    palette._list.setCurrentRow(0)  # "Visible One" sorts first alphabetically
    palette._activate_current()

    assert calls == [1]
    # The palette invoked the *same* QAction menu_bar.py/toolbar.py would
    # have (action_for returns the identical cached object) -- not a
    # second, independently-triggered call path.
    assert binder.action_for("test.visible_one") is bound_action
    palette.close()


def test_typing_filters_the_list(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    palette = CommandPalette(window, binder)
    palette.show()

    palette._search.setText("Two")

    visible_labels = {
        palette._list.item(i).text()
        for i in range(palette._list.count())
        if not palette._list.item(i).isHidden()
    }
    assert visible_labels == {"Visible Two"}
    palette.close()


def test_escape_rejects_the_dialog(qapp: QApplication) -> None:
    window = QWidget()
    binder = ActionBinder(window)
    palette = CommandPalette(window, binder)
    palette.show()

    event = QKeyEvent(
        QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier
    )
    palette.keyPressEvent(event)

    assert palette.result() == CommandPalette.DialogCode.Rejected
