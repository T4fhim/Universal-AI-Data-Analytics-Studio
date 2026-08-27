# File: tests/ui/widgets/test_lineage_view.py
"""Tests for LineageView -- milestone 23 acceptance criterion 4.

"A test constructs a lineage view against a real multi-generation dataset chain (dataset ->
cleaned child -> cleaned grandchild) and asserts the tree structure reflects it." Uses a real
:class:`~src.services.workspace_service.WorkspaceService` and a real
:class:`~src.cleaning.duplicates.DropDuplicates` operation to build the chain -- not synthetic
``Dataset`` stand-ins with a hand-set ``parent_dataset_id`` -- so :meth:`~src.services.
workspace_service.WorkspaceService.get_lineage`/:meth:`~src.services.workspace_service.
WorkspaceService.get_children`'s real output is what drives the assertions.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.cleaning.duplicates import DropDuplicates
from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.widgets.lineage_view import LineageView


def _make_chain() -> tuple[WorkspaceService, Dataset, Dataset, Dataset]:
    """root -> child -> grandchild, each derived via a real DropDuplicates.apply() call."""
    workspace = WorkspaceService()
    root = Dataset(
        name="root", dataframe=pd.DataFrame({"a": [1, 1, 2]}), source_format="csv"
    )
    workspace.add_dataset(root)
    child = DropDuplicates.apply(root)
    workspace.add_dataset(child)
    grandchild = DropDuplicates.apply(child)
    workspace.add_dataset(grandchild)
    return workspace, root, child, grandchild


def test_a_fresh_view_shows_the_placeholder(qapp: QApplication) -> None:
    view = LineageView()
    assert view.topLevelItemCount() == 1
    assert view.topLevelItem(0).text(0) == "(No dataset selected)"


def test_show_lineage_with_none_target_resets_to_the_placeholder(
    qapp: QApplication,
) -> None:
    view = LineageView()
    workspace, root, child, _grandchild = _make_chain()
    view.show_lineage(workspace.get_lineage(child.dataset_id), child, [])

    view.show_lineage([], None, [])

    assert view.topLevelItemCount() == 1
    assert view.topLevelItem(0).text(0) == "(No dataset selected)"


def test_lineage_for_the_middle_dataset_shows_ancestor_target_and_descendant(
    qapp: QApplication,
) -> None:
    """The literal acceptance-criterion scenario: dataset -> cleaned child -> cleaned
    grandchild, viewed centered on the middle (child) dataset -- root above, grandchild below.
    """
    workspace, root, child, grandchild = _make_chain()

    ancestors = workspace.get_lineage(child.dataset_id)
    descendants = workspace.get_children(child.dataset_id)
    assert ancestors == [root]  # sanity: real WorkspaceService output, not a stand-in
    assert descendants == [grandchild]

    view = LineageView()
    view.show_lineage(ancestors, child, descendants)

    # Root at the tree's top level, exactly one item.
    assert view.topLevelItemCount() == 1
    root_item = view.topLevelItem(0)
    assert root_item.text(0).startswith(root.name)

    # The target (child) is root's only child, marked [active].
    assert root_item.childCount() == 1
    target_item = root_item.child(0)
    assert target_item.text(0).startswith(child.name)
    assert "[active]" in target_item.text(0)

    # The grandchild is nested one level under the target.
    assert target_item.childCount() == 1
    descendant_item = target_item.child(0)
    assert descendant_item.text(0).startswith(grandchild.name)


def test_lineage_for_the_root_dataset_has_no_ancestors(qapp: QApplication) -> None:
    workspace, root, child, _grandchild = _make_chain()

    ancestors = workspace.get_lineage(root.dataset_id)
    descendants = workspace.get_children(root.dataset_id)
    assert ancestors == []

    view = LineageView()
    view.show_lineage(ancestors, root, descendants)

    # The root dataset itself is the tree's only top-level item (no ancestor above it).
    assert view.topLevelItemCount() == 1
    root_item = view.topLevelItem(0)
    assert "[active]" in root_item.text(0)
    assert root_item.childCount() == 1
    assert root_item.child(0).text(0).startswith(child.name)


def test_lineage_for_the_leaf_dataset_has_no_descendants(qapp: QApplication) -> None:
    workspace, root, child, grandchild = _make_chain()

    ancestors = workspace.get_lineage(grandchild.dataset_id)
    descendants = workspace.get_children(grandchild.dataset_id)
    assert ancestors == [root, child]  # root-first
    assert descendants == []

    view = LineageView()
    view.show_lineage(ancestors, grandchild, descendants)

    root_item = view.topLevelItem(0)
    child_item = root_item.child(0)
    target_item = child_item.child(0)
    assert "[active]" in target_item.text(0)
    assert target_item.childCount() == 0


def test_items_carry_their_dataset_id_for_future_click_to_navigate_use(
    qapp: QApplication,
) -> None:
    workspace, root, child, _grandchild = _make_chain()
    view = LineageView()
    view.show_lineage(workspace.get_lineage(child.dataset_id), child, [])

    root_item = view.topLevelItem(0)
    assert root_item.data(0, Qt.ItemDataRole.UserRole) == root.dataset_id
    target_item = root_item.child(0)
    assert target_item.data(0, Qt.ItemDataRole.UserRole) == child.dataset_id
