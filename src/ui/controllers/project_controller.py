# File: src/ui/controllers/project_controller.py
"""Owns every project-lifecycle handler: new/open/save/save-as, recent projects, dataset reload.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists and
why every method below is the same logic that used to live on
``MainWindow``, unchanged in behavior.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget

from src.core.exceptions import ApplicationError
from src.core.logger import get_logger
from src.readers.reader_registry import get_reader_for_path
from src.services.project_service import ProjectService
from src.services.workspace_service import WorkspaceService
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.worker_runner import WorkerRunner

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
        :class:`~src.services.workspace_service.Dataset` objects, and
        human-readable failure strings for recorded datasets that could not
        be reloaded (multi-table source, or a caught
        :class:`~src.core.exceptions.ApplicationError`) -- same
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
            :class:`~src.core.bootstrap.DependencyContainer`.
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
    """

    def __init__(
        self,
        parent: QWidget,
        project_service: ProjectService,
        workspace_service: WorkspaceService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        state_bus: UiStateBus,
        worker_runner: WorkerRunner,
        menu_bar: ApplicationMenuBar,
    ) -> None:
        self._parent = parent
        self._project_service = project_service
        self._workspace_service = workspace_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._state_bus = state_bus
        self._worker_runner = worker_runner
        self._menu_bar = menu_bar

    # -- Project actions --------------------------------------------------------

    def new_project(self) -> None:
        project = self._project_service.new_project("Untitled Project")
        self._status_bar.set_active_project_label(project.name)
        self._status_bar.show_message(f"Created new project: {project.name}")
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
        self._reload_project_datasets(project)

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

        skipped_names = self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )

        try:
            self._project_service.save_project(project)
        except ApplicationError as exc:
            QMessageBox.critical(self._parent, "Failed to Save Project", str(exc))
            _logger.warning("Failed to save project: %s", exc)
            return

        self._status_bar.show_message(f"Saved project: {project.name}")
        self._warn_about_skipped_datasets(skipped_names)

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

        skipped_names = self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )

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
        self._warn_about_skipped_datasets(skipped_names)

    def _warn_about_skipped_datasets(self, skipped_names: list[str]) -> None:
        """Surface :meth:`ProjectService.record_datasets`'s skipped-dataset names.

        Milestone 19: before this, ``record_datasets``'s return value
        (dataset names skipped because they have no ``source_path`` --
        derived datasets, not yet persistable per milestone 3a's own
        scope) was discarded entirely at both call sites -- a save that
        silently dropped a derived dataset from the project file gave the
        user no indication anything was left out. A warning-severity
        dialog (not critical): the save itself succeeded, this only names
        what could not be included in it.
        """
        if not skipped_names:
            return
        names_text = "\n".join(f"• {name}" for name in skipped_names)
        QMessageBox.warning(
            self._parent,
            "Some Datasets Were Not Saved",
            f"The project was saved, but the following dataset(s) could "
            f"not be included because they have no source file (they were "
            f"created by a cleaning operation or another in-app "
            f"transformation, not loaded from disk):\n\n{names_text}",
        )
