# File: tests/persistence/test_persistence_service.py
"""The eight Control C-3 characterization tests for the persistence layer.

These are the *frozen contract* for :class:`~uadas_core.persistence.
persistence_service.PersistenceService` — one observable behaviour per test,
enumerated verbatim from ``plans/phase-1-6-persistence-contract.md`` §4. They
are written red (before the service exists) so the implementation is proven
against them rather than the other way round; a test that "looks wrong" during
implementation is a contract escalation, not something to edit.

Why these live alongside ``tests/services`` rather than inside it: the
persistence layer is a new top-level ``uadas_core`` package (Qt-free, its own
``lint-imports`` boundary), so its tests get their own package to match.

``tests/conftest.py`` seeds the chart registry at module import (web-transition
1.3), so ``chart_registry.get_chart("bar")`` resolves here without a
``bootstrap()`` call.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd
import pytest

from uadas_core.core.exceptions import ServiceError
from uadas_core.persistence.persistence_service import (
    PersistenceService,
    SaveReport,
    WorkspaceSnapshot,
)
from uadas_core.services.workspace_service import (
    Dashboard,
    DashboardTile,
    Dataset,
    Visualization,
    WorkspaceService,
)
from uadas_core.visualization import chart_registry


def _bar_figure(dataframe: pd.DataFrame, category_column: str) -> object:
    """Build a real ``"bar"`` figure the way a live producer would."""
    return chart_registry.get_chart("bar").chart_class.build(
        dataframe, category_column=category_column
    )


def test_workspace_round_trips_including_a_derived_dataset(tmp_path: Path) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()

    root_df = pd.DataFrame({"city": ["a", "b", "c", "a"], "sales": [1, 2, 3, 4]})
    root = Dataset(
        name="root",
        dataframe=root_df,
        source_format="csv",
        source_path=Path("/data/root.csv"),
    )
    workspace.add_dataset(root)

    derived_df = root_df[root_df["sales"] > 1].reset_index(drop=True)
    derived = Dataset(
        name="derived",
        dataframe=derived_df,
        source_format="csv",
        source_path=None,
        parent_dataset_id=root.dataset_id,
        derivation_description="rows with sales > 1",
    )
    workspace.add_dataset(derived)

    figure = _bar_figure(derived_df, "city")
    viz = Visualization(
        name="bar of city",
        dataset_id=derived.dataset_id,
        figure=figure,
        chart_type="bar",
        chart_parameters={"category_column": "city"},
    )
    workspace.add_visualization(viz)

    tile = DashboardTile(visualization_id=viz.visualization_id, row=2, column=1)
    dashboard = Dashboard(name="dash", tiles=[tile])
    workspace.add_dashboard(dashboard)

    service = PersistenceService()
    report = service.save_workspace(
        workspace.list_datasets(),
        workspace.list_visualizations(),
        workspace.list_dashboards(),
        base,
    )
    assert isinstance(report, SaveReport)
    assert report.skipped_visualization_ids == []

    snapshot = service.load_workspace(base)
    assert isinstance(snapshot, WorkspaceSnapshot)
    assert snapshot.rebuild_failures == []

    by_id = {d.dataset_id: d for d in snapshot.datasets}
    loaded_root = by_id[root.dataset_id]
    loaded_derived = by_id[derived.dataset_id]

    assert loaded_root.dataframe.equals(root_df)
    assert loaded_derived.dataframe.equals(derived_df)
    assert loaded_derived.parent_dataset_id == root.dataset_id
    assert loaded_derived.derivation_description == "rows with sales > 1"
    assert loaded_derived.source_path is None

    # Datasets come back topologically ordered: the parent precedes the child.
    ordered_ids = [d.dataset_id for d in snapshot.datasets]
    assert ordered_ids.index(root.dataset_id) < ordered_ids.index(derived.dataset_id)

    assert len(snapshot.visualizations) == 1
    loaded_viz = snapshot.visualizations[0]
    assert loaded_viz.chart_type == "bar"
    assert loaded_viz.chart_parameters == {"category_column": "city"}
    assert loaded_viz.figure.to_json() == figure.to_json()

    assert len(snapshot.dashboards) == 1
    loaded_tiles = snapshot.dashboards[0].tiles
    assert len(loaded_tiles) == 1
    assert loaded_tiles[0].tile_id == tile.tile_id
    assert (loaded_tiles[0].row, loaded_tiles[0].column) == (2, 1)
    assert loaded_tiles[0].visualization_id == viz.visualization_id


def test_load_rejects_a_parent_dataset_id_cycle(tmp_path: Path) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()

    parent = Dataset(name="a", dataframe=pd.DataFrame({"x": [1]}), source_format="csv")
    workspace.add_dataset(parent)
    child = Dataset(
        name="b",
        dataframe=pd.DataFrame({"x": [2]}),
        source_format="csv",
        parent_dataset_id=parent.dataset_id,
        derivation_description="child of a",
    )
    workspace.add_dataset(child)

    service = PersistenceService()
    service.save_workspace(workspace.list_datasets(), [], [], base)

    # Close the loop directly in the .db: a's parent becomes b.
    connection = sqlite3.connect(base / "workspace.db")
    try:
        connection.execute(
            "UPDATE datasets SET parent_dataset_id = ? WHERE dataset_id = ?",
            (child.dataset_id, parent.dataset_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(ServiceError, match="cycle"):
        service.load_workspace(base)


def test_chart_type_class_name_is_normalised_to_registry_name_on_save(
    tmp_path: Path,
) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()

    frame = pd.DataFrame({"city": ["a", "b", "a"]})
    dataset = Dataset(name="d", dataframe=frame, source_format="csv")
    workspace.add_dataset(dataset)

    viz = Visualization(
        name="v",
        dataset_id=dataset.dataset_id,
        figure=_bar_figure(frame, "city"),
        chart_type="BarChart",  # legacy class-name form
        chart_parameters={"category_column": "city"},
    )
    workspace.add_visualization(viz)

    service = PersistenceService()
    service.save_workspace(
        workspace.list_datasets(), workspace.list_visualizations(), [], base
    )
    snapshot = service.load_workspace(base)

    assert len(snapshot.visualizations) == 1
    assert snapshot.visualizations[0].chart_type == "bar"


def test_visualization_on_a_closed_dataset_is_skipped_on_save(
    tmp_path: Path,
) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()

    frame = pd.DataFrame({"city": ["a", "b"]})
    dataset = Dataset(name="d", dataframe=frame, source_format="csv")
    workspace.add_dataset(dataset)
    viz = Visualization(
        name="v",
        dataset_id=dataset.dataset_id,
        figure=_bar_figure(frame, "city"),
        chart_type="bar",
        chart_parameters={"category_column": "city"},
    )
    workspace.add_visualization(viz)
    workspace.close_dataset(dataset.dataset_id)

    service = PersistenceService()
    report = service.save_workspace(
        workspace.list_datasets(), workspace.list_visualizations(), [], base
    )
    assert report.skipped_visualization_ids == [viz.visualization_id]

    snapshot = service.load_workspace(base)
    assert snapshot.visualizations == []


def test_load_rejects_a_non_uuid4_dataset_id_before_any_path_join(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()
    dataset = Dataset(name="d", dataframe=pd.DataFrame({"x": [1]}), source_format="csv")
    workspace.add_dataset(dataset)

    service = PersistenceService()
    service.save_workspace(workspace.list_datasets(), [], [], base)

    connection = sqlite3.connect(base / "workspace.db")
    try:
        connection.execute("UPDATE datasets SET dataset_id = ?", ("../../etc/passwd",))
        connection.commit()
    finally:
        connection.close()

    read_calls: list[object] = []
    real_read_parquet = pd.read_parquet

    def _spy_read_parquet(path: object, *args: object, **kwargs: object) -> object:
        read_calls.append(path)
        return real_read_parquet(path, *args, **kwargs)

    monkeypatch.setattr(pd, "read_parquet", _spy_read_parquet)

    with pytest.raises(ServiceError):
        service.load_workspace(base)

    # The non-uuid4 id must be rejected before any path is built / opened.
    assert read_calls == []


def test_a_visualization_whose_column_no_longer_exists_is_a_rebuild_failure_not_a_load_abort(
    tmp_path: Path,
) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()

    frame = pd.DataFrame({"city": ["a", "b", "a"], "keep": [1, 2, 3]})
    dataset = Dataset(name="d", dataframe=frame, source_format="csv")
    workspace.add_dataset(dataset)
    viz = Visualization(
        name="v",
        dataset_id=dataset.dataset_id,
        figure=_bar_figure(frame, "city"),
        chart_type="bar",
        chart_parameters={"category_column": "city"},
    )
    workspace.add_visualization(viz)

    service = PersistenceService()
    service.save_workspace(
        workspace.list_datasets(), workspace.list_visualizations(), [], base
    )

    # Rewrite the persisted frame so the viz's referenced column ("city") is
    # gone. The frame SHAPE (row/column counts) is preserved deliberately: a
    # shape change is a structural checksum failure (see the row-count test)
    # and would abort the whole load, which is not what this test exercises.
    parquet_path = base / f"{dataset.dataset_id}.parquet"
    frame.rename(columns={"city": "region"}).to_parquet(parquet_path, index=False)

    snapshot = service.load_workspace(base)

    assert [d.name for d in snapshot.datasets] == ["d"]
    assert viz.visualization_id in snapshot.rebuild_failures
    assert snapshot.visualizations == []


def test_dangling_tile_visualization_id_round_trips(tmp_path: Path) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()
    dataset = Dataset(name="d", dataframe=pd.DataFrame({"x": [1]}), source_format="csv")
    workspace.add_dataset(dataset)

    tile = DashboardTile(visualization_id="ghost", row=0, column=0)
    dashboard = Dashboard(name="dash", tiles=[tile])

    service = PersistenceService()
    # `dashboard` is handed to save_workspace as plain data — add_dashboard
    # would reject a tile whose visualization is not tracked, which is exactly
    # the persisted state this test needs to round-trip.
    service.save_workspace(workspace.list_datasets(), [], [dashboard], base)
    snapshot = service.load_workspace(base)

    workspace.load_snapshot(
        snapshot.datasets, snapshot.visualizations, snapshot.dashboards
    )
    resolved = workspace.get_dashboard_tiles(dashboard.dashboard_id)

    assert len(resolved) == 1
    resolved_tile, resolved_viz = resolved[0]
    assert resolved_viz is None
    assert resolved_tile.visualization_id == "ghost"
    assert resolved_tile.tile_id == tile.tile_id


def test_row_count_checksum_mismatch_is_a_structural_load_error(
    tmp_path: Path,
) -> None:
    base = tmp_path / "p.workspace"
    workspace = WorkspaceService()
    frame = pd.DataFrame({"x": [1, 2, 3, 4]})
    dataset = Dataset(name="d", dataframe=frame, source_format="csv")
    workspace.add_dataset(dataset)

    service = PersistenceService()
    service.save_workspace(workspace.list_datasets(), [], [], base)

    # Overwrite the frame with a different row count: metadata now disagrees.
    parquet_path = base / f"{dataset.dataset_id}.parquet"
    pd.DataFrame({"x": [1, 2]}).to_parquet(parquet_path, index=False)

    with pytest.raises(ServiceError):
        service.load_workspace(base)
