# File: tests/services/test_workspace_service.py
"""Tests for src.services.workspace_service.WorkspaceService.

Covers the documented non-cascading close behavior (CLAUDE.md: "Closing
a dataset or visualization does not cascade to things derived from
it... orphaned references are normal, expected state... not corruption
to guard against"). Each assertion below is tied to specific, directly
read source behavior in workspace_service.py rather than an assumed
"cascading" model:

* close_dataset() does not alter or remove a derived child's
  parent_dataset_id (workspace_service.py:287-293 only pops the closed
  id from self._datasets; it never touches other datasets).
* get_lineage() on a chain with a closed ancestor stops at the orphan
  without raising (workspace_service.py:326-328: an unresolved
  parent_dataset_id causes an explicit `break`, not a raise).
* get_children() does not require its argument to currently be loaded,
  by explicit design (workspace_service.py:334-345's own docstring:
  "well-defined even if the ID itself is stale") — it still returns a
  closed parent's children after that parent has been closed.
* close_dataset() on the active dataset clears get_active_dataset() to
  None rather than reassigning another loaded dataset.
"""

from __future__ import annotations

import pandas as pd
import pytest

from src.core.exceptions import ServiceError
from src.services.workspace_service import Dataset, WorkspaceService


def _make_dataset(name: str = "root", parent_dataset_id: str | None = None) -> Dataset:
    return Dataset(
        name=name,
        dataframe=pd.DataFrame({"a": [1, 2, 3]}),
        source_format="csv",
        parent_dataset_id=parent_dataset_id,
    )


def test_close_dataset_does_not_alter_childs_parent_dataset_id() -> None:
    workspace = WorkspaceService()
    parent = _make_dataset("parent")
    workspace.add_dataset(parent)
    child = _make_dataset("child", parent_dataset_id=parent.dataset_id)
    workspace.add_dataset(child)

    workspace.close_dataset(parent.dataset_id)

    assert child.parent_dataset_id == parent.dataset_id


def test_get_lineage_stops_at_orphaned_ancestor_without_raising() -> None:
    workspace = WorkspaceService()
    parent = _make_dataset("parent")
    workspace.add_dataset(parent)
    child = _make_dataset("child", parent_dataset_id=parent.dataset_id)
    workspace.add_dataset(child)

    workspace.close_dataset(parent.dataset_id)

    # Must not raise: an orphaned ancestor is documented as normal,
    # expected state.
    lineage = workspace.get_lineage(child.dataset_id)

    assert lineage == []


def test_get_children_returns_children_of_a_closed_parent_without_raising() -> None:
    workspace = WorkspaceService()
    parent = _make_dataset("parent")
    workspace.add_dataset(parent)
    child = _make_dataset("child", parent_dataset_id=parent.dataset_id)
    workspace.add_dataset(child)

    children_before_close = workspace.get_children(parent.dataset_id)
    workspace.close_dataset(parent.dataset_id)
    children_after_close = workspace.get_children(parent.dataset_id)

    assert children_before_close == [child]
    assert children_after_close == [child]

    # get_dataset(), by contrast, does raise for the same now-closed id
    # — confirming get_children()'s documented, deliberately different
    # behavior is actually being exercised here, not just coincidence.
    with pytest.raises(ServiceError):
        workspace.get_dataset(parent.dataset_id)


def test_close_dataset_clears_active_dataset_without_reassigning() -> None:
    workspace = WorkspaceService()
    first = _make_dataset("first")
    second = _make_dataset("second")
    workspace.add_dataset(first)
    workspace.add_dataset(second)
    workspace.set_active_dataset(first.dataset_id)

    workspace.close_dataset(first.dataset_id)

    assert workspace.get_active_dataset() is None
