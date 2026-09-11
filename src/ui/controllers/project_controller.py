# File: src/ui/controllers/project_controller.py
"""Owns every project-lifecycle handler: new/open/save/save-as, recent projects, dataset reload.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists and
why every method below is the same logic that used to live on
``MainWindow``, unchanged in behavior.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner
from uadas_core.core.exceptions import ApplicationError
from uadas_core.core.logger import get_logger
from uadas_core.models import Project
from uadas_core.persistence.persistence_service import (
    PersistenceService,
    SaveReport,
    WorkspaceSnapshot,
)
from uadas_core.readers.reader_registry import get_reader_for_path
from uadas_core.services.project_service import ProjectService
from uadas_core.services.workspace_service import WorkspaceService

if TYPE_CHECKING:
    from src.ui.menu_bar import ApplicationMenuBar

_logger = get_logger(__name__)

_PROJECT_FILE_FILTER = "Universal AI Data Analytics Studio Project (*.uads.json)"


def _read_recorded_datasets(recorded: list[tuple[str, Path]]) -> tuple[list, list[str]]:
    """Read every ``(name, source_path)`` pair recorded in a project, off the UI thread.

    Module-level (not a :class:`ProjectController` method) and touches no
    Qt widgets or services deliberately -- this is the function
    :meth:`ProjectController._reload_project_datasets` hands to
    :class:`~src.ui.worker_runner.WorkerRunner`, and everything that runs on
    a worker thread must not touch ``self._workspace_service`` or any
    widget. Returns plain data; the caller applies it to the workspace back
    on the UI thread in :meth:`ProjectController._on_datasets_reloaded`.

    Returns:
        A ``(datasets, failures)`` tuple: successfully read
        :class:`~uadas_core.models.Dataset` objects, and
        human-readable failure strings for recorded datasets that could not
        be reloaded (multi-table source, or a caught
        :class:`~uadas_core.core.exceptions.ApplicationError`) -- same
        skip-with-a-warning behavior as before this milestone, just moved.
    """
    datasets = []
    failures: list[str] = []
    for name, source_path in recorded:
        try:
            reader_class = get_reader_for_path(source_path)
            available_tables = reader_class.list_tables(source_path)
            if len(available_tables) > 1:
                failures.append(
                    f"{name}: has multiple tables; re-open it manually "
                    f"via Open Dataset and select a table."
                )
                continue
            datasets.append(reader_class.read(source_path))
        except ApplicationError as exc:
            failures.append(f"{name}: {exc}")
            continue

    return datasets, failures


class ProjectController:
    """Handles project new/open/save/save-as and reloading a project's recorded datasets.

    Args:
        parent: The window dialogs (``QFileDialog``, ``QMessageBox``)
            should be parented to.
        project_service: Resolved from the shared
            :class:`~uadas_core.core.bootstrap.DependencyContainer`.
        workspace_service: Same -- datasets reloaded from a project are
            added here.
        dock_manager: For refreshing the Dataset Explorer and appending
            console messages after a reload.
        status_bar: For busy/progress/message feedback.
        state_bus: :meth:`~src.ui.ui_state_bus.UiStateBus.request_refresh`
            is called whenever ``has_project``/``has_active_dataset`` could
            have changed, matching the pre-milestone-19 behavior exactly.
        worker_runner: Runs the dataset-reload read off the UI thread.
        menu_bar: The "Open Recent" submenu is rebuilt here after any
            open/save-as that could have changed the recent-projects list.
        on_before_save: Milestone 20 -- called with the :class:`~uadas_core.services.project_service.
            Project` about to be saved, just before :meth:`~uadas_core.services.project_service.
            ProjectService.save_project` is called, so every loaded dataset's current analysis
            log gets recorded into the project's contents first. Typically
            :meth:`~src.ui.controllers.pipeline_controller.PipelineController.persist_all_logs`.
            This module deliberately does not import ``PipelineController`` to call it
            directly -- see :mod:`src.ui.controllers.pipeline_controller`'s own docstring on
            why this is a callback, matching how :class:`~src.ui.controllers.database_controller.
            DatabaseController` already receives ``on_dataset_loaded`` rather than importing
            :class:`~src.ui.controllers.dataset_controller.DatasetController`.
        on_project_opened: Milestone 20 -- called with the :class:`~uadas_core.services.project_service.
            Project` just opened, after every other post-open bookkeeping in
            :meth:`open_project_at_path` below, so recorded analysis logs are restored into the
            orchestrator. Typically :meth:`~src.ui.controllers.pipeline_controller.
            PipelineController.restore_logs_for_project`.
    """

    def __init__(
        self,
        parent: QWidget,
        project_service: ProjectService,
        workspace_service: WorkspaceService,
        persistence_service: PersistenceService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        state_bus: UiStateBus,
        worker_runner: WorkerRunner,
        menu_bar: ApplicationMenuBar,
        on_before_save: Callable[[Project], None] | None = None,
        on_project_opened: Callable[[Project], None] | None = None,
    ) -> None:
        self._parent = parent
        self._project_service = project_service
        self._workspace_service = workspace_service
        self._persistence_service = persistence_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._state_bus = state_bus
        self._worker_runner = worker_runner
        self._menu_bar = menu_bar
        self._on_before_save = on_before_save
        self._on_project_opened = on_project_opened

    # -- Project actions --------------------------------------------------------

    def new_project(self) -> None:
        """Create a fresh, empty project and make it active.

        Milestone-28 remediation: before this, the only feedback was a transient
        status-bar message plus a small status-bar label change -- both easy to miss
        entirely (no dialog, no page transition; the Welcome page correctly stays put
        since :meth:`~src.ui.workbench.workbench.Workbench.update_pipeline_state` only
        navigates off it once a *dataset* becomes active, not a project). A user's real
        log from this session showed exactly that confusion: seven "New Project"
        creations in about a minute, four of them within the same second -- consistent
        with rage-clicking a button that gave no visible confirmation it had worked.
        The console message below gives a second, persistent, more visible channel
        alongside the existing (still-kept) status-bar ones.
        """
        project = self._project_service.new_project("Untitled Project")
        self._status_bar.set_active_project_label(project.name)
        self._status_bar.show_message(f"Created new project: {project.name}")
        self._dock_manager.append_console_message(
            f"Created new project '{project.name}'. Use File > Open Dataset "
            f"to import your first file."
        )
        _logger.info("New project created via UI: %s", project.name)
        self._state_bus.request_refresh()  # has_project just became True

    def open_project(self) -> None:
        file_path_str, _selected_filter = QFileDialog.getOpenFileName(
            self._parent, "Open Project", "", _PROJECT_FILE_FILTER
        )
        if not file_path_str:
            return  # user cancelled the dialog
        self.open_project_at_path(Path(file_path_str))

    def open_recent_project(self, path_str: str) -> None:
        """Handler for a clicked "Open Recent" entry.

        Milestone 17: before this milestone, ``menu_bar.py`` built these
        entries with a target path stored via ``QAction.setData()`` but
        nothing ever connected a handler to them at all -- a real, visible,
        clickable menu item that did nothing when clicked, found by the
        audit behind this whole overhaul. ``menu_bar.py``'s
        ``update_recent_projects_menu`` now wires each entry's
        ``triggered`` signal directly to this method.
        """
        self.open_project_at_path(Path(path_str))

    def open_project_at_path(self, path: Path) -> None:
        """Shared "open a project file and reload its datasets" logic.

        Used by both :meth:`open_project` (path chosen via a file dialog)
        and :meth:`open_recent_project` (path chosen from the "Open
        Recent" submenu) -- the two differ only in how ``path`` is
        obtained, not in what happens once it is.
        """
        try:
            project = self._project_service.open_project(path)
        except ApplicationError as exc:
            QMessageBox.critical(self._parent, "Failed to Open Project", str(exc))
            _logger.warning("Failed to open project from %s: %s", path, exc)
            return

        self._status_bar.set_active_project_label(project.name)
        self._status_bar.show_message(f"Opened project: {project.name}")
        self._menu_bar.update_recent_projects_menu(
            self._project_service.get_recent_projects(),
            on_open=self.open_recent_project,
        )
        self._state_bus.request_refresh()  # has_project just became True

        # Web-transition 1.6: a project saved by 1.6+ has a <stem>.workspace/
        # directory holding the full workspace (derived datasets, visualizations,
        # dashboards). Restore from it and skip the legacy reader-reload -- running
        # both would produce duplicate root datasets with different ids. A project
        # saved before 1.6 has no such directory; fall back to re-reading each
        # recorded source file as before.
        if self._workspace_base(project).is_dir():
            self._status_bar.show_busy("Restoring workspace…")
            self._worker_runner.run(
                self._persistence_service.load_workspace,
                self._workspace_base(project),
                on_result=self._on_workspace_loaded,
                on_error=self._on_workspace_load_error,
                on_finished=self._status_bar.hide_busy,
            )
        else:
            self._reload_project_datasets(project)

        if self._on_project_opened is not None:
            self._on_project_opened(project)

    def _reload_project_datasets(self, project) -> None:
        """Re-read every dataset recorded in ``project`` and load it into the workspace.

        Uses the same read-through-the-registry, add-to-workspace,
        refresh-the-dock sequence as the dataset-open path, since reloading
        a project's datasets is functionally the same operation (populate
        the workspace from a file on disk) repeated once per recorded
        dataset -- multi-table sources are not supported here (a saved
        project records only a name and path, not which table was
        selected within a multi-table source at the time it was originally
        loaded), so any recorded dataset that turns out to need a table
        selection is skipped with a warning rather than guessed at.

        Milestone 6: the actual per-file reading (``_read_recorded_datasets``)
        runs on a worker thread rather than blocking the UI thread for
        however long every recorded dataset takes to re-read -- this was
        one of the two hot spots the milestone plan named explicitly. The
        worker function only reads files and returns plain data; mutating
        ``self._workspace_service`` happens back on the UI thread in
        :meth:`_on_datasets_reloaded`, since ``WorkspaceService`` is not
        documented or verified as thread-safe and every other consumer
        only ever touches it from the UI thread.
        """
        recorded = self._project_service.get_recorded_dataset_paths(project)
        if not recorded:
            return

        self._status_bar.show_busy(f"Reloading {len(recorded)} dataset(s)…")
        self._worker_runner.run(
            _read_recorded_datasets,
            recorded,
            on_result=self._on_datasets_reloaded,
            on_error=self._on_datasets_reload_error,
            # Milestone 17: status_bar.show_progress exists and every
            # worker's progress signal is now connected to it, even though
            # _read_recorded_datasets does not itself accept a
            # progress_callback yet -- see ApplicationStatusBar.
            # show_progress's own docstring for why that is deliberate,
            # incremental wiring rather than dead code.
            on_progress=self._status_bar.show_progress,
            on_finished=self._status_bar.hide_busy,
        )

    def _on_datasets_reloaded(self, result: tuple[list, list[str]]) -> None:
        """Apply the datasets read by :func:`_read_recorded_datasets` to the workspace.

        Runs on the UI thread (connected to ``BaseWorker.signals.result``,
        which Qt's queued-connection default delivers on the receiver's
        thread) so ``WorkspaceService`` mutation and dock refresh stay off
        the worker thread.
        """
        datasets, failures = result
        for dataset in datasets:
            self._workspace_service.add_dataset(dataset)

        self._dock_manager.refresh_dataset_list(self._workspace_service.list_datasets())
        self._dock_manager.append_console_message(
            f"Reloaded {len(datasets)} dataset(s) from project"
            + (f"; {len(failures)} failed." if failures else ".")
        )

        if failures:
            failures_text = "\n".join(f"• {f}" for f in failures)
            QMessageBox.warning(
                self._parent,
                "Some Datasets Could Not Be Reloaded",
                f"The project opened, but the following recorded "
                f"dataset(s) could not be automatically reloaded:\n\n"
                f"{failures_text}",
            )

    def _on_datasets_reload_error(self, exc: Exception, traceback_text: str) -> None:
        # _read_recorded_datasets already catches ApplicationError per
        # dataset internally (see its own docstring) -- reaching this
        # handler means something unexpected escaped that loop entirely,
        # not a normal per-dataset failure.
        _logger.error(
            "Unexpected failure reloading project datasets: %s\n%s", exc, traceback_text
        )
        QMessageBox.critical(
            self._parent,
            "Failed to Reload Datasets",
            f"An unexpected error occurred while reloading the project's datasets: {exc}",
        )

    def save_project(self) -> None:
        project = self._project_service.get_active_project()
        if project is None:
            self._status_bar.show_message("No project is open to save.")
            return

        if project.path is None:
            self.save_project_as()
            return

        # record_datasets still writes the legacy {name, source_path} list into
        # the .uads.json (the pre-1.6 fallback open path uses it), but its
        # return value -- derived datasets it could not record -- is no longer
        # surfaced: web-transition 1.6 persists exactly those to
        # <project>.workspace/ via _persist_workspace below.
        self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )
        if self._on_before_save is not None:
            self._on_before_save(project)

        try:
            self._project_service.save_project(project)
        except ApplicationError as exc:
            QMessageBox.critical(self._parent, "Failed to Save Project", str(exc))
            _logger.warning("Failed to save project: %s", exc)
            return

        self._status_bar.show_message(f"Saved project: {project.name}")
        self._persist_workspace(project)

    def save_project_as(self) -> None:
        project = self._project_service.get_active_project()
        if project is None:
            self._status_bar.show_message("No project is open to save.")
            return

        file_path_str, _selected_filter = QFileDialog.getSaveFileName(
            self._parent,
            "Save Project As",
            f"{project.name}.uads.json",
            _PROJECT_FILE_FILTER,
        )
        if not file_path_str:
            return  # user cancelled the dialog

        # See save_project: record_datasets still populates the .uads.json list
        # for the fallback open path; its skipped-derived-datasets return is not
        # surfaced because _persist_workspace persists those to the workspace DB.
        self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )
        if self._on_before_save is not None:
            self._on_before_save(project)

        try:
            self._project_service.save_project(project, Path(file_path_str))
        except ApplicationError as exc:
            QMessageBox.critical(self._parent, "Failed to Save Project", str(exc))
            _logger.warning("Failed to save project as %s: %s", file_path_str, exc)
            return

        self._status_bar.show_message(f"Saved project: {project.name}")
        self._menu_bar.update_recent_projects_menu(
            self._project_service.get_recent_projects(),
            on_open=self.open_recent_project,
        )
        self._persist_workspace(project)

    # -- Workspace persistence (web-transition 1.6) --------------------------
    #
    # Milestone 19 added ``_warn_about_skipped_datasets`` here, which surfaced
    # ``record_datasets``'s return value -- derived (source-file-less) datasets
    # it could not record into the ``.uads.json``. Web-transition 1.6 removed
    # that warning: those datasets are now persisted in full to
    # ``<project>.workspace/`` by :meth:`_persist_workspace`, so "were not saved"
    # is no longer true. ``_warn_about_skipped_visualizations`` below is its
    # 1.6 counterpart, for the one thing a full-replace save genuinely drops.

    def _workspace_base(self, project: Project) -> Path:
        """Return the ``<project-stem>.workspace/`` directory beside ``project.path``.

        The persistence layer's per-project store (SQLite ``workspace.db`` +
        ``<dataset_id>.parquet`` frames). ``project.path`` is always set by the time
        this is called -- both save paths route a path-less project through Save-As
        first, and open only reaches here after a successful ``open_project``.
        ``.uads.json`` is stripped if present, else the whole file name is used, so
        ``foo.json`` deterministically yields ``foo.json.workspace`` (see
        ``plans/phase-1-6-persistence-contract.md`` §5.1).
        """
        assert project.path is not None  # documented precondition, above
        name = project.path.name
        stem = name[: -len(".uads.json")] if name.endswith(".uads.json") else name
        return project.path.parent / f"{stem}.workspace"

    def _persist_workspace(self, project: Project) -> None:
        """Persist the full workspace to ``<project>.workspace/`` on a worker thread.

        Web-transition 1.6. Runs after ``ProjectService.save_project`` has written the
        ``.uads.json``. The dataset / visualization / dashboard lists are snapshotted
        here on the UI thread and handed to ``PersistenceService.save_workspace`` as
        plain data -- the worker never touches the live, non-thread-safe
        ``WorkspaceService``, mirroring ``_reload_project_datasets``'s own split.
        """
        base = self._workspace_base(project)
        self._status_bar.show_busy("Saving workspace…")
        self._worker_runner.run(
            self._persistence_service.save_workspace,
            self._workspace_service.list_datasets(),
            self._workspace_service.list_visualizations(),
            self._workspace_service.list_dashboards(),
            base,
            on_result=self._on_workspace_saved,
            on_error=self._on_workspace_save_error,
            on_finished=self._status_bar.hide_busy,
        )

    def _on_workspace_saved(self, report: SaveReport) -> None:
        """UI-thread handler for a completed ``save_workspace``."""
        self._warn_about_skipped_visualizations(report.skipped_visualization_ids)

    def _on_workspace_save_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Failed to persist workspace: %s\n%s", exc, traceback_text)
        QMessageBox.critical(
            self._parent,
            "Failed to Save Workspace",
            f"The project file was saved, but its workspace data (datasets, "
            f"visualizations, dashboards) could not be written: {exc}",
        )

    def _warn_about_skipped_visualizations(self, skipped_ids: list[str]) -> None:
        """Surface visualizations ``save_workspace`` could not persist.

        A visualization whose dataset has been closed has no frame to save from, so it
        is skipped (``plans/phase-1-6-persistence-contract.md`` §2.4). Warning, not
        critical: the save itself succeeded. Because save is full-replace, such a
        visualization is gone on the next save -- worth telling the user. This is the
        1.6 counterpart of the milestone-19 skipped-datasets warning that 1.6 removed
        (see the section comment above).
        """
        if not skipped_ids:
            return
        ids_text = "\n".join(f"• {vid}" for vid in skipped_ids)
        QMessageBox.warning(
            self._parent,
            "Some Visualizations Were Not Saved",
            f"The project was saved, but the following visualization(s) could "
            f"not be included because the dataset they chart has been "
            f"closed:\n\n{ids_text}",
        )

    def _on_workspace_loaded(self, snapshot: WorkspaceSnapshot) -> None:
        """UI-thread handler for a completed ``load_workspace``: install the snapshot.

        Runs on the UI thread (queued signal), so mutating ``WorkspaceService`` via
        :meth:`~uadas_core.services.workspace_service.WorkspaceService.load_snapshot`
        and refreshing the docks is safe here -- the same UI-thread/worker-thread
        split as :meth:`_on_datasets_reloaded`.
        """
        self._workspace_service.load_snapshot(
            snapshot.datasets, snapshot.visualizations, snapshot.dashboards
        )
        self._dock_manager.refresh_dataset_list(self._workspace_service.list_datasets())
        self._state_bus.request_refresh()
        self._dock_manager.append_console_message(
            f"Restored workspace: {len(snapshot.datasets)} dataset(s), "
            f"{len(snapshot.visualizations)} visualization(s), "
            f"{len(snapshot.dashboards)} dashboard(s)"
            + (
                f"; {len(snapshot.rebuild_failures)} visualization(s) could not "
                f"be rebuilt."
                if snapshot.rebuild_failures
                else "."
            )
        )
        if snapshot.rebuild_failures:
            failures_text = "\n".join(f"• {vid}" for vid in snapshot.rebuild_failures)
            QMessageBox.warning(
                self._parent,
                "Some Visualizations Could Not Be Restored",
                f"The project's workspace was restored, but the following "
                f"visualization(s) could not be rebuilt (their chart type or a "
                f"column they use is no longer available):\n\n{failures_text}",
            )

    def _on_workspace_load_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Failed to restore workspace: %s\n%s", exc, traceback_text)
        QMessageBox.critical(
            self._parent,
            "Failed to Restore Workspace",
            f"The project opened, but its saved workspace data could not be "
            f"restored: {exc}",
        )
