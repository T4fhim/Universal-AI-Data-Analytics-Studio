# File: tests/services/test_workspace_service.py
"""Tests for uadas_core.services.workspace_service.WorkspaceService.

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
import plotly.graph_objects as go
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.models import Dashboard, DashboardTile, Dataset, Visualization
from uadas_core.services.workspace_service import WorkspaceService


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


def test_dashboard_tile_gets_a_uuid4_tile_id_by_default() -> None:
    a = DashboardTile(visualization_id="v", row=0, column=0)
    b = DashboardTile(visualization_id="v", row=0, column=1)
    assert len(a.tile_id) == 36 and a.tile_id != b.tile_id
    assert (
        DashboardTile(visualization_id="v", row=0, column=0, tile_id="fixed").tile_id
        == "fixed"
    )


# -- load_snapshot (Phase 1.6 restore entry point) --------------------------


def _viz(dataset_id: str, name: str = "v") -> Visualization:
    return Visualization(
        name=name,
        dataset_id=dataset_id,
        figure=go.Figure(),
        chart_type="bar",
        chart_parameters={"category_column": "a"},
    )


def test_load_snapshot_replaces_all_state() -> None:
    workspace = WorkspaceService()
    stale = _make_dataset("stale")
    workspace.add_dataset(stale)
    workspace.set_active_dataset(stale.dataset_id)

    restored_ds = _make_dataset("restored")
    restored_viz = _viz(restored_ds.dataset_id)
    tile = DashboardTile(
        visualization_id=restored_viz.visualization_id, row=0, column=0
    )
    restored_dash = Dashboard(name="d", tiles=[tile])

    workspace.load_snapshot([restored_ds], [restored_viz], [restored_dash])

    assert workspace.list_datasets() == [restored_ds]
    with pytest.raises(ServiceError):
        workspace.get_dataset(stale.dataset_id)
    assert workspace.get_dataset(restored_ds.dataset_id) is restored_ds
    assert workspace.list_visualizations() == [restored_viz]
    assert workspace.list_dashboards() == [restored_dash]


def test_load_snapshot_tolerates_a_dangling_parent_dataset_id() -> None:
    workspace = WorkspaceService()
    child = Dataset(
        name="child",
        dataframe=pd.DataFrame({"a": [1]}),
        source_format="csv",
        parent_dataset_id="00000000-0000-4000-8000-000000000000",
        derivation_description="derived from a parent not in the snapshot",
    )

    workspace.load_snapshot([child], [], [])

    assert workspace.get_dataset(child.dataset_id) is child
    # get_lineage stops gracefully at the dangling parent rather than raising.
    assert workspace.get_lineage(child.dataset_id) == []


def test_load_snapshot_tolerates_a_dangling_tile_visualization_id() -> None:
    workspace = WorkspaceService()
    dataset = _make_dataset("d")
    tile = DashboardTile(visualization_id="never-added", row=1, column=2)
    dashboard = Dashboard(name="dash", tiles=[tile])

    workspace.load_snapshot([dataset], [], [dashboard])

    resolved = workspace.get_dashboard_tiles(dashboard.dashboard_id)
    assert resolved == [(tile, None)]


def test_load_snapshot_rejects_a_parent_dataset_id_cycle() -> None:
    workspace = WorkspaceService()
    a = Dataset(
        name="a",
        dataframe=pd.DataFrame({"a": [1]}),
        source_format="csv",
        dataset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        parent_dataset_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
    )
    b = Dataset(
        name="b",
        dataframe=pd.DataFrame({"a": [1]}),
        source_format="csv",
        dataset_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        parent_dataset_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
    )

    with pytest.raises(ServiceError, match="cycle"):
        workspace.load_snapshot([a, b], [], [])


def test_load_snapshot_clears_active_selection() -> None:
    workspace = WorkspaceService()
    dataset = _make_dataset("d")
    workspace.add_dataset(dataset)
    viz = _viz(dataset.dataset_id)
    workspace.add_visualization(viz)
    workspace.set_active_dataset(dataset.dataset_id)
    workspace.set_active_visualization(viz.visualization_id)

    workspace.load_snapshot([dataset], [viz], [])

    assert workspace.get_active_dataset() is None
    assert workspace.get_active_visualization() is None
