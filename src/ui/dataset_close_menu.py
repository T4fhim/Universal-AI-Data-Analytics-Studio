# File: src/ui/dataset_close_menu.py
"""The Dataset Explorer tree's right-click "Close Dataset" context menu.

Split out of :class:`~src.ui.dock_manager.DockManager` purely to keep ``dock_manager.py``
under ``tests/ui/test_module_size.py``'s 400-non-docstring-line budget -- this milestone's
addition to that file (close-request wiring for datasets *and* charts/dashboards) would have
pushed it over, and this piece is genuinely self-contained: it needs only the
:class:`~PySide6.QtWidgets.QTreeWidget` it attaches to and the one callback a caller connects,
nothing else :class:`DockManager` itself holds.

Milestone 23: closes the "data accumulates until exit" leak this overhaul's audit named --
before this, nothing in ``src/ui/`` ever called
:meth:`~src.services.workspace_service.WorkspaceService.close_dataset`. A context menu, not a
registered :class:`~src.ui.actions.action_registry.ActionSpec` (unlike ``edit.undo``/
``edit.redo``) -- closing *which* dataset is per-item data, the same reason "Open Recent" stays
bespoke rather than becoming registry entries (see :mod:`~src.ui.menu_bar`'s own docstring).
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QTreeWidget


class DatasetCloseMenu:
    """Wires a "Close Dataset" context menu onto ``tree``.

    Args:
        tree: The Dataset Explorer's tree widget -- items must carry their
            :attr:`~src.services.workspace_service.Dataset.dataset_id` in
            ``Qt.ItemDataRole.UserRole`` (see
            :meth:`~src.ui.dock_manager.DockManager._populate_dataset_items`), the same
            convention :meth:`~src.ui.dock_manager.DockManager.connect_dataset_double_click`
            already relies on.
    """

    def __init__(self, tree: QTreeWidget) -> None:
        self._tree = tree
        self._handler: Callable[[str], None] | None = None
        tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        tree.customContextMenuRequested.connect(self._on_context_menu)

    def connect(self, handler: Callable[[str], None]) -> None:
        """Call ``handler(dataset_id)`` when "Close Dataset" is chosen for an item."""
        self._handler = handler

    def _on_context_menu(self, position) -> None:
        item = self._tree.itemAt(position)
        dataset_id = (
            item.data(0, Qt.ItemDataRole.UserRole) if item is not None else None
        )
        if dataset_id is None or self._handler is None:
            return  # no item under the cursor, or nothing connected via connect()
        self._show_menu(dataset_id, self._tree.viewport().mapToGlobal(position))

    def _show_menu(self, dataset_id: str, global_position) -> None:
        # Split out of _on_context_menu so a test can monkeypatch this one method (bypassing
        # QMenu.exec()'s real, blocking popup -- there is nobody offscreen to dismiss it)
        # without needing to fake mouse/keyboard input just to prove the handler wiring works.
        handler = self._handler
        assert handler is not None  # _on_context_menu already checked this
        menu = QMenu(self._tree)
        close_action = QAction("Close Dataset", menu)
        close_action.triggered.connect(lambda: handler(dataset_id))
        menu.addAction(close_action)
        menu.exec(global_position)
