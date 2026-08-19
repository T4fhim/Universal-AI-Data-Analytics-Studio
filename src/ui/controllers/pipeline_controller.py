# File: src/ui/controllers/pipeline_controller.py
"""Owns the guided-pipeline workbench's business logic: propose, run, reproduce, persist.

New in milestone 20 -- see :mod:`src.ui.controllers`'s own docstring for why controllers exist
at all. Before this milestone, :class:`~src.services.analysis_orchestrator_service.
AnalysisOrchestratorService` was orphaned except ``get_log()`` (confirmed by grep against
``src/ui/`` at the time this overhaul's audit was written): ``propose_next_stage``,
``run_stage``, and ``reproduce`` were never called from anywhere a user could reach.
:meth:`PipelineController.run_understand_stage` is the first UI-driven call to ``run_stage``
this application has ever made.

Like every other milestone-19 controller, this one holds only the services/collaborators it
actually needs and is constructed once in ``MainWindow._build_controllers``. It also owns
``ProjectService.record_analysis_log``/``get_recorded_analysis_logs``'s only UI call sites
(:meth:`persist_all_logs`/:meth:`restore_logs_for_project`), wired into
:class:`~src.ui.controllers.project_controller.ProjectController`'s save/open flow via the same
callback-injection pattern :class:`~src.ui.controllers.database_controller.DatabaseController`
already uses for ``on_dataset_loaded`` -- ``ProjectController`` does not import this module (it
would have no reason to depend on the pipeline), it just calls whatever callable ``main_window.py``
handed it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox, QWidget

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import (
    AnalysisLog,
    AnalysisLogEntry,
    AnalysisOrchestratorService,
    PipelineStage,
    StageProposal,
)
from src.services.project_service import ProjectService
from src.services.workspace_service import Dataset, WorkspaceService
from src.ui.command_stack import CommandStack, DatasetPointerCommand
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner

if TYPE_CHECKING:
    from src.services.project_service import Project

_logger = get_logger(__name__)


class PipelineSnapshot:
    """The pipeline state for one dataset, as :meth:`PipelineController.snapshot_for_active_dataset`
    hands it to :class:`~src.ui.workbench.workbench.Workbench.update_pipeline_state`.

    A plain container rather than a ``dataclass`` purely to avoid this module needing a second
    import just for ``dataclass``/``field`` over three attributes with no defaults to manage.
    """

    def __init__(self, log: AnalysisLog, proposal: StageProposal) -> None:
        self.log = log
        self.proposal = proposal


class PipelineController:
    """Runs and tracks the guided pipeline for the active dataset.

    Args:
        parent: The window dialogs should be parented to.
        workspace_service: The active dataset is read from here.
        orchestrator_service: Does the actual propose/run/reproduce work.
        project_service: For recording/restoring each dataset's analysis log against the
            currently open project.
        dock_manager: For appending console messages.
        status_bar: For busy/message feedback.
        state_bus: Refreshed after a stage runs or a log is restored -- not because pipeline
            state affects any ``ActionSpec`` predicate today, but so any other listener
            (a future one) does not need this controller to grow a bespoke notification
            mechanism of its own.
        worker_runner: Runs :meth:`run_understand_stage`'s actual tool call off the UI
            thread -- ``profile_dataset`` iterates every column and is not guaranteed fast
            on a large dataset, matching why :class:`~src.ui.controllers.dataset_controller.
            DatasetController` offloads its own reads.
        command_stack: Milestone 23. Where :meth:`register_clean_operation` pushes a new
            undoable command and :meth:`undo`/:meth:`redo` replay one -- constructed once in
            ``main_window.py`` (not resolved from the ``DependencyContainer``; see
            :mod:`~src.ui.command_stack`'s own docstring for why) and handed to this
            controller since ``PipelineController`` already owns every other pipeline-shaped
            mutation of the active dataset (``run_understand_stage``, ``reproduce_active_dataset``).
        on_changed: Called after anything that could have changed the active dataset's
            pipeline state (a stage ran, a reproduction completed, logs were restored from a
            reopened project) -- typically
            :meth:`~src.ui.main_window.MainWindow._refresh_workbench`, which recomputes a
            fresh :class:`PipelineSnapshot` and pushes it into the workbench. Optional so a
            test can construct this controller without a real workbench to refresh.
    """

    def __init__(
        self,
        parent: QWidget,
        workspace_service: WorkspaceService,
        orchestrator_service: AnalysisOrchestratorService,
        project_service: ProjectService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        state_bus: UiStateBus,
        worker_runner: WorkerRunner,
        command_stack: CommandStack,
        on_changed: Callable[[], None] | None = None,
    ) -> None:
        self._parent = parent
        self._workspace_service = workspace_service
        self._orchestrator_service = orchestrator_service
        self._project_service = project_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._state_bus = state_bus
        self._worker_runner = worker_runner
        self._command_stack = command_stack
        self._on_changed = on_changed

    # -- Reading pipeline state --------------------------------------------------------

    def snapshot_for_active_dataset(self) -> PipelineSnapshot | None:
        """Return the active dataset's current log + proposal, or ``None`` if none is active."""
        dataset = self._workspace_service.get_active_dataset()
        if dataset is None:
            return None
        log = self._orchestrator_service.get_log(dataset.dataset_id)
        proposal = self._orchestrator_service.propose_next_stage(dataset.dataset_id)
        return PipelineSnapshot(log=log, proposal=proposal)

    # -- Running stages --------------------------------------------------------

    def run_understand_stage(self) -> None:
        """Run the UNDERSTAND stage (``profile_dataset``) against the active dataset.

        The first UI-driven call to
        :meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.run_stage`
        -- see this module's own docstring.
        """
        dataset = self._workspace_service.get_active_dataset()
        if dataset is None:
            QMessageBox.information(
                self._parent,
                "No Active Dataset",
                "Open or select a dataset before running the Understand stage.",
            )
            return

        dataset_id = dataset.dataset_id
        self._status_bar.show_busy("Profiling dataset…")
        self._worker_runner.run(
            self._orchestrator_service.run_stage,
            dataset_id,
            PipelineStage.UNDERSTAND,
            tool_name="profile_dataset",
            on_result=lambda entry: self._on_stage_run_completed(dataset_id, entry),
            on_error=self._on_stage_run_error,
            on_finished=self._status_bar.hide_busy,
        )

    def _on_stage_run_completed(self, dataset_id: str, entry: AnalysisLogEntry) -> None:
        self._dock_manager.append_console_message(
            f"Ran {entry.stage.value} stage"
            + (f" ({entry.tool_name})" if entry.tool_name else "")
            + "."
        )
        self._status_bar.show_message(f"{entry.stage.value.title()} stage complete.")
        _logger.info(
            "Pipeline stage run via UI: dataset=%s stage=%s tool=%s",
            dataset_id,
            entry.stage.value,
            entry.tool_name,
        )
        self._persist_log_if_project_open(dataset_id)
        self._state_bus.request_refresh()
        if self._on_changed is not None:
            self._on_changed()

    def _on_stage_run_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Pipeline stage run failed: %s\n%s", exc, traceback_text)
        self._dock_manager.append_console_message(f"⚠ Pipeline stage failed: {exc}")
        QMessageBox.critical(self._parent, "Stage Failed", str(exc))

    # -- Cleaning (milestone 23) --------------------------------------------------------

    def register_clean_operation(self, derived: Dataset) -> None:
        """Add a cleaning operation's result to the workspace and make it undoable.

        Connected to :attr:`~src.ui.workbench.pages.clean_page.CleanPage.operation_applied` in
        ``main_window.py``. ``derived`` has already been produced by
        :meth:`~src.cleaning.base_operation.BaseOperation.apply` by the time this runs (see
        ``CleanPage``'s own docstring for why the page computes it, not this controller) --
        this method's only job is bookkeeping: add it to the workspace, make it active, and
        push a :class:`~src.ui.command_stack.DatasetPointerCommand` so :meth:`undo` can move
        the active pointer back.
        """
        self._workspace_service.add_dataset(derived)
        self._workspace_service.set_active_dataset(derived.dataset_id)
        self._command_stack.push(
            DatasetPointerCommand(
                description=derived.derivation_description or "Cleaning operation",
                dataset_id=derived.dataset_id,
                parent_dataset_id=derived.parent_dataset_id,
            )
        )
        self._dock_manager.refresh_dataset_list(self._workspace_service.list_datasets())
        self._state_bus.request_refresh()  # has_active_dataset/can_undo both just changed
        self._status_bar.show_message(
            derived.derivation_description or f"Created dataset '{derived.name}'."
        )
        self._dock_manager.append_console_message(
            f"Cleaning: {derived.derivation_description or derived.name}"
        )
        if self._on_changed is not None:
            self._on_changed()

    def undo(self) -> None:
        """Move the active-dataset pointer back to the parent of the most recent operation.

        Never mutates any dataset's dataframe -- see
        :meth:`~src.ui.command_stack.CommandStack.undo`'s own docstring; this method is a thin
        UI-feedback wrapper around it (busy state is not needed here, unlike
        :meth:`run_understand_stage` -- moving a pointer is O(1), nothing to offload).
        """
        try:
            command = self._command_stack.undo()
        except ServiceError as exc:
            _logger.warning("Undo requested with nothing to undo: %s", exc)
            return
        self._status_bar.show_message(f"Undid: {command.description}")
        self._dock_manager.append_console_message(f"Undo: {command.description}")
        self._state_bus.request_refresh()
        if self._on_changed is not None:
            self._on_changed()

    def redo(self) -> None:
        """Move the active-dataset pointer forward to the most recently undone operation's result.

        See :meth:`undo`'s own docstring -- identical reasoning, opposite direction.
        """
        try:
            command = self._command_stack.redo()
        except ServiceError as exc:
            _logger.warning("Redo requested with nothing to redo: %s", exc)
            return
        self._status_bar.show_message(f"Redid: {command.description}")
        self._dock_manager.append_console_message(f"Redo: {command.description}")
        self._state_bus.request_refresh()
        if self._on_changed is not None:
            self._on_changed()

    # -- Reproducing --------------------------------------------------------

    def reproduce_active_dataset(self) -> None:
        """Replay every stage recorded for the active dataset.

        Synchronous, unlike :meth:`run_understand_stage` -- as of milestone 20 the only stage
        that can appear in a log at all is UNDERSTAND (a single, already-fast
        ``profile_dataset`` call), so offloading this to :attr:`_worker_runner` today would
        add ceremony with nothing behind it to justify it yet. Revisit once milestones 23-26
        add stages whose replay could genuinely be slow (CLEAN/ANALYZE/PREDICT).
        """
        dataset = self._workspace_service.get_active_dataset()
        if dataset is None:
            QMessageBox.information(
                self._parent,
                "No Active Dataset",
                "Open or select a dataset before reproducing its analysis log.",
            )
            return

        try:
            replayed = self._orchestrator_service.reproduce(dataset.dataset_id)
        except ServiceError as exc:
            QMessageBox.critical(self._parent, "Failed to Reproduce", str(exc))
            _logger.warning(
                "Reproduce failed for dataset %s: %s", dataset.dataset_id, exc
            )
            return

        self._dock_manager.append_console_message(
            f"Reproduced {len(replayed)} stage(s) for '{dataset.name}'."
        )
        self._status_bar.show_message(f"Reproduced {len(replayed)} stage(s).")
        self._persist_log_if_project_open(dataset.dataset_id)
        self._state_bus.request_refresh()
        if self._on_changed is not None:
            self._on_changed()

    # -- Persistence (ProjectService.record_analysis_log / get_recorded_analysis_logs) --------

    def _persist_log_if_project_open(self, dataset_id: str) -> None:
        project = self._project_service.get_active_project()
        if project is None:
            return  # nothing to persist into; the log still lives in the orchestrator
        log = self._orchestrator_service.get_log(dataset_id)
        self._project_service.record_analysis_log(project, dataset_id, log.to_dict())

    def persist_all_logs(self, project: Project) -> None:
        """Record every currently loaded dataset's analysis log into ``project``.

        Called by :class:`~src.ui.controllers.project_controller.ProjectController` just
        before it calls :meth:`~src.services.project_service.ProjectService.save_project`,
        via the ``on_before_save`` callback ``main_window.py`` wires -- see this module's own
        docstring for why the wiring is a callback rather than an import.
        """
        for dataset in self._workspace_service.list_datasets():
            log = self._orchestrator_service.get_log(dataset.dataset_id)
            if log.entries:  # skip datasets the pipeline has never touched
                self._project_service.record_analysis_log(
                    project, dataset.dataset_id, log.to_dict()
                )

    def restore_logs_for_project(self, project: Project) -> None:
        """Install every analysis log recorded in ``project`` into the orchestrator.

        Called by :class:`~src.ui.controllers.project_controller.ProjectController` right
        after it opens ``project``, via the ``on_project_opened`` callback -- this is what
        makes a dataset's pipeline history survive a save/reload cycle (milestone 20's
        round-trip acceptance criterion) rather than resetting to an empty log every time a
        project is reopened in a fresh session.
        """
        recorded = self._project_service.get_recorded_analysis_logs(project)
        for dataset_id, log_dict in recorded.items():
            self._orchestrator_service.load_log(AnalysisLog.from_dict(log_dict))
        if recorded:
            _logger.info(
                "Restored %d analysis log(s) from project '%s'.",
                len(recorded),
                project.name,
            )
        if self._on_changed is not None:
            self._on_changed()
