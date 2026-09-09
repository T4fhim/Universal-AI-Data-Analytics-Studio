# File: tests/ui/controllers/test_project_controller.py
"""Tests for ProjectController's project-lifecycle handlers.

Web-transition 1.6 reworked the save/open paths: a save now also persists the
full workspace (datasets incl. derived, visualizations, dashboards) to a
``<project-stem>.workspace/`` directory via
:class:`~uadas_core.persistence.persistence_service.PersistenceService`, and an
open restores from that directory when it exists. The milestone-19
"``record_datasets`` skipped these derived datasets" warning was **removed** in
1.6 -- those datasets are now saved in full, so the warning would be false; its
1.6 counterpart, ``_warn_about_skipped_visualizations``, fires only for the one
thing a full-replace save genuinely drops (a visualization whose dataset is
closed).

Fakes are duck-typed for the collaborators ProjectController only calls a few
methods on; the workspace + persistence layers are the **real** classes, since
the point of these tests is the real save/load round trip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
from PySide6.QtWidgets import QApplication, QMainWindow

from src.ui.controllers.project_controller import ProjectController
from uadas_core.persistence.persistence_service import PersistenceService
from uadas_core.services.project_service import Project
from uadas_core.services.workspace_service import (
    Dataset,
    Visualization,
    WorkspaceService,
)
from uadas_core.visualization import chart_registry


class _SyncWorkerRunner:
    """Runs ``fn(*args)`` inline and drives the result/error/finished callbacks.

    ProjectController hands its save/load calls to ``WorkerRunner.run`` so they
    stay off the UI thread; here we execute them synchronously so a test can
    assert on the outcome without a Qt event loop.
    """

    def run(
        self,
        fn: Any,
        *args: Any,
        on_result: Any = None,
        on_error: Any = None,
        on_finished: Any = None,
        **_kwargs: Any,
    ) -> None:
        try:
            result = fn(*args)
        except Exception as exc:  # noqa: BLE001 - mirrors WorkerRunner's own catch-all
            if on_error is not None:
                on_error(exc, "")
        else:
            if on_result is not None:
                on_result(result)
        finally:
            if on_finished is not None:
                on_finished()


class _FakeProjectService:
    def __init__(self, active_project: Project | None, skipped_names: Any = ()) -> None:
        self._active_project = active_project
        self._skipped_names = list(skipped_names)
        self.saved_projects: list[Project] = []

    def get_active_project(self) -> Project | None:
        return self._active_project

    def open_project(self, path: Path) -> Project:
        project = Project(name=path.stem, path=path)
        self._active_project = project
        return project

    def record_datasets(self, project: Any, datasets: Any) -> list[str]:
        return self._skipped_names

    def get_recorded_dataset_paths(self, project: Any) -> list[tuple[str, Path]]:
        return []

    def save_project(self, project: Project, path: Path | None = None) -> Project:
        if path is not None:
            project.path = path
        self.saved_projects.append(project)
        return project

    def get_recent_projects(self) -> list[str]:
        return []


class _FakeDockManager:
    def __init__(self) -> None:
        self.console_messages: list[str] = []
        self.refreshed_with: list[Any] = []

    def append_console_message(self, text: str) -> None:
        self.console_messages.append(text)

    def refresh_dataset_list(self, datasets: Any) -> None:
        self.refreshed_with.append(list(datasets))


class _FakeStatusBar:
    def show_message(self, text: str) -> None:
        pass

    def set_active_project_label(self, name: Any) -> None:
        pass

    def show_busy(self, text: str) -> None:
        pass

    def hide_busy(self) -> None:
        pass

    def show_progress(self, value: int, text: str) -> None:
        pass


class _FakeStateBus:
    def __init__(self) -> None:
        self.refresh_count = 0

    def request_refresh(self) -> None:
        self.refresh_count += 1


class _FakeMenuBar:
    def update_recent_projects_menu(self, recent_paths: Any, on_open: Any) -> None:
        pass


def _make_controller(
    parent: QMainWindow,
    project_service: _FakeProjectService,
    workspace_service: WorkspaceService,
) -> tuple[ProjectController, _FakeDockManager, _FakeStateBus]:
    dock = _FakeDockManager()
    state_bus = _FakeStateBus()
    controller = ProjectController(
        parent,
        project_service,
        workspace_service,
        PersistenceService(),
        dock,
        _FakeStatusBar(),
        state_bus,
        _SyncWorkerRunner(),
        _FakeMenuBar(),
    )
    return controller, dock, state_bus


def _bar_figure(frame: pd.DataFrame) -> object:
    return chart_registry.get_chart("bar").chart_class.build(
        frame, category_column="city"
    )


def test_save_project_persists_the_workspace_to_a_dot_workspace_dir(
    qapp: QApplication, block_modals: list[Any], tmp_path: Path
) -> None:
    workspace = WorkspaceService()
    workspace.add_dataset(
        Dataset(
            name="root",
            dataframe=pd.DataFrame({"city": ["a", "b"], "n": [1, 2]}),
            source_format="csv",
            source_path=Path("/data/root.csv"),
        )
    )
    project = Project(name="p", path=tmp_path / "p.uads.json")
    controller, _dock, _bus = _make_controller(
        QMainWindow(), _FakeProjectService(project), workspace
    )

    controller.save_project()

    base = tmp_path / "p.workspace"
    assert (base / "workspace.db").is_file()
    assert list(base.glob("*.parquet"))
    assert block_modals == []


def test_save_project_no_longer_warns_about_derived_datasets(
    qapp: QApplication, block_modals: list[Any], tmp_path: Path
) -> None:
    """The milestone-19 warning is intentionally gone: 1.6 persists derived
    datasets in full to the workspace DB, so "were not saved" is false."""
    workspace = WorkspaceService()
    project = Project(name="p", path=tmp_path / "p.uads.json")
    service = _FakeProjectService(project, skipped_names=["Derived Dataset"])
    controller, _dock, _bus = _make_controller(QMainWindow(), service, workspace)

    controller.save_project()

    assert service.saved_projects == [project]
    assert block_modals == []


def test_save_project_warns_about_a_visualization_on_a_closed_dataset(
    qapp: QApplication, block_modals: list[Any], tmp_path: Path
) -> None:
    workspace = WorkspaceService()
    frame = pd.DataFrame({"city": ["a", "b", "a"]})
    dataset = Dataset(name="d", dataframe=frame, source_format="csv")
    workspace.add_dataset(dataset)
    viz = Visualization(
        name="v",
        dataset_id=dataset.dataset_id,
        figure=_bar_figure(frame),
        chart_type="bar",
        chart_parameters={"category_column": "city"},
    )
    workspace.add_visualization(viz)
    workspace.close_dataset(dataset.dataset_id)

    project = Project(name="p", path=tmp_path / "p.uads.json")
    controller, _dock, _bus = _make_controller(
        QMainWindow(), _FakeProjectService(project), workspace
    )

    controller.save_project()

    assert len(block_modals) == 1
    assert block_modals[0].kind == "warning"
    assert viz.visualization_id in block_modals[0].text


def test_open_project_restores_the_saved_workspace(
    qapp: QApplication, block_modals: list[Any], tmp_path: Path
) -> None:
    # --- controller 1 saves a workspace with a derived dataset + a viz ---
    saved_workspace = WorkspaceService()
    root_frame = pd.DataFrame({"city": ["a", "b", "c"], "n": [1, 2, 3]})
    root = Dataset(name="root", dataframe=root_frame, source_format="csv")
    saved_workspace.add_dataset(root)
    derived_frame = root_frame[root_frame["n"] > 1].reset_index(drop=True)
    derived = Dataset(
        name="derived",
        dataframe=derived_frame,
        source_format="csv",
        source_path=None,
        parent_dataset_id=root.dataset_id,
        derivation_description="n > 1",
    )
    saved_workspace.add_dataset(derived)
    viz = Visualization(
        name="v",
        dataset_id=derived.dataset_id,
        figure=_bar_figure(derived_frame),
        chart_type="bar",
        chart_parameters={"category_column": "city"},
    )
    saved_workspace.add_visualization(viz)

    project_path = tmp_path / "p.uads.json"
    saver, _d1, _b1 = _make_controller(
        QMainWindow(),
        _FakeProjectService(Project(name="p", path=project_path)),
        saved_workspace,
    )
    saver.save_project()
    assert (tmp_path / "p.workspace" / "workspace.db").is_file()

    # --- controller 2, fresh workspace, opens the same project ---
    fresh_workspace = WorkspaceService()
    opener, dock, state_bus = _make_controller(
        QMainWindow(), _FakeProjectService(None), fresh_workspace
    )

    opener.open_project_at_path(project_path)

    restored = {d.dataset_id: d for d in fresh_workspace.list_datasets()}
    assert set(restored) == {root.dataset_id, derived.dataset_id}
    assert restored[derived.dataset_id].parent_dataset_id == root.dataset_id
    assert restored[derived.dataset_id].dataframe.equals(derived_frame)
    assert [v.visualization_id for v in fresh_workspace.list_visualizations()] == [
        viz.visualization_id
    ]
    assert dock.refreshed_with  # Dataset Explorer refreshed
    assert state_bus.refresh_count >= 1
    assert block_modals == []


def test_open_project_without_a_workspace_dir_falls_back_without_crashing(
    qapp: QApplication, block_modals: list[Any], tmp_path: Path
) -> None:
    fresh_workspace = WorkspaceService()
    controller, _dock, _bus = _make_controller(
        QMainWindow(), _FakeProjectService(None), fresh_workspace
    )

    # No <stem>.workspace/ dir exists -> the legacy reader-reload path runs,
    # and _FakeProjectService.get_recorded_dataset_paths returns [] -> no-op.
    controller.open_project_at_path(tmp_path / "never_saved.uads.json")

    assert fresh_workspace.list_datasets() == []
    assert block_modals == []
