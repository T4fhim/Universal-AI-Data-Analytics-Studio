# File: src/ui/command_palette.py
"""A Ctrl+K searchable list of every ``palette_visible`` action.

Lists every :class:`~src.ui.actions.action_registry.ActionSpec` with
``palette_visible=True`` and, on selection, calls
``QAction.trigger()`` on the exact same ``QAction``
:class:`~src.ui.actions.action_binder.ActionBinder` hands the menu bar and
toolbar -- not a second, independent invocation path. That sharing (see
``ActionBinder``'s module docstring) is what makes "selecting an action in
the palette invokes the same handler the menu/toolbar would" true by
construction: there is only ever one ``QAction`` per id, so triggering it
from here runs the identical ``triggered`` connection a menu click would.

A disabled action still appears in the list (so the palette answers "what
*can* this application do," not only "what can I do right now" -- useful
for discovery) but ``QAction.trigger()`` on a disabled action is a Qt-level
no-op, so selecting one safely does nothing rather than crashing or forcing
a state check here that would duplicate ``ActionBinder.refresh_enablement``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.logger import get_logger
from src.ui.actions.action_binder import ActionBinder
from src.ui.actions.action_registry import list_actions
from src.ui.ui_state_bus import UiStateBus

_logger = get_logger(__name__)

_ACTION_ID_ROLE = Qt.ItemDataRole.UserRole


class CommandPalette(QDialog):
    """A modal, keyboard-driven searchable list of actions.

    Args:
        parent_window: The window this palette overlays.
        binder: Supplies the shared ``QAction`` for whichever entry is
            selected.
        state_bus: If given, :meth:`request_refresh` is called on every
            open so enablement is current before the user sees the list --
            the palette-open lazy safety net
            :mod:`~src.ui.ui_state_bus` documents alongside its own
            coalesced-mutation path.
    """

    def __init__(
        self,
        parent_window: QWidget,
        binder: ActionBinder,
        state_bus: UiStateBus | None = None,
    ) -> None:
        super().__init__(parent_window)
        self._binder = binder
        self._state_bus = state_bus

        self.setWindowTitle(self.tr("Command Palette"))
        self.setModal(True)
        self.setMinimumWidth(480)

        layout = QVBoxLayout(self)
        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Type to search actions…")
        layout.addWidget(self._search)

        self._list = QListWidget(self)
        layout.addWidget(self._list)

        self._search.textChanged.connect(self._refilter)

    def showEvent(self, event) -> None:
        if self._state_bus is not None:
            self._state_bus.request_refresh()
        self._search.clear()
        self._populate()
        self._search.setFocus()
        super().showEvent(event)

    def _populate(self) -> None:
        self._list.clear()
        visible_specs = sorted(
            (spec for spec in list_actions().values() if spec.palette_visible),
            key=lambda spec: spec.label,
        )
        for spec in visible_specs:
            item = QListWidgetItem(spec.label)
            item.setData(_ACTION_ID_ROLE, spec.action_id)
            if spec.status_tip:
                item.setToolTip(spec.status_tip)
            self._list.addItem(item)
        if self._list.count() > 0:
            self._list.setCurrentRow(0)

    def _refilter(self, text: str) -> None:
        needle = text.strip().lower()
        first_visible_row: int | None = None
        for row in range(self._list.count()):
            item = self._list.item(row)
            action_id = item.data(_ACTION_ID_ROLE)
            haystack = f"{item.text()} {action_id}".lower()
            matches = needle in haystack
            item.setHidden(not matches)
            if matches and first_visible_row is None:
                first_visible_row = row
        if first_visible_row is not None:
            self._list.setCurrentRow(first_visible_row)

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Escape:
            self.reject()
            return
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up):
            # Arrow keys move the list selection even while the search
            # field has keyboard focus -- without forwarding these, the
            # user would have to Tab into the list before Up/Down did
            # anything, breaking the "type to filter, arrow to pick"
            # flow every command palette (VS Code, Sublime, etc.) uses.
            self._list.keyPressEvent(event)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._activate_current()
            return
        super().keyPressEvent(event)

    def _activate_current(self) -> None:
        item = self._list.currentItem()
        if item is None or item.isHidden():
            return
        action_id = item.data(_ACTION_ID_ROLE)
        self.accept()
        self._binder.action_for(action_id).trigger()
