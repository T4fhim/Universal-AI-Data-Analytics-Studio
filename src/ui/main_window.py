# File: src/ui/main_window.py
"""The application's main window.

:class:`MainWindow` assembles every piece built in milestone 1b-ii --
menu bar, toolbar, status bar, dock manager, theme manager, and (since
milestone 20) the workbench as initial central content -- and, since
milestone 19, constructs the per-concern controllers in
:mod:`src.ui.controllers` and wires
:class:`~src.ui.actions.action_binder.ActionBinder` to their methods rather
than holding every handler itself. This class does not construct its own
service instances: it resolves what it needs from ``context.container``,
the same container every other part of the running application resolves
from, and hands those services to whichever controller owns the concern
they belong to.

Milestone 19 note: before this milestone, this file held every project/
dataset/visualization/report/assistant handler directly and had grown to
942 lines -- exactly the "one more handler" growth
:mod:`tests.ui.test_module_size`'s own docstring warns about. This is a
pure refactor: every controller method in :mod:`src.ui.controllers` is
the same logic that used to live here, moved verbatim. What remains here
is genuinely window-level: settings/theme/about, the command palette
shortcut, and window lifecycle.

Milestone 20 note: :class:`~src.ui.workbench.workbench.Workbench` replaces
``WelcomeWidget`` as the central widget (see :meth:`__init__`'s own
comment on that call site), and :meth:`_refresh_workbench` -- reached via
``state_changed`` alongside the existing enablement recompute -- is the one
place this file reads live :class:`~src.services.analysis_orchestrator_service.
AnalysisOrchestratorService` state and pushes it into that otherwise
service-free widget tree.
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QMainWindow

# Import-time registration side effect, matching how src.visualization.
# chart_registry's own built-ins are seeded -- this module must be imported
# somewhere before ActionBinder.assert_all_bound() runs below, or the
# registry it populates would simply be empty. main_window.py is the
# composition root for the UI's action-consuming side, so it is the
# natural place for this import to live rather than a scattered import in
# menu_bar.py/toolbar.py, which only *consume* the registry, not populate it.
import src.ui.actions.builtin_actions  # noqa: F401
from src.core.bootstrap import BootstrapContext
from src.core.constants import APP_NAME, DEFAULT_WINDOW_HEIGHT, DEFAULT_WINDOW_WIDTH
from src.core.logger import get_logger
from src.plugins.plugin_manager import PluginManager
from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.database_connection_service import DatabaseConnectionService
from src.services.project_service import ProjectService
from src.services.report_service import ReportService
from src.services.settings_service import SettingsService
from src.services.workspace_service import WorkspaceService
from src.ui.actions.action_binder import ActionBinder
from src.ui.actions.action_context import ActionContext
from src.ui.command_palette import CommandPalette
from src.ui.command_stack import CommandStack
from src.ui.controllers.assistant_controller import AssistantController
from src.ui.controllers.database_controller import DatabaseController
from src.ui.controllers.dataset_controller import DatasetController
from src.ui.controllers.pipeline_controller import PipelineController
from src.ui.controllers.project_controller import ProjectController
from src.ui.controllers.report_controller import ReportController
from src.ui.controllers.visualization_controller import VisualizationController
from src.ui.dialogs.about_dialog import AboutDialog
from src.ui.dialogs.settings_dialog import SettingsDialog
from src.ui.dock_manager import DockManager
from src.ui.menu_bar import ApplicationMenuBar
from src.ui.status_bar import ApplicationStatusBar
from src.ui.theme.icon_provider import IconProvider
from src.ui.theme.tokens import DARK_TOKENS
from src.ui.theme_manager import ThemeManager
from src.ui.toolbar import ApplicationToolBar
from src.ui.ui_state_bus import UiStateBus
from src.ui.workbench.pages.analyze_page import AnalyzePage
from src.ui.workbench.pages.clean_page import CleanPage
from src.ui.workbench.pages.explore_page import ExplorePage
from src.ui.workbench.pages.report_page import ReportPage
from src.ui.workbench.pages.reproduce_page import ReproducePage
from src.ui.workbench.pages.understand_page import UnderstandPage
from src.ui.workbench.workbench import Workbench
from src.ui.worker_runner import WorkerRunner

_logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """The application's main window.

    Args:
        context: The result of a successful
            :func:`~src.core.bootstrap.bootstrap` call. Services this
            window needs are resolved from ``context.container`` during
            construction and handed to whichever controller owns them;
            ``ThemeManager`` is constructed fresh here (it wraps the live
            ``QApplication`` instance, which does not exist until
            :mod:`src.core.app` constructs it -- see that module's
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

        self.setWindowTitle(APP_NAME)
        self.resize(DEFAULT_WINDOW_WIDTH, DEFAULT_WINDOW_HEIGHT)

        # Milestone 17: IconProvider needs a ThemeTokens instance at
        # construction, but ThemeManager (which knows the real, configured
        # theme) is not constructed until after this window is, by
        # src/core/app.py -- see attach_theme_manager below for where this
        # gets corrected to the real theme. DARK_TOKENS here is a safe,
        # visible-either-way placeholder for the brief window before that
        # call, not a real theme decision.
        self._icon_provider = IconProvider(DARK_TOKENS, parent=self)
        self._state_bus = UiStateBus(self)
        self._binder = ActionBinder(self, self._icon_provider)
        self._worker_runner = WorkerRunner(self)
        # Milestone 23: constructed directly here, not resolved from the
        # DependencyContainer -- see src/ui/command_stack.py's own docstring for why it
        # follows UiStateBus/WorkerRunner's construction pattern rather than bootstrap.py's.
        self._command_stack = CommandStack(self._workspace_service)

        self._menu_bar = ApplicationMenuBar(self, self._binder, self._state_bus)
        self.setMenuBar(self._menu_bar)

        self._tool_bar = ApplicationToolBar(self, self._binder)
        self.addToolBar(self._tool_bar)

        self._status_bar = ApplicationStatusBar(self)
        self.setStatusBar(self._status_bar)

        self._dock_manager = DockManager(self)
        self._populate_view_menu()

        # Milestone 20: Workbench replaces WelcomeWidget as the central
        # widget -- unlike WelcomeWidget (setCentralWidget called exactly
        # once, forever, before this milestone), Workbench itself IS the
        # permanent central widget, and internally switches from its
        # welcome page to a pipeline stage page once a dataset becomes
        # active -- see _refresh_workbench, called from _on_ui_state_changed.
        self._workbench = Workbench(self)
        self.setCentralWidget(self._workbench)

        self._command_palette = CommandPalette(self, self._binder, self._state_bus)
        self._command_palette_shortcut = QShortcut(QKeySequence("Ctrl+K"), self)
        self._command_palette_shortcut.activated.connect(self._command_palette.exec)

        self._build_controllers()
        self._connect_actions()
        self._binder.assert_all_bound()
        self._state_bus.state_changed.connect(self._on_ui_state_changed)
        # Seed enablement once immediately -- every QAction defaults to
        # Qt's own enabled=True, and state_changed only fires from
        # request_refresh() (a later mutation) or a menu's aboutToShow.
        # Without this call, "Save Project" would show enabled on a cold
        # start with no project open until the user first did something.
        self._on_ui_state_changed()

        self._menu_bar.update_recent_projects_menu(
            self._project_service.get_recent_projects(),
            on_open=self._project_controller.open_recent_project,
        )

        _logger.info("Main window constructed.")

    # -- Setup helpers --------------------------------------------------------

    def _build_controllers(self) -> None:
        """Construct every controller, each holding only what it needs.

        One controller per concern rather than a shared "god context"
        object -- see :mod:`src.ui.controllers`'s own docstring for why.
        ``PipelineController`` is built first because ``ProjectController``
        depends on two of its methods (``persist_all_logs``/
        ``restore_logs_for_project``) as callbacks -- milestone 20's own
        version of the same "built last/first because it depends on another
        controller's method" ordering ``DatabaseController`` already
        established for ``DatasetController.load_dataset``.
        """
        self._pipeline_controller = PipelineController(
            self,
            self._workspace_service,
            self._orchestrator_service,
            self._project_service,
            self._dock_manager,
            self._status_bar,
            self._state_bus,
            self._worker_runner,
            self._command_stack,
            on_changed=self._refresh_workbench,
        )
        self._project_controller = ProjectController(
            self,
            self._project_service,
            self._workspace_service,
            self._dock_manager,
            self._status_bar,
            self._state_bus,
            self._worker_runner,
            self._menu_bar,
            on_before_save=self._pipeline_controller.persist_all_logs,
            on_project_opened=self._pipeline_controller.restore_logs_for_project,
        )
        self._dataset_controller = DatasetController(
            self,
            self._workspace_service,
            self._dock_manager,
            self._status_bar,
            self._state_bus,
            self._worker_runner,
        )
        self._visualization_controller = VisualizationController(
            self,
            self._workspace_service,
            self._dock_manager,
            self._status_bar,
            self._state_bus,
            self._worker_runner,
        )
        self._report_controller = ReportController(
            self,
            self._workspace_service,
            self._orchestrator_service,
            self._report_service,
            self._dock_manager,
            self._status_bar,
            self._worker_runner,
        )
        self._assistant_controller = AssistantController(
            self,
            self._settings_service,
            self._workspace_service,
            self._dock_manager,
            self._status_bar,
            self._worker_runner,
        )
        self._database_controller = DatabaseController(
            self, self._database_service, self._dataset_controller.load_dataset
        )

    def _populate_view_menu(self) -> None:
        for toggle_action in self._dock_manager.view_menu_toggle_actions():
            self._menu_bar.menu_view.addAction(toggle_action)

    def _connect_actions(self) -> None:
        bind = self._binder.bind
        bind("project.new", self._project_controller.new_project)
        bind("project.open", self._project_controller.open_project)
        bind("dataset.open", self._dataset_controller.open_dataset)
        bind("dataset.connect_database", self._database_controller.connect_database)
        bind("analysis.visualize", self._visualization_controller.create_visualization)
        bind("analysis.dashboard", self._visualization_controller.create_dashboard)
        bind("analysis.generate_report", self._report_controller.generate_report)
        bind("project.save", self._project_controller.save_project)
        bind("project.save_as", self._project_controller.save_project_as)
        bind("project.settings", self._on_open_settings)
        bind("project.exit", self.close)
        bind("view.toggle_theme", self._on_toggle_theme)
        bind("help.about", self._on_open_about)
        bind("edit.undo", self._pipeline_controller.undo)
        bind("edit.redo", self._pipeline_controller.redo)

        self._workbench.welcome_page.button_new_project.clicked.connect(
            self._project_controller.new_project
        )
        self._workbench.welcome_page.button_open_project.clicked.connect(
            self._project_controller.open_project
        )

        self._dock_manager.chat_panel.send_button.clicked.connect(
            self._assistant_controller.send_chat_message
        )
        # Milestone 21: "Clear Chat" and the live expertise-level selector.
        self._dock_manager.chat_panel.clear_button.clicked.connect(
            self._assistant_controller.clear_chat
        )
        self._dock_manager.chat_panel.expertise_combo.currentIndexChanged.connect(
            self._assistant_controller.on_expertise_level_changed
        )

        # Milestone 18: the first time double-clicking a dataset has ever
        # done anything in this application -- see DockManager.
        # connect_dataset_double_click's own docstring.
        self._dock_manager.connect_dataset_double_click(
            self._dataset_controller.on_dataset_double_clicked
        )

        # Milestone 20: workbench stage pages emit signals rather than
        # calling services themselves (see src/ui/workbench/__init__.py's
        # own docstring) -- this is where those signals meet the
        # controller methods that actually do the work. isinstance narrows
        # StagePage down to each concrete subclass so its own signals (not
        # declared on the StagePage base) are visible to mypy, rather than
        # an `is not None` check alone.
        understand_page = self._workbench.page_for(PipelineStage.UNDERSTAND)
        if isinstance(understand_page, UnderstandPage):
            understand_page.run_requested.connect(
                self._pipeline_controller.run_understand_stage
            )
        report_page = self._workbench.page_for(PipelineStage.REPORT)
        if isinstance(report_page, ReportPage):
            report_page.generate_report_requested.connect(
                self._report_controller.generate_report
            )
        reproduce_page = self._workbench.page_for(PipelineStage.REPRODUCE)
        if isinstance(reproduce_page, ReproducePage):
            reproduce_page.reproduce_requested.connect(
                self._pipeline_controller.reproduce_active_dataset
            )
        # Milestone 23: CleanPage computes the derived dataset itself (see its own
        # docstring for why) and hands it off via a signal, the same "structure here,
        # behavior wired by the caller" split every other stage page above uses.
        clean_page = self._workbench.page_for(PipelineStage.CLEAN)
        if isinstance(clean_page, CleanPage):
            clean_page.operation_applied.connect(
                self._pipeline_controller.register_clean_operation
            )

        # Milestone 23: "genuinely reachable" close actions -- see
        # DockManager.connect_dataset_close_requested/connect_chart_closed's own
        # docstrings for why these are wired as callbacks rather than QActions
        # (there is no fixed, registrable set of "which dataset/chart" ids the way
        # ActionRegistry's own entries are all parameter-free).
        self._dock_manager.connect_dataset_close_requested(
            self._dataset_controller.close_dataset
        )
        self._dock_manager.connect_chart_closed(
            self._visualization_controller.on_chart_closed
        )

    def _on_ui_state_changed(self) -> None:
        """Recompute and apply enablement -- the sole consumer of ``state_changed``.

        Rebuilds a fresh :class:`~src.ui.actions.action_context.ActionContext`
        from the live services on every call rather than tracking one
        incrementally, per that class's own docstring. ``is_busy`` is
        always ``False`` here: no current ``ActionSpec`` reads it, so wiring
        live worker-busy tracking now would be speculative plumbing with no
        predicate to observe it. ``can_undo``/``can_redo`` (milestone 23) are
        real, read from :attr:`_command_stack`.

        Milestone 20: also refreshes the Dataset Explorer's "Project" node
        and the workbench's pipeline state -- ``state_changed`` already
        fires at exactly the moments either could have changed (a project
        opened/saved, a dataset activated, a stage ran), so this is the one
        place both piggyback on rather than each needing their own
        notification wiring.
        """
        context = ActionContext.capture(
            project_service=self._project_service,
            workspace_service=self._workspace_service,
            settings_service=self._settings_service,
            can_undo=self._command_stack.can_undo(),
            can_redo=self._command_stack.can_redo(),
        )
        self._binder.refresh_enablement(context)

        active_project = self._project_service.get_active_project()
        self._dock_manager.set_project_label(
            active_project.name if active_project is not None else None
        )
        self._refresh_workbench()

    def _refresh_workbench(self) -> None:
        """Push a fresh :class:`~src.ui.controllers.pipeline_controller.PipelineSnapshot`
        into the workbench -- the sole place that reads
        :class:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService`
        state and translates it into what :class:`~src.ui.workbench.workbench.Workbench`
        (a display-only widget with no service reference of its own) renders.
        """
        active_dataset = self._workspace_service.get_active_dataset()
        snapshot = self._pipeline_controller.snapshot_for_active_dataset()
        log = snapshot.log if snapshot is not None else None
        proposal = snapshot.proposal if snapshot is not None else None
        self._workbench.update_pipeline_state(
            dataset_active=active_dataset is not None, log=log, proposal=proposal
        )

        understand_page = self._workbench.page_for(PipelineStage.UNDERSTAND)
        if isinstance(understand_page, UnderstandPage) and log is not None:
            understand_entries = [
                entry
                for entry in log.entries
                if entry.stage == PipelineStage.UNDERSTAND
            ]
            if understand_entries:
                understand_page.show_profile_summary(understand_entries[-1].outputs)

        # Milestone 22: AnalyzePage/ExplorePage hold a plain Dataset (not a service
        # reference -- see AnalyzePage's own docstring), so this is the same "structure
        # here, behavior wired by the caller" hand-off UnderstandPage.show_profile_summary
        # above already uses, just handing over the dataset itself instead of a log entry.
        analyze_page = self._workbench.page_for(PipelineStage.ANALYZE)
        if isinstance(analyze_page, AnalyzePage):
            analyze_page.set_dataset(active_dataset)
        explore_page = self._workbench.page_for(PipelineStage.EXPLORE)
        if isinstance(explore_page, ExplorePage):
            explore_page.set_dataset(active_dataset)

        # Milestone 23: same hand-off, plus feeding the real
        # get_lineage/get_children output into LineageView -- see
        # CleanPage.show_lineage's own docstring for why the page itself
        # never calls WorkspaceService directly.
        clean_page = self._workbench.page_for(PipelineStage.CLEAN)
        if isinstance(clean_page, CleanPage):
            clean_page.set_dataset(active_dataset)
            if active_dataset is not None:
                ancestors = self._workspace_service.get_lineage(
                    active_dataset.dataset_id
                )
                descendants = self._workspace_service.get_children(
                    active_dataset.dataset_id
                )
                clean_page.show_lineage(ancestors, active_dataset, descendants)
            else:
                clean_page.show_lineage([], None, [])

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
        before it. Stored via ``QWidget.setProperty`` rather than a plain
        attribute purely so :meth:`_apply_theme_from_settings` has a
        single, explicit way to check "has this been attached yet" via
        ``property()`` returning ``None`` -- a plain attribute would need
        a separate ``hasattr`` check or an ``Optional`` instance
        attribute initialized in ``__init__`` before this method could
        ever run, and ``ThemeManager`` genuinely cannot exist that early
        (see above).
        """
        self.setProperty("theme_manager", theme_manager)
        # Milestone 16: the dock manager's open chart tabs need to hear
        # about theme changes too, to recolour via Plotly.relayout -- see
        # DockManager.attach_theme_manager for why this is a separate call
        # rather than DockManager reading self.property("theme_manager")
        # itself (it would need a live QWidget reference to do that, which
        # this class already is and DockManager deliberately is not).
        self._dock_manager.attach_theme_manager(theme_manager)

        # Milestone 17: self._icon_provider was constructed with DARK_TOKENS
        # as a placeholder in __init__ (ThemeManager did not exist yet) --
        # correct it to the real, configured theme now, and keep it
        # current on every future toggle. current_tokens() is not None
        # here: src/core/app.py always calls apply_theme() before this
        # method, so a theme has already been applied by this point.
        current_tokens = theme_manager.current_tokens()
        if current_tokens is not None:
            self._icon_provider.set_tokens(current_tokens)
        theme_manager.theme_changed.connect(
            lambda _name: self._icon_provider.set_tokens(theme_manager.current_tokens())
        )

    def _on_open_about(self) -> None:
        dialog = AboutDialog(self)
        dialog.exec()

    # -- Window lifecycle --------------------------------------------------------

    def closeEvent(self, event) -> None:
        """Tear down long-lived resources before the window closes.

        Detaches the logging-panel handler first: without this, the root
        logger retains a handler wrapping this window's
        (about-to-be-destroyed) logging dock widget, and any log call
        after close would raise when the handler tried to write to a
        widget that no longer exists -- see
        :meth:`~src.ui.dock_manager.DockManager.remove_log_handler`'s own
        docstring for the same reasoning.

        Milestone 19: also closes every live database connection this
        session opened. Before this milestone nothing called
        :meth:`~src.services.database_connection_service.
        DatabaseConnectionService.close_all_connections` from the UI at
        all -- a connection opened via Connect to Database stayed open
        until the process exited rather than being released when the
        window that opened it closed.
        """
        self._dock_manager.remove_log_handler()
        self._database_service.close_all_connections()
        _logger.info("Main window closing.")
        super().closeEvent(event)
