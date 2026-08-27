# File: src/ui/widgets/dataset_explorer_view.py
"""``DatasetExplorerView``: the Dataset Explorer dock's tree, plus milestone 27's EmptyState page.

Extracted out of :class:`~src.ui.dock_manager.DockManager` in milestone 27, purely to keep
``dock_manager.py`` under ``tests.ui.test_module_size``'s 400-line budget -- that module was
already at 396/400 non-docstring lines (zero real headroom) before this milestone's own
"(No datasets loaded)" -> :class:`~src.ui.widgets.empty_state.EmptyState` conversion needed
room to land. The same "same logic, new home" extraction milestones 19 and 26 already
established as this codebase's answer to the module-size test's own stated purpose ("a hard
ceiling is what actually prevents 'one more feature' additions from silently recreating the
problem") -- every method here is logic that used to live directly on ``DockManager``
(``_populate_dataset_items``, ``_rebuild_dataset_tree``), moved essentially verbatim behind a
narrower, tree-only interface. ``DockManager`` still owns :class:`~src.ui.dataset_close_menu.
DatasetCloseMenu` and the double-click wiring -- both attach to :attr:`DatasetExplorerView.tree`
directly, exactly as they attached to ``DockManager``'s own ``_dataset_tree_widget`` before.

An illustration + action button cannot live inside a single ``QTreeWidgetItem`` the way the old
"(No datasets loaded)" placeholder row's plain text could -- this is a real ``QStackedWidget``
switch (tree page vs. :class:`~src.ui.widgets.empty_state.EmptyState` page) driven by
:meth:`rebuild`, not a cosmetic change.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QStackedWidget, QTreeWidget, QTreeWidgetItem, QWidget

from src.ui.widgets.empty_state import EmptyState


def _tr(text: str) -> str:
    """``QCoreApplication.translate`` for this module -- not a ``QObject`` method call, since
    the two module-level helpers below are plain functions, not bound methods.
    """
    return QCoreApplication.translate("DatasetExplorerView", text)


def _label(dataset: object) -> str:
    return f"{dataset.name} ({dataset.row_count} rows x {dataset.column_count} cols)"  # type: ignore[attr-defined]


class DatasetExplorerView(QStackedWidget):
    """A dataset tree page plus an :class:`~src.ui.widgets.empty_state.EmptyState` page.

    Args:
        parent: Parent widget.

    Attributes:
        tree: The real ``QTreeWidget`` -- :class:`~src.ui.dock_manager.DockManager` attaches
            :class:`~src.ui.dataset_close_menu.DatasetCloseMenu` and the double-click handler to
            this directly, unchanged from before this class existed.
        empty_state: Shown instead of :attr:`tree` whenever :meth:`rebuild` is called with no
            datasets.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderHidden(True)
        self.empty_state = EmptyState(
            heading=_tr("No Datasets Loaded"),
            message=_tr("Use File > Open Dataset to import your first file."),
            parent=self,
        )
        self.addWidget(self.tree)
        self.addWidget(self.empty_state)
        # Milestone 20: the deleted Project Explorer dock's one job -- naming the open project
        # (or "(No project open)") -- is absorbed here as the tree's own top-level node. See
        # DockManager.set_project_label's own docstring for the full A3 dock-disposition
        # rationale; this class only owns the resulting label string and rebuild trigger.
        self._project_label = "(No project open)"
        self._last_datasets: list = []
        self.rebuild([])

    def set_project_label(self, project_name: str | None) -> None:
        """Update the "Project" top-level node's text and rebuild to show it."""
        self._project_label = (
            f"Project: {project_name}" if project_name else "(No project open)"
        )
        self.rebuild(self._last_datasets)

    def rebuild(self, datasets: list) -> None:
        """Clear and repopulate: the Project node first, then datasets or the EmptyState page.

        Datasets whose ``parent_dataset_id`` points at another dataset in ``datasets`` are
        nested as tree children of that parent, recursively, so a chain of cleaning operations
        reads as a lineage rather than a flat, unordered list -- see
        :class:`~src.ui.dock_manager.DockManager.refresh_dataset_list`'s own docstring (the
        caller this method's logic was extracted from) for the full rationale, including why a
        dataset whose parent was closed is still rendered at the top level rather than dropped.
        """
        self._last_datasets = datasets
        self.tree.clear()
        QTreeWidgetItem(self.tree, [self._project_label])
        if not datasets:
            self.setCurrentWidget(self.empty_state)
            return
        self._populate_items(datasets)
        self.setCurrentWidget(self.tree)

    def _populate_items(self, datasets: list) -> None:
        by_id = {dataset.dataset_id: dataset for dataset in datasets}
        items_by_id: dict[str, QTreeWidgetItem] = {}

        def _build_item(dataset: object) -> QTreeWidgetItem:
            if dataset.dataset_id in items_by_id:  # type: ignore[attr-defined]
                return items_by_id[dataset.dataset_id]  # type: ignore[attr-defined]
            parent_id = dataset.parent_dataset_id  # type: ignore[attr-defined]
            if parent_id is not None and parent_id in by_id:
                parent_item = _build_item(by_id[parent_id])
                item = QTreeWidgetItem(parent_item, [_label(dataset)])
            else:
                item = QTreeWidgetItem(self.tree, [_label(dataset)])
            # Milestone 18: the item's dataset_id, read back out by
            # DockManager.connect_dataset_double_click's handler.
            item.setData(0, Qt.ItemDataRole.UserRole, dataset.dataset_id)  # type: ignore[attr-defined]
            items_by_id[dataset.dataset_id] = item  # type: ignore[attr-defined]
            return item

        for dataset in datasets:
            _build_item(dataset)
        self.tree.expandAll()
