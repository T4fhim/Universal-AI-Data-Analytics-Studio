# File: src/ui/main_window.py
"""The application's main window.

:class:`MainWindow` assembles every piece built in milestone 1b-ii --
menu bar, toolbar, status bar, dock manager, theme manager, and the
welcome widget as initial central content -- and, since milestone 19,
constructs the per-concern controllers in :mod:`src.ui.controllers` and
wires :class:`~src.ui.actions.action_binder.ActionBinder` to their
methods rather than holding every handler itself. This class does not
construct its own service instances: it resolves what it needs from
``context.container``, the same container every other part of the
running application resolves from, and hands those services to whichever
controller owns the concern they belong to.

Milestone 19 note: before this milestone, this file held every project/
dataset/visualization/report/assistant handler directly and had grown to
942 lines -- exactly the "one more handler" growth
:mod:`tests.ui.test_module_size`'s own docstring warns about. This is a
pure refactor: every controller method in :mod:`src.ui.controllers` is
the same logic that used to live here, moved verbatim. What remains here
is genuinely window-level: settings/theme/about, the command palette
shortcut, and window lifecycle.
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
from src.services.analysis_orchestrator_service import AnalysisOrchestratorService
from src.services.database_connection_service import DatabaseConnectionService
from src.services.project_service import ProjectService
from src.services.report_service import ReportService
from src.services.settings_service import SettingsService
from src.services.workspace_service import WorkspaceService
from src.ui.actions.action_binder import ActionBinder
from src.ui.actions.action_context import ActionContext
from src.ui.command_palette import CommandPalette
from src.ui.controllers.assistant_controller import AssistantController
from src.ui.controllers.database_controller import DatabaseController
from src.ui.controllers.dataset_controller import DatasetController
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
from src.ui.widgets.welcome_widget import WelcomeWidget
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

        self._menu_bar = ApplicationMenuBar(self, self._binder, self._state_bus)
        self.setMenuBar(self._menu_bar)

        self._tool_bar = ApplicationToolBar(self, self._binder)
        self.addToolBar(self._tool_bar)

        self._status_bar = ApplicationStatusBar(self)
        self.setStatusBar(self._status_bar)

        self._dock_manager = DockManager(self)
        self._populate_view_menu()

        self._welcome_widget = WelcomeWidget(self)
        self.setCentralWidget(self._welcome_widget)

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
        """Construct every milestone-19 controller, each holding only what it needs.

        One controller per concern rather than a shared "god context"
        object -- see :mod:`src.ui.controllers`'s own docstring for why.
        ``DatabaseController`` is built last because it depends on
        ``DatasetController.load_dataset`` as its result callback.
        """
        self._project_controller = ProjectController(
            self,
            self._project_service,
            self._workspace_service,
            self._dock_manager,
            self._status_bar,
            self._state_bus,
            self._worker_runner,
            self._menu_bar,
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

        self._welcome_widget.button_new_project.clicked.connect(
            self._project_controller.new_project
        )
        self._welcome_widget.button_open_project.clicked.connect(
            self._project_controller.open_project
        )

        self._dock_manager.chat_panel.send_button.clicked.connect(
            self._assistant_controller.send_chat_message
        )

        # Milestone 18: the first time double-clicking a dataset has ever
        # done anything in this application -- see DockManager.
        # connect_dataset_double_click's own docstring.
        self._dock_manager.connect_dataset_double_click(
            self._dataset_controller.on_dataset_double_clicked
        )

    def _on_ui_state_changed(self) -> None:
        """Recompute and apply enablement -- the sole consumer of ``state_changed``.

        Rebuilds a fresh :class:`~src.ui.actions.action_context.ActionContext`
        from the live services on every call rather than tracking one
        incrementally, per that class's own docstring. ``is_busy`` is
        always ``False`` here: no current ``ActionSpec`` reads it (only
        ``can_undo``/``can_redo``, also always ``False`` until milestone 23,
        share that "field exists, nothing consumes it yet" status), so
        wiring live worker-busy tracking now would be speculative plumbing
        with no predicate to observe it.
        """
        context = ActionContext.capture(
            project_service=self._project_service,
            workspace_service=self._workspace_service,
            settings_service=self._settings_service,
        )
        self._binder.refresh_enablement(context)

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
