# File: tests/ui/controllers/test_pipeline_controller.py
"""Tests for PipelineController: the milestone-20 UI wiring of AnalysisOrchestratorService.

Backs milestone 20's acceptance criteria:
3. Clicking "Run" on the Understand stage page calls ``run_stage(..., tool_name=
   "profile_dataset")`` and a real ``AnalysisLogEntry`` appears afterward -- see
   :func:`test_run_understand_stage_runs_profile_dataset_and_records_a_real_log_entry`. That
   this is the first UI-driven call to ``run_stage`` ever is a repo-history fact (confirmed
   separately by grepping ``src/ui/`` before this milestone -- see the plan document's own
   Context section, which found only ``get_log()`` called), not something a single test run can
   itself prove; :meth:`~src.ui.controllers.pipeline_controller.PipelineController.
   run_understand_stage` is the only call site this milestone adds.
4. Closing and reopening a project preserves the analysis log -- a real round-trip against a
   real ``tmp_path`` project file (see ``tests/services/test_project_service_analysis_log.py``
   for the pure-service-layer version; this file additionally covers the controller-level
   persist/restore wiring with real services).

Uses real :class:`~src.services.workspace_service.WorkspaceService`,
:class:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService`, and
:class:`~src.services.project_service.ProjectService` instances (not mocks) -- the same
"duck-typed fakes only for Qt-adjacent collaborators, real services for the actual business
logic under test" split ``tests/ui/controllers/test_project_controller.py`` established.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import QApplication, QMainWindow

from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.project_service import ProjectService
from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.controllers.pipeline_controller import PipelineController
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner
from tests.ui.qt_helpers import wait_for_signal


def _make_dataset() -> Dataset:
    frame = pd.DataFrame({"a": [1, 2, 3], "b": ["x", "y", None]})
    return Dataset(name="test", dataframe=frame, source_format="csv")


def _make_controller(
    qapp: QApplication, workspace_service: WorkspaceService | None = None
) -> tuple[
    PipelineController, WorkspaceService, AnalysisOrchestratorService, ProjectService
]:
    workspace_service = workspace_service or WorkspaceService()
    orchestrator_service = AnalysisOrchestratorService(workspace_service)
    project_service = ProjectService()
    window = QMainWindow()
    dock_manager = DockManager(window)
    status_bar = ApplicationStatusBar(window)
    state_bus = UiStateBus(window)
    worker_runner = WorkerRunner(window)

    controller = PipelineController(
        window,
        workspace_service,
        orchestrator_service,
        project_service,
        dock_manager,
        status_bar,
        state_bus,
        worker_runner,
    )
    return controller, workspace_service, orchestrator_service, project_service


def test_run_understand_stage_runs_profile_dataset_and_records_a_real_log_entry(
    qapp: QApplication, block_modals
) -> None:
    controller, workspace_service, orchestrator_service, _ = _make_controller(qapp)
    dataset = _make_dataset()
    workspace_service.add_dataset(dataset)
    workspace_service.set_active_dataset(dataset.dataset_id)

    completed_signal_holder: list = []
    original_run = controller._worker_runner.run

    def _capturing_run(*args, **kwargs):
        worker = original_run(*args, **kwargs)
        completed_signal_holder.append(worker)
        return worker

    controller._worker_runner.run = _capturing_run  # type: ignore[method-assign]

    controller.run_understand_stage()
    wait_for_signal(completed_signal_holder[0].signals.finished)

    log = orchestrator_service.get_log(dataset.dataset_id)
    assert len(log.entries) == 1
    entry = log.entries[0]
    assert entry.stage == PipelineStage.UNDERSTAND
    assert entry.tool_name == "profile_dataset"
    assert entry.outputs["row_count"] == 3
    assert not block_modals  # no error dialog was shown


def test_run_understand_stage_with_no_active_dataset_shows_a_message_not_a_crash(
    qapp: QApplication, block_modals
) -> None:
    controller, _workspace_service, _orchestrator_service, _ = _make_controller(qapp)

    controller.run_understand_stage()

    assert len(block_modals) == 1
    assert block_modals[0].kind == "information"


def test_persist_all_logs_writes_only_datasets_with_entries(qapp: QApplication) -> None:
    controller, workspace_service, orchestrator_service, project_service = (
        _make_controller(qapp)
    )
    dataset = _make_dataset()
    workspace_service.add_dataset(dataset)
    untouched_dataset = _make_dataset()
    workspace_service.add_dataset(untouched_dataset)
    orchestrator_service.run_stage(
        dataset.dataset_id, PipelineStage.UNDERSTAND, tool_name="profile_dataset"
    )
    project = project_service.new_project("Test Project")

    controller.persist_all_logs(project)

    recorded = project_service.get_recorded_analysis_logs(project)
    assert dataset.dataset_id in recorded
    assert untouched_dataset.dataset_id not in recorded


def test_restore_logs_for_project_installs_logs_into_the_orchestrator(
    qapp: QApplication,
) -> None:
    controller, workspace_service, orchestrator_service, project_service = (
        _make_controller(qapp)
    )
    dataset = _make_dataset()
    workspace_service.add_dataset(dataset)
    orchestrator_service.run_stage(
        dataset.dataset_id, PipelineStage.UNDERSTAND, tool_name="profile_dataset"
    )
    project = project_service.new_project("Test Project")
    controller.persist_all_logs(project)

    # A fresh orchestrator, as if the app had been restarted -- the log
    # must come back from project.contents, not from any in-memory state.
    fresh_orchestrator = AnalysisOrchestratorService(workspace_service)
    fresh_controller = PipelineController(
        controller._parent,
        workspace_service,
        fresh_orchestrator,
        project_service,
        controller._dock_manager,
        controller._status_bar,
        controller._state_bus,
        controller._worker_runner,
    )
    assert fresh_orchestrator.get_log(dataset.dataset_id).entries == []

    fresh_controller.restore_logs_for_project(project)

    restored_log = fresh_orchestrator.get_log(dataset.dataset_id)
    assert len(restored_log.entries) == 1
    assert restored_log.entries[0].stage == PipelineStage.UNDERSTAND


def test_round_trip_through_a_real_project_file_preserves_the_analysis_log(
    qapp: QApplication, tmp_path
) -> None:
    """The full acceptance-criterion-4 path: save to a real file, reopen it, restore the log."""
    controller, workspace_service, orchestrator_service, project_service = (
        _make_controller(qapp)
    )
    dataset = _make_dataset()
    workspace_service.add_dataset(dataset)
    orchestrator_service.run_stage(
        dataset.dataset_id, PipelineStage.UNDERSTAND, tool_name="profile_dataset"
    )
    project = project_service.new_project("Round Trip Project")
    controller.persist_all_logs(project)
    project_path = tmp_path / "round_trip.uads.json"
    project_service.save_project(project, project_path)

    # Simulate closing and reopening: a fresh ProjectService/orchestrator,
    # nothing in memory carried over except the file on disk.
    reopened_project_service = ProjectService()
    reopened_project = reopened_project_service.open_project(project_path)
    fresh_orchestrator = AnalysisOrchestratorService(workspace_service)
    fresh_controller = PipelineController(
        controller._parent,
        workspace_service,
        fresh_orchestrator,
        reopened_project_service,
        controller._dock_manager,
        controller._status_bar,
        controller._state_bus,
        controller._worker_runner,
    )

    fresh_controller.restore_logs_for_project(reopened_project)

    restored_log = fresh_orchestrator.get_log(dataset.dataset_id)
    assert len(restored_log.entries) == 1
    assert restored_log.entries[0].tool_name == "profile_dataset"
    assert restored_log.entries[0].outputs["row_count"] == 3
