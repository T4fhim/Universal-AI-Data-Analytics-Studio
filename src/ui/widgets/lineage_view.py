# File: src/ui/widgets/lineage_view.py
"""Renders a dataset's ancestry/descent as a real tree -- previously orphaned data made visible.

:meth:`~src.services.workspace_service.WorkspaceService.get_lineage` and :meth:`~src.services.
workspace_service.WorkspaceService.get_children` have existed since milestone 3a, but nothing in
``src/ui/`` ever called either before this milestone -- a cleaning operation's
``parent_dataset_id``/``derivation_description`` were recorded and then never shown to a user
anywhere except the Dataset Explorer dock's flat parent-nesting (see
:meth:`~src.ui.dock_manager.DockManager._populate_dataset_items`), which nests by
``parent_dataset_id`` too but has no dedicated "why was this derived" view.

**A plain ``QTreeWidget``, not custom-painted** -- the same "standard widgets get accessibility
for free" reasoning :class:`~src.ui.workbench.stage_rail.StageRail` and
:class:`~src.ui.dock_manager.DockManager`'s own dataset tree already follow (see the plan's A3:
"Qt 6 on Windows uses the UI Automation accessibility backend; standard widgets are accessible for
free, while custom-painted ones need a ``QAccessibleInterface`` plugin"). :class:`LineageView`
*is* a ``QTreeWidget`` rather than a ``QWidget`` wrapping one, matching that same dataset tree's
own shape exactly, since there is no second zone (a filter bar, a toolbar) this view needs to
compose alongside it -- unlike :class:`~src.ui.widgets.data_table.data_table_view.DataTableView`,
which legitimately needs to be a container because it *does* have more than one child widget.

**Takes already-fetched data, not a service reference.** :meth:`show_lineage` accepts the plain
``list[Dataset]`` results :meth:`~src.services.workspace_service.WorkspaceService.get_lineage`/
:meth:`~src.services.workspace_service.WorkspaceService.get_children` already return, rather than
a ``WorkspaceService`` instance to query itself -- this package must never import
``src.ui.controllers`` (enforced by ``tests/ui/test_import_layering.py``'s
``_WIDGET_LIKE_PACKAGES`` rule) and, more importantly, matches every other stage-page widget's
"structure here, behavior wired by the caller" split documented in
``src/ui/workbench/__init__.py``: the caller (a controller) resolves the live data, this widget
only renders whatever it is handed.

**Only one level of descendants, deliberately.** :meth:`~src.services.workspace_service.
WorkspaceService.get_children` itself only ever returns *direct* children, not a recursive
subtree -- calling it again for each child to build a deeper tree would need this widget to hold
a live service reference (the exact thing the paragraph above says it must not do). A caller
that wants a specific dataset's full descendant subtree shown can call :meth:`show_lineage`
again, retargeted at that dataset -- there is precedent for "click to re-target" navigation
elsewhere in this codebase (the Dataset Explorer's own double-click-to-view), so this is not a
new interaction pattern being invented here, just not one this milestone's scope wires up.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from src.ui.a11y.accessible import describe

if TYPE_CHECKING:
    from src.services.workspace_service import Dataset

# Mirrors DockManager._populate_dataset_items's own Qt.ItemDataRole.UserRole convention for
# stashing a dataset_id on a tree item -- NOT DisplayRole (0), which would silently overwrite
# the human-readable label text set at construction time with the raw id.
_ROLE_DATASET_ID = Qt.ItemDataRole.UserRole


def _label(dataset: Dataset) -> str:
    return f"{dataset.name} ({dataset.row_count} rows x {dataset.column_count} cols)"


class LineageView(QTreeWidget):
    """A tree of one dataset's ancestors, itself, and direct descendants.

    Args:
        parent: Parent widget.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("lineageView")
        self.setHeaderHidden(True)
        describe(
            self,
            name="Dataset lineage",
            description=(
                "Shows which dataset this one was derived from, and what has been "
                "derived from it."
            ),
        )
        self._show_placeholder()

    def _show_placeholder(self) -> None:
        self.clear()
        QTreeWidgetItem(self, ["(No dataset selected)"])

    def show_lineage(
        self,
        ancestors: list[Dataset],
        target: Dataset | None,
        descendants: list[Dataset],
    ) -> None:
        """Render ``ancestors`` (root first) -> ``target`` -> ``descendants`` as a nested tree.

        Args:
            ancestors: :meth:`~src.services.workspace_service.WorkspaceService.get_lineage`'s
                return value for ``target`` -- root-first, each one the parent of the next,
                ending immediately before ``target`` itself.
            target: The dataset this lineage is centered on -- rendered as the deepest ancestor
                item's child (or as the tree's own root item, if ``ancestors`` is empty). ``None``
                clears the tree back to its initial placeholder, the same "nothing to show yet"
                state a freshly constructed view starts in.
            descendants: :meth:`~src.services.workspace_service.WorkspaceService.get_children`'s
                return value for ``target`` -- rendered as ``target``'s own children. See this
                module's own docstring for why this is only one level deep.
        """
        self.clear()
        if target is None:
            self._show_placeholder()
            return

        parent_item: QTreeWidget | QTreeWidgetItem = self
        for ancestor in ancestors:
            item = QTreeWidgetItem(parent_item, [_label(ancestor)])
            item.setData(0, _ROLE_DATASET_ID, ancestor.dataset_id)
            parent_item = item

        target_item = QTreeWidgetItem(parent_item, [f"{_label(target)}  [active]"])
        target_item.setData(0, _ROLE_DATASET_ID, target.dataset_id)

        for child in descendants:
            child_item = QTreeWidgetItem(target_item, [_label(child)])
            child_item.setData(0, _ROLE_DATASET_ID, child.dataset_id)

        self.expandAll()
