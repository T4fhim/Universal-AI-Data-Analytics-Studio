# File: src/ui/main_window.py
"""The application's main window.

:class:`MainWindow` assembles every piece built in milestone 1b-ii —
menu bar, toolbar, status bar, dock manager, theme manager, and the
welcome widget as initial central content — and wires the menu/toolbar
actions to real calls against the services resolved from the
dependency container (``SettingsService``, ``ProjectService``,
``WorkspaceService``, all registered in :mod:`src.core.bootstrap`).

This class does not construct its own service instances. It receives
the :class:`~src.core.bootstrap.BootstrapContext` and resolves what it
needs from ``context.container`` — the same container every other part
of the running application resolves from — so that, for example, a
project opened through this window's File > Open action updates the
one ``ProjectService`` instance the rest of the application shares,
rather than a private instance only this window would know about.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
)

from src.ai.assistant_service import AssistantService, AssistantTurnResult
from src.core.bootstrap import BootstrapContext
from src.core.constants import APP_NAME, DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH
from src.core.exceptions import ApplicationError, ServiceError
from src.core.logger import get_logger
from src.plugins.plugin_manager import PluginManager
from src.readers.reader_registry import get_reader_for_path
from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.database_connection_service import DatabaseConnectionService
from src.services.project_service import ProjectService
from src.services.report_service import ReportService
from src.services.settings_service import SettingsService
from src.services.workspace_service import (
    Dashboard,
    DashboardTile,
    Visualization,
    WorkspaceService,
)
from src.ui.dialogs.about_dialog import AboutDialog
from src.ui.dialogs.connect_database_dialog import ConnectDatabaseDialog
from src.ui.dialogs.create_visualization_dialog import CreateVisualizationDialog
from src.ui.dialogs.generate_report_dialog import GenerateReportDialog
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.dock_manager import DockManager
from src.ui.menu_bar import ApplicationMenuBar
from src.ui.status_bar import ApplicationStatusBar
from src.ui.theme_manager import ThemeManager
from src.ui.toolbar import ApplicationToolBar
from src.ui.widgets.welcome_widget import WelcomeWidget
from src.visualization.dashboard_renderer import render_dashboard
from src.workers import BaseWorker

_logger = get_logger(__name__)

_PROJECT_FILE_FILTER = "Universal AI Data Analytics Studio Project (*.uads.json)"

# Mirrors the extensions each reader in src.readers declares via its
# own SUPPORTED_EXTENSIONS class attribute (see
# src.readers.base_reader.BaseReader). Not built dynamically from
# those attributes at import time — Qt's file-dialog filter syntax
# groups extensions under one human-readable label per format, which
# doesn't map cleanly onto a flat set union the way
# reader_registry.get_reader_for_path's own error-message construction
# does; a hardcoded filter string here is clearer than deriving one
# generically. Extended in milestone 2b to include Excel and SQLite
# alongside 2a's original three formats, and again in milestone 14 to
# include ODS/YAML/Parquet/Feather/PowerPoint/HTML/ZIP-GZIP — this
# constant needs a manual update whenever a new reader is added to
# src.readers, since nothing enforces the two staying in sync
# automatically.
_DATASET_FILE_FILTER = (
    "All Supported Datasets (*.csv *.tsv *.json *.txt *.xlsx *.xls "
    "*.db *.sqlite *.sqlite3 *.pdf *.docx *.xml *.png *.jpg *.jpeg "
    "*.bmp *.tiff *.tif *.ods *.yaml *.yml *.parquet *.feather *.pptx "
    "*.html *.htm *.zip *.gz *.gzip);;"
    "CSV Files (*.csv *.tsv);;"
    "JSON Files (*.json);;"
    "Text Files (*.txt);;"
    "Excel Files (*.xlsx *.xls);;"
    "SQLite Databases (*.db *.sqlite *.sqlite3);;"
    "PDF Files (*.pdf);;"
    "Word Documents (*.docx);;"
    "XML Files (*.xml);;"
    "Images (*.png *.jpg *.jpeg *.bmp *.tiff *.tif);;"
    "OpenDocument Spreadsheets (*.ods);;"
    "YAML Files (*.yaml *.yml);;"
    "Parquet Files (*.parquet);;"
    "Feather Files (*.feather);;"
    "PowerPoint Presentations (*.pptx);;"
    "HTML Files (*.html *.htm);;"
    "Archives (*.zip *.gz *.gzip)"
)

# Sentinel distinct from None: None is already a legitimate return
# value from _resolve_table_name (meaning "single-table file, no
# selection was needed"), so the user cancelling the table-picker
# dialog needs its own, different marker — conflating the two would
# mean a cancelled dialog silently proceeds as if the file only had
# one table, which is a real, distinct bug from simply not offering a
# picker at all.
_TABLE_SELECTION_CANCELLED = object()

# A second, separately distinct sentinel: zero tables available at
# all. Added in milestone 2c-i, when PDF and Word readers introduced a
# case 2a/2b's readers never faced — a genuinely valid, unremarkable
# document (a text-only PDF; a Word doc with no tables) that simply
# has nothing tabular in it. This is not an error (the document isn't
# malformed) and it is not the same as "exactly one table" (there is
# nothing to read at all) — see
# src.readers.base_reader.BaseReader.list_tables's own docstring for
# how readers report this, and _resolve_table_name below for how the
# UI distinguishes it from both None and cancellation.
_NO_TABLES_AVAILABLE = object()


def _read_recorded_datasets(recorded: list[tuple[str, Path]]) -> tuple[list, list[str]]:
    """Read every ``(name, source_path)`` pair recorded in a project, off the UI thread.

    Module-level (not a ``MainWindow`` method) and touches no Qt
    widgets or services deliberately — this is the function
    :meth:`MainWindow._reload_project_datasets` hands to a
    :class:`~src.workers.BaseWorker`, and everything a ``BaseWorker``
    runs executes on a background thread where touching
    ``self._workspace_service`` or any widget would be unsafe. Returns
    plain data; the caller applies it to the workspace back on the UI
    thread in :meth:`MainWindow._on_datasets_reloaded`.

    Returns:
        A ``(datasets, failures)`` tuple: successfully read
        :class:`~src.services.workspace_service.Dataset` objects, and
        human-readable failure strings for recorded datasets that
        could not be reloaded (multi-table source, or a caught
        :class:`~src.core.exceptions.ApplicationError`) — same
        skip-with-a-warning behavior as before this milestone, just
        computed on a worker thread instead of the UI thread.
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


class MainWindow(QMainWindow):
    """The application's main window.

    Args:
        context: The result of a successful
            :func:`~src.core.bootstrap.bootstrap` call. Services this
            window needs (``SettingsService``, ``ProjectService``,
            ``WorkspaceService``) are resolved from
            ``context.container`` during construction, and
            ``ThemeManager`` is constructed fresh here (it wraps the
            live ``QApplication`` instance, which does not exist until
            :mod:`src.core.app` constructs it — see that module's
            extended ``run()`` for where this window is built).
    """

    def __init__(self, context: BootstrapContext) -> None:
        super().__init__()
        self._context = context
        self._settings_service = context.container.resolve(SettingsService)
        self._project_service = context.container.resolve(ProjectService)
        self._workspace_service = context.container.resolve(WorkspaceService)
        self._plugin_manager = context.container.resolve(PluginManager)
        self._orchestrator_service = context.container.resolve(
            AnalysisOrchestratorService
        )
        self._report_service = context.container.resolve(ReportService)
        self._database_service = context.container.resolve(DatabaseConnectionService)
        # Constructed lazily on first chat message, not here — building
        # it eagerly would mean every window construction (including
        # ones where the user never opens the AI panel) pays the cost
        # of resolving provider profiles and would show a "no provider
        # configured" error before the user has done anything. See
        # _get_or_build_assistant_service.
        self._assistant_service: AssistantService | None = None

        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

        self._menu_bar = ApplicationMenuBar(self)
        self.setMenuBar(self._menu_bar)

        self._tool_bar = ApplicationToolBar(self, self._menu_bar)
        self.addToolBar(self._tool_bar)

        self._status_bar = ApplicationStatusBar(self)
        self.setStatusBar(self._status_bar)

        self._dock_manager = DockManager(self)
        self._populate_view_menu()

        self._welcome_widget = WelcomeWidget(self)
        self.setCentralWidget(self._welcome_widget)

        self._connect_actions()
        self._menu_bar.update_recent_projects_menu(
            self._project_service.get_recent_projects()
        )

        _logger.info("Main window constructed.")

    # -- Setup helpers --------------------------------------------------------

    def _populate_view_menu(self) -> None:
        for toggle_action in self._dock_manager.view_menu_toggle_actions():
            self._menu_bar.menu_view.addAction(toggle_action)

    def _connect_actions(self) -> None:
        self._menu_bar.action_new_project.triggered.connect(self._on_new_project)
        self._menu_bar.action_open_project.triggered.connect(self._on_open_project)
        self._menu_bar.action_open_dataset.triggered.connect(self._on_open_dataset)
        self._menu_bar.action_connect_database.triggered.connect(
            self._on_connect_database
        )
        self._menu_bar.action_create_visualization.triggered.connect(
            self._on_create_visualization
        )
        self._menu_bar.action_create_dashboard.triggered.connect(
            self._on_create_dashboard
        )
        self._menu_bar.action_generate_report.triggered.connect(
            self._on_generate_report
        )
        self._menu_bar.action_save_project.triggered.connect(self._on_save_project)
        self._menu_bar.action_save_project_as.triggered.connect(
            self._on_save_project_as
        )
        self._menu_bar.action_settings.triggered.connect(self._on_open_settings)
        self._menu_bar.action_exit.triggered.connect(self.close)
        self._menu_bar.action_toggle_theme.triggered.connect(self._on_toggle_theme)
        self._menu_bar.action_about.triggered.connect(self._on_open_about)

        self._welcome_widget.button_new_project.clicked.connect(self._on_new_project)
        self._welcome_widget.button_open_project.clicked.connect(self._on_open_project)

        self._dock_manager.chat_panel.send_button.clicked.connect(
            self._on_send_chat_message
        )

    # -- Project actions --------------------------------------------------------

    def _on_new_project(self) -> None:
        project = self._project_service.new_project("Untitled Project")
        self._status_bar.set_active_project_label(project.name)
        self._status_bar.show_message(f"Created new project: {project.name}")
        _logger.info("New project created via UI: %s", project.name)

    def _on_open_project(self) -> None:
        file_path_str, _selected_filter = QFileDialog.getOpenFileName(
            self, "Open Project", "", _PROJECT_FILE_FILTER
        )
        if not file_path_str:
            return  # user cancelled the dialog

        try:
            project = self._project_service.open_project(Path(file_path_str))
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Open Project", str(exc))
            _logger.warning("Failed to open project from %s: %s", file_path_str, exc)
            return

        self._status_bar.set_active_project_label(project.name)
        self._status_bar.show_message(f"Opened project: {project.name}")
        self._menu_bar.update_recent_projects_menu(
            self._project_service.get_recent_projects()
        )
        self._reload_project_datasets(project)

    def _reload_project_datasets(self, project) -> None:
        """Re-read every dataset recorded in ``project`` and load it into the workspace.

        Uses the same read-through-the-registry, add-to-workspace,
        refresh-the-dock sequence as
        :meth:`_on_open_dataset`'s successful path, since reloading a
        project's datasets is functionally the same operation
        (populate the workspace from a file on disk) repeated once per
        recorded dataset — multi-table sources are not supported here
        (a saved project records only a name and path, not which
        table was selected within a multi-table source at the time it
        was originally loaded), so any recorded dataset that turns out
        to need a table selection is skipped with a warning rather
        than guessed at.

        Milestone 6: the actual per-file reading (``_read_recorded_datasets``)
        runs on a :class:`~src.workers.BaseWorker` thread rather than
        blocking the UI thread for however long every recorded dataset
        takes to re-read — this was one of the two hot spots the
        milestone plan named explicitly. The worker function only reads
        files and returns plain data; mutating ``self._workspace_service``
        happens back on the UI thread in :meth:`_on_datasets_reloaded`,
        since ``WorkspaceService`` is not documented or verified as
        thread-safe and every other consumer only ever touches it from
        the UI thread.
        """
        recorded = self._project_service.get_recorded_dataset_paths(project)
        if not recorded:
            return

        self._status_bar.show_busy(f"Reloading {len(recorded)} dataset(s)…")
        worker = BaseWorker(_read_recorded_datasets, recorded)
        worker.signals.result.connect(self._on_datasets_reloaded)
        worker.signals.error.connect(self._on_datasets_reload_error)
        worker.signals.finished.connect(self._status_bar.hide_busy)
        QThreadPool.globalInstance().start(worker)

    def _on_datasets_reloaded(self, result: tuple[list, list[str]]) -> None:
        """Apply the datasets read by :func:`_read_recorded_datasets` to the workspace.

        Runs on the UI thread (connected to ``BaseWorker.signals.result``,
        which Qt's queued-connection default delivers on the receiver's
        thread — the main window lives on the UI thread, so this method
        does too) so ``WorkspaceService`` mutation and dock refresh stay
        off the worker thread.
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
                self,
                "Some Datasets Could Not Be Reloaded",
                f"The project opened, but the following recorded "
                f"dataset(s) could not be automatically reloaded:\n\n"
                f"{failures_text}",
            )

    def _on_datasets_reload_error(self, exc: Exception, traceback_text: str) -> None:
        # _read_recorded_datasets already catches ApplicationError per
        # dataset internally (see its own docstring) — reaching this
        # handler means something unexpected escaped that loop
        # entirely, not a normal per-dataset failure.
        _logger.error(
            "Unexpected failure reloading project datasets: %s\n%s", exc, traceback_text
        )
        QMessageBox.critical(
            self,
            "Failed to Reload Datasets",
            f"An unexpected error occurred while reloading the project's datasets: {exc}",
        )

    def _on_save_project(self) -> None:
        project = self._project_service.get_active_project()
        if project is None:
            self._status_bar.show_message("No project is open to save.")
            return

        if project.path is None:
            self._on_save_project_as()
            return

        self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )

        try:
            self._project_service.save_project(project)
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Save Project", str(exc))
            _logger.warning("Failed to save project: %s", exc)
            return

        self._status_bar.show_message(f"Saved project: {project.name}")

    def _on_save_project_as(self) -> None:
        project = self._project_service.get_active_project()
        if project is None:
            self._status_bar.show_message("No project is open to save.")
            return

        file_path_str, _selected_filter = QFileDialog.getSaveFileName(
            self, "Save Project As", f"{project.name}.uads.json", _PROJECT_FILE_FILTER
        )
        if not file_path_str:
            return  # user cancelled the dialog

        self._project_service.record_datasets(
            project, self._workspace_service.list_datasets()
        )

        try:
            self._project_service.save_project(project, Path(file_path_str))
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Save Project", str(exc))
            _logger.warning("Failed to save project as %s: %s", file_path_str, exc)
            return

        self._status_bar.show_message(f"Saved project: {project.name}")
        self._menu_bar.update_recent_projects_menu(
            self._project_service.get_recent_projects()
        )

    # -- Dataset actions --------------------------------------------------------

    def _on_open_dataset(self) -> None:
        file_path_str, _selected_filter = QFileDialog.getOpenFileName(
            self, "Open Dataset", "", _DATASET_FILE_FILTER
        )
        if not file_path_str:
            return  # user cancelled the dialog

        dataset_path = Path(file_path_str)

        try:
            reader_class = get_reader_for_path(dataset_path)
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Open Dataset", str(exc))
            _logger.warning("No reader available for %s: %s", file_path_str, exc)
            return

        table_name = self._resolve_table_name(reader_class, dataset_path)
        if table_name is _TABLE_SELECTION_CANCELLED:
            return  # user cancelled the table-picker dialog
        if table_name is _NO_TABLES_AVAILABLE:
            # Not an error dialog (QMessageBox.critical) — a document
            # with no detectable tables is not malformed, it simply
            # has nothing tabular in it (a prose-only PDF; a Word doc
            # with no tables). QMessageBox.information matches how
            # this project already distinguishes "something went
            # wrong" from "nothing to report" elsewhere (see the
            # read_warnings handling below in this same method).
            QMessageBox.information(
                self,
                "No Tables Found",
                f"'{dataset_path.name}' does not appear to contain "
                f"any tables that could be extracted as a dataset.",
            )
            _logger.info("No tables found in %s; nothing to load.", file_path_str)
            return

        # Milestone 6: the actual file read — the other named hot spot in the
        # milestone plan alongside project reload — runs on a BaseWorker
        # thread. Everything above this point (dialogs, list_tables) must
        # stay on the UI thread since it drives Qt dialogs directly; only
        # the read() call itself, which can genuinely take a while for a
        # large file, moves off it.
        self._status_bar.show_busy(f"Loading {dataset_path.name}…")
        worker = BaseWorker(reader_class.read, dataset_path, table_name=table_name)
        worker.signals.result.connect(self._on_dataset_read)
        worker.signals.error.connect(
            lambda exc, tb: self._on_dataset_read_error(file_path_str, exc, tb)
        )
        worker.signals.finished.connect(self._status_bar.hide_busy)
        QThreadPool.globalInstance().start(worker)

    def _on_dataset_read(self, dataset) -> None:
        """Apply a successfully read dataset to the workspace (UI thread)."""
        self._workspace_service.add_dataset(dataset)
        self._workspace_service.set_active_dataset(dataset.dataset_id)
        self._dock_manager.refresh_dataset_list(self._workspace_service.list_datasets())

        self._status_bar.show_message(
            f"Loaded dataset: {dataset.name} "
            f"({dataset.row_count} rows × {dataset.column_count} cols)"
        )
        self._dock_manager.append_console_message(
            f"Loaded dataset '{dataset.name}' "
            f"({dataset.row_count} rows × {dataset.column_count} cols)."
        )
        _logger.info(
            "Dataset opened via UI: %s (%d rows, %d cols, %d warning(s))",
            dataset.name,
            dataset.row_count,
            dataset.column_count,
            len(dataset.read_warnings),
        )

        if dataset.read_warnings:
            # Informational, not an error dialog — the load succeeded;
            # these are non-fatal issues the reader flagged along the
            # way (a skipped malformed row, an encoding fallback, an
            # ambiguous-type column — see the individual readers in
            # src.readers for what each one can report here). Surfaced
            # as a dialog rather than folded into the transient status
            # bar message (which times out and could be missed
            # entirely) or left purely in the log (which a user would
            # never see without deliberately opening the Log dock) —
            # these warnings represent real, specific data-quality
            # information the reader worked out, and discarding that
            # silently after a successful load would waste it.
            warnings_text = "\n".join(f"• {w}" for w in dataset.read_warnings)
            QMessageBox.information(
                self,
                "Dataset Loaded with Warnings",
                f"'{dataset.name}' was loaded successfully, but the "
                f"following was noted while reading it:\n\n{warnings_text}",
            )

    def _on_dataset_read_error(
        self, file_path_str: str, exc: Exception, traceback_text: str
    ) -> None:
        # Mirrors the try/except this replaced: reader_class.read()
        # normally raises ApplicationError for expected failure modes
        # (malformed file, unsupported encoding); BaseWorker forwards
        # whatever it caught unchanged, so this handler treats it the
        # same as the old synchronous except block did.
        QMessageBox.critical(self, "Failed to Open Dataset", str(exc))
        self._dock_manager.append_console_message(f"⚠ Failed to open dataset: {exc}")
        _logger.warning("Failed to open dataset from %s: %s", file_path_str, exc)

    def _on_connect_database(self) -> None:
        # Synchronous, not BaseWorker-offloaded — see
        # ConnectDatabaseDialog's own module docstring for why a live
        # database connection is a deliberate exception to this
        # window's usual "slow work runs off the UI thread" rule.
        dialog = ConnectDatabaseDialog(self._database_service, self)
        if dialog.exec() != ConnectDatabaseDialog.DialogCode.Accepted:
            return

        dataset = dialog.get_result()
        if dataset is None:
            return  # dialog accepted without a table having been read; nothing to add

        self._on_dataset_read(dataset)

    def _on_create_visualization(self) -> None:
        active_dataset = self._workspace_service.get_active_dataset()
        if active_dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before creating a visualization.",
            )
            return

        dialog = CreateVisualizationDialog(active_dataset.dataframe, self)
        if dialog.exec() != CreateVisualizationDialog.DialogCode.Accepted:
            return

        figure, chart_type, parameters = dialog.get_result()

        visualization = Visualization(
            name=parameters.get("title") or f"{chart_type} of {active_dataset.name}",
            dataset_id=active_dataset.dataset_id,
            figure=figure,
            chart_type=chart_type,
            chart_parameters=parameters,
        )
        self._workspace_service.add_visualization(visualization)
        self._workspace_service.set_active_visualization(visualization.visualization_id)
        self._dock_manager.display_chart(figure, name=visualization.name)

        self._status_bar.show_message(f"Created visualization: {visualization.name}")
        self._dock_manager.append_console_message(
            f"Created visualization '{visualization.name}' ({chart_type})."
        )
        _logger.info(
            "Visualization created via UI: %s (%s)", visualization.name, chart_type
        )

    def _on_create_dashboard(self) -> None:
        """Combine every currently tracked visualization into one auto-arranged dashboard.

        A first, bounded version — combines all visualizations rather
        than offering a picker/layout designer, which is real
        additional UI work not built yet. Grid arranged 2 columns
        wide, row-major order, matching how many tiles happen to
        exist.
        """
        visualizations = self._workspace_service.list_visualizations()
        if len(visualizations) < 2:
            QMessageBox.information(
                self,
                "Not Enough Visualizations",
                "Create at least 2 visualizations before building a dashboard.",
            )
            return

        columns_per_row = 2
        tiles = [
            DashboardTile(
                visualization_id=viz.visualization_id,
                row=i // columns_per_row,
                column=i % columns_per_row,
            )
            for i, viz in enumerate(visualizations)
        ]
        dashboard = Dashboard(name="Dashboard", tiles=tiles)

        try:
            self._workspace_service.add_dashboard(dashboard)
            resolved = self._workspace_service.get_dashboard_tiles(
                dashboard.dashboard_id
            )
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Create Dashboard", str(exc))
            _logger.warning("Dashboard creation failed: %s", exc)
            return

        # Milestone 6: render_dashboard's Plotly-figure assembly is the
        # third named hot spot in the milestone plan (dataset reads,
        # project reload, dashboard rendering) — offloaded the same way,
        # since combining several figures into one grid is real work that
        # scales with tile count.
        self._status_bar.show_busy("Building dashboard…")
        worker = BaseWorker(render_dashboard, dashboard, resolved)
        worker.signals.result.connect(
            lambda figure: self._on_dashboard_rendered(figure, len(tiles))
        )
        worker.signals.error.connect(self._on_dashboard_render_error)
        worker.signals.finished.connect(self._status_bar.hide_busy)
        QThreadPool.globalInstance().start(worker)

    def _on_dashboard_rendered(self, combined_figure, tile_count: int) -> None:
        self._dock_manager.display_chart(combined_figure, name="Dashboard")
        self._status_bar.show_message(
            f"Created dashboard with {tile_count} visualization(s)."
        )
        self._dock_manager.append_console_message(
            f"Created dashboard with {tile_count} visualization(s)."
        )
        _logger.info("Dashboard created via UI: %d tile(s).", tile_count)

    def _on_dashboard_render_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Dashboard rendering failed: %s\n%s", exc, traceback_text)
        self._dock_manager.append_console_message(f"⚠ Dashboard creation failed: {exc}")
        QMessageBox.critical(self, "Failed to Create Dashboard", str(exc))

    def _on_generate_report(self) -> None:
        active_dataset = self._workspace_service.get_active_dataset()
        if active_dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before generating a report.",
            )
            return

        completed_stages = self._orchestrator_service.get_log(
            active_dataset.dataset_id
        ).completed_stages()
        available_stages = [
            stage for stage in PipelineStage if stage in completed_stages
        ]

        dialog = GenerateReportDialog(active_dataset.name, available_stages, self)
        if dialog.exec() != GenerateReportDialog.DialogCode.Accepted:
            return

        options = dialog.get_result()

        # Milestone 6: report generation rasterizes every chart via
        # kaleido and writes a real file — exactly the kind of
        # operation that must not block the UI thread, matching how
        # _on_create_dashboard above offloads render_dashboard.
        self._status_bar.show_busy("Generating report…")
        worker = BaseWorker(
            self._report_service.generate_report,
            active_dataset.dataset_id,
            options["output_path"],
            options["report_format"],
            options["expertise_level"],
            title=options["title"],
            included_stages=options["included_stages"],
        )
        worker.signals.result.connect(self._on_report_generated)
        worker.signals.error.connect(self._on_report_generation_error)
        worker.signals.finished.connect(self._status_bar.hide_busy)
        QThreadPool.globalInstance().start(worker)

    def _on_report_generated(self, output_path: Path) -> None:
        self._status_bar.show_message(f"Report saved to {output_path}")
        self._dock_manager.append_console_message(f"Generated report: {output_path}")
        _logger.info("Report generated via UI: %s", output_path)

    def _on_report_generation_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Report generation failed: %s\n%s", exc, traceback_text)
        self._dock_manager.append_console_message(f"⚠ Report generation failed: {exc}")
        QMessageBox.critical(self, "Failed to Generate Report", str(exc))

    def _resolve_table_name(self, reader_class, dataset_path: Path):
        """Determine which table to read, prompting the user if more than one exists.

        Calls :meth:`~src.readers.base_reader.BaseReader.list_tables`
        unconditionally rather than only for readers known to be
        multi-table — every reader supports this method (single-table
        readers inherit a default that returns one name derived from
        the file itself; see ``BaseReader.list_tables``'s own
        docstring), so this method does not need to know or check
        which kind of reader it was given.

        Returns:
            ``None`` if the source has exactly one table (no picker
            was needed; :meth:`~src.readers.base_reader.BaseReader.read`
            should be called with ``table_name=None``, which every
            reader handles correctly for the single-table case).
            A table name string if the user picked one from a
            multi-table source.
            :data:`_TABLE_SELECTION_CANCELLED` if the source has more
            than one table and the user cancelled the picker dialog.
            :data:`_NO_TABLES_AVAILABLE` if the source has zero
            tables — a genuinely valid state for some formats (a
            text-only PDF, a Word document with no tables; see
            :mod:`src.readers.pdf_reader` and
            :mod:`src.readers.word_reader`), not an error condition.
            Callers must check for both sentinels specifically (not
            just falsiness) before proceeding, since ``None`` is
            itself a legitimate, different return value from either.

        If :meth:`list_tables` itself raises (a corrupted file, for
        instance), this method does not catch that — it propagates to
        :meth:`_on_open_dataset`'s caller, which already wraps the
        subsequent :meth:`~src.readers.base_reader.BaseReader.read`
        call in the same kind of error handling; letting this
        propagate the same way (rather than duplicating a try/except
        here) keeps error handling for "this file is unreadable" in
        one place regardless of which step first discovers it.
        """
        available_tables = reader_class.list_tables(dataset_path)

        if len(available_tables) == 0:
            return _NO_TABLES_AVAILABLE

        if len(available_tables) == 1:
            return None

        chosen_name, user_confirmed = QInputDialog.getItem(
            self,
            "Select Table",
            f"'{dataset_path.name}' contains {len(available_tables)} "
            f"tables. Which one would you like to open?",
            available_tables,
            0,
            False,  # editable=False: user must pick from the list, not type a name
        )
        if not user_confirmed:
            return _TABLE_SELECTION_CANCELLED
        return chosen_name

    # -- Settings / theme / about -----------------------------------------------

    def _on_open_settings(self) -> None:
        dialog = SettingsDialog(
            self._settings_service, self, plugin_manager=self._plugin_manager
        )
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self._apply_theme_from_settings()

    def _on_toggle_theme(self) -> None:
        current = self._settings_service.get("theme", default="dark")
        new_theme = "light" if current == "dark" else "dark"
        self._settings_service.set("theme", value=new_theme)
        self._settings_service.save()
        self._apply_theme_from_settings()

    def _apply_theme_from_settings(self) -> None:
        theme_manager: ThemeManager = self.property("theme_manager")
        if theme_manager is None:
            _logger.warning(
                "No ThemeManager attached to main window; cannot apply theme change."
            )
            return
        theme_name = self._settings_service.get("theme", default="dark")
        theme_manager.apply_theme(theme_name)

    def attach_theme_manager(self, theme_manager: ThemeManager) -> None:
        """Attach the running application's :class:`~src.ui.theme_manager.ThemeManager`.

        Called once by :mod:`src.core.app` after both the
        ``QApplication`` and this window exist, since ``ThemeManager``
        wraps the live application instance and cannot be constructed
        before it. Stored via ``QWidget.setProperty`` rather than a
        plain attribute purely so :meth:`_apply_theme_from_settings`
        has a single, explicit way to check "has this been attached
        yet" via ``property()`` returning ``None`` — a plain attribute
        would need a separate ``hasattr`` check or an ``Optional``
        instance attribute initialized in ``__init__`` before this
        method could ever run, and ``ThemeManager`` genuinely cannot
        exist that early (see above).
        """
        self.setProperty("theme_manager", theme_manager)

    def _on_open_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    # -- AI chat panel (milestone 10) --------------------------------------------

    def _get_or_build_assistant_service(self) -> AssistantService | None:
        """Return the running :class:`AssistantService`, constructing it from config on first use.

        Returns ``None`` (after showing an explanatory dialog) if no
        provider is configured or construction otherwise fails —
        callers must check for this rather than assuming a non-``None``
        return, since "not configured yet" is a normal, expected state
        for a freshly installed application, not an error to raise
        past the UI layer.
        """
        if self._assistant_service is not None:
            return self._assistant_service

        providers = self._settings_service.get("ai", "providers", default=[])
        rotation_enabled = self._settings_service.get(
            "ai", "rotation_enabled", default=False
        )
        expertise_level = self._settings_service.get(
            "ai", "expertise_level", default="beginner"
        )

        try:
            service = AssistantService.from_provider_profiles(
                providers, rotation_enabled, self._workspace_service, expertise_level
            )
        except ServiceError as exc:
            QMessageBox.information(self, "AI Assistant Not Configured", str(exc))
            return None

        self._assistant_service = service
        self._dock_manager.chat_panel.set_provider_label(
            f"Provider: {service.active_provider_name}"
        )
        _logger.info(
            "AssistantService constructed (provider: %s).", service.active_provider_name
        )
        return service

    def _on_send_chat_message(self) -> None:
        chat_panel = self._dock_manager.chat_panel
        text = chat_panel.current_input_text()
        if not text:
            return

        if self._workspace_service.get_active_dataset() is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before using the AI assistant.",
            )
            return

        service = self._get_or_build_assistant_service()
        if service is None:
            return  # _get_or_build_assistant_service already explained why

        chat_panel.append_user_message(text)
        chat_panel.clear_input()
        chat_panel.set_ready(False)
        self._status_bar.show_busy("Waiting for AI assistant…")

        worker = BaseWorker(service.send_message, text)
        worker.signals.result.connect(self._on_assistant_turn_result)
        worker.signals.error.connect(self._on_assistant_turn_error)
        worker.signals.finished.connect(self._on_assistant_turn_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_assistant_turn_result(self, result: AssistantTurnResult) -> None:
        chat_panel = self._dock_manager.chat_panel
        chat_panel.append_assistant_message(result.reply_text)
        self._dock_manager.append_console_message("AI assistant turn completed.")

        if result.new_datasets:
            chat_panel.append_tool_activity(
                f"Created {len(result.new_datasets)} new dataset(s): "
                f"{', '.join(d.name for d in result.new_datasets)}."
            )
            self._dock_manager.append_console_message(
                f"AI tool created dataset(s): "
                f"{', '.join(d.name for d in result.new_datasets)}."
            )
            self._dock_manager.refresh_dataset_list(
                self._workspace_service.list_datasets()
            )

        for visualization in result.new_visualizations:
            chat_panel.append_tool_activity(
                f"Created visualization: {visualization.name}."
            )
            self._dock_manager.append_console_message(
                f"AI tool created visualization: {visualization.name}."
            )
            self._dock_manager.display_chart(
                visualization.figure, name=visualization.name
            )

        if self._assistant_service is not None:
            # Reflects any rotation that happened mid-turn (milestone
            # 7) — the label may now name a different provider profile
            # than it did before this turn started.
            chat_panel.set_provider_label(
                f"Provider: {self._assistant_service.active_provider_name}"
            )

    def _on_assistant_turn_error(self, exc: Exception, traceback_text: str) -> None:
        self._dock_manager.chat_panel.append_error_message(str(exc))
        self._dock_manager.append_console_message(f"⚠ AI assistant turn failed: {exc}")
        _logger.warning("Assistant turn failed: %s\n%s", exc, traceback_text)

    def _on_assistant_turn_finished(self) -> None:
        self._status_bar.hide_busy()
        self._dock_manager.chat_panel.set_ready(True)

    # -- Window lifecycle --------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Detach the logging-panel handler before the window closes.

        Without this, the root logger retains a handler wrapping this
        window's (about-to-be-destroyed) logging dock widget; any log
        call after close would raise when the handler tried to write
        to a widget that no longer exists. See
        :meth:`~src.ui.dock_manager.DockManager.remove_log_handler`'s
        own docstring for the same reasoning.
        """
        self._dock_manager.remove_log_handler()
        _logger.info("Main window closing.")
        super().closeEvent(event)
