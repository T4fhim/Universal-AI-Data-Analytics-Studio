# File: src/ui/menu_bar.py
"""Constructs the application's menu bar.

:class:`ApplicationMenuBar` builds the File, Edit, View, and Help
menus and their actions, but does not itself implement what any action
*does* — each ``QAction`` is exposed as a public attribute (for
example, ``self.action_new_project``) so that :mod:`src.ui.main_window`
can connect it to a real handler that calls into
:class:`~src.services.project_service.ProjectService` or whichever
service the action concerns. This keeps "what menu items exist and how
they're organized" separate from "what happens when the user clicks
one," matching the separation already used between service and UI
layers elsewhere in this project.

Keyboard shortcuts are attached here, since a shortcut is a property of
the action itself (what key combination triggers it) rather than of
the handler (what the trigger does).
"""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenuBar

from src.core.logger import get_logger

_logger = get_logger(__name__)


class ApplicationMenuBar(QMenuBar):
    """The application's top-level menu bar.

    Args:
        parent_window: The main window this menu bar belongs to.
            Passed through to ``QMenuBar``'s own parent parameter and
            also used as the parent for each ``QAction``, since Qt
            actions need a parent to participate correctly in the
            widget's event and shortcut handling.
    """

    def __init__(self, parent_window: QMainWindow) -> None:
        super().__init__(parent_window)
        self._build_file_menu(parent_window)
        self._build_edit_menu(parent_window)
        self._build_view_menu(parent_window)
        self._build_analysis_menu(parent_window)
        self._build_help_menu(parent_window)
        _logger.debug("Menu bar constructed.")

    def _build_file_menu(self, parent_window: QMainWindow) -> None:
        file_menu = self.addMenu("&File")

        self.action_new_project = QAction("&New Project", parent_window)
        self.action_new_project.setShortcut(QKeySequence.StandardKey.New)
        file_menu.addAction(self.action_new_project)

        self.action_open_project = QAction("&Open Project...", parent_window)
        self.action_open_project.setShortcut(QKeySequence.StandardKey.Open)
        file_menu.addAction(self.action_open_project)

        self.menu_recent_projects = file_menu.addMenu("Open &Recent")

        file_menu.addSeparator()

        # Dataset actions are grouped separately from project actions
        # (above) and settings/exit actions (below) — opening a
        # dataset (a .csv/.json/.txt file, via src.readers) is a
        # conceptually different operation from opening a project (a
        # .uads.json file, via ProjectService), even though both are
        # "open a file" in a loose sense. QKeySequence.StandardKey.Open
        # (Ctrl+O) is already claimed by action_open_project above, so
        # this needs its own explicit, non-conflicting shortcut rather
        # than reusing a standard key that would create an ambiguous
        # double-binding.
        self.action_open_dataset = QAction("Open &Dataset...", parent_window)
        self.action_open_dataset.setShortcut("Ctrl+Shift+O")
        file_menu.addAction(self.action_open_dataset)

        file_menu.addSeparator()

        self.action_save_project = QAction("&Save Project", parent_window)
        self.action_save_project.setShortcut(QKeySequence.StandardKey.Save)
        file_menu.addAction(self.action_save_project)

        self.action_save_project_as = QAction("Save Project &As...", parent_window)
        self.action_save_project_as.setShortcut(QKeySequence.StandardKey.SaveAs)
        file_menu.addAction(self.action_save_project_as)

        file_menu.addSeparator()

        self.action_settings = QAction("Se&ttings...", parent_window)
        self.action_settings.setShortcut(QKeySequence.StandardKey.Preferences)
        file_menu.addAction(self.action_settings)

        file_menu.addSeparator()

        self.action_exit = QAction("E&xit", parent_window)
        self.action_exit.setShortcut(QKeySequence.StandardKey.Quit)
        file_menu.addAction(self.action_exit)

    def _build_edit_menu(self, parent_window: QMainWindow) -> None:
        edit_menu = self.addMenu("&Edit")

        self.action_undo = QAction("&Undo", parent_window)
        self.action_undo.setShortcut(QKeySequence.StandardKey.Undo)
        edit_menu.addAction(self.action_undo)

        self.action_redo = QAction("&Redo", parent_window)
        self.action_redo.setShortcut(QKeySequence.StandardKey.Redo)
        edit_menu.addAction(self.action_redo)

    def _build_view_menu(self, parent_window: QMainWindow) -> None:
        view_menu = self.addMenu("&View")

        self.action_toggle_theme = QAction("Toggle &Dark / Light Theme", parent_window)
        view_menu.addAction(self.action_toggle_theme)

        view_menu.addSeparator()

        # Dock-widget visibility toggles are added here by main_window.py
        # after DockManager has constructed the actual dock widgets,
        # since this menu needs a reference to each dock's own
        # toggleViewAction() — this class does not construct docks
        # itself (that is DockManager's responsibility) and so cannot
        # populate these entries at __init__ time.
        self.menu_view = view_menu

    def _build_analysis_menu(self, parent_window: QMainWindow) -> None:
        # Separate from View: a chart is a data action performed on
        # the active dataset (closer in kind to Open Dataset), not a
        # toggle of the window's own appearance. Also gives future
        # Statistics Engine actions (correlation, aggregation views) a
        # natural home without a second menu reshuffle later.
        analysis_menu = self.addMenu("&Analysis")

        self.action_create_visualization = QAction("&Visualize...", parent_window)
        analysis_menu.addAction(self.action_create_visualization)

        self.action_create_dashboard = QAction("Create &Dashboard", parent_window)
        analysis_menu.addAction(self.action_create_dashboard)

    def _build_help_menu(self, parent_window: QMainWindow) -> None:
        help_menu = self.addMenu("&Help")

        self.action_about = QAction("&About", parent_window)
        help_menu.addAction(self.action_about)

    def update_recent_projects_menu(self, recent_paths: list[str]) -> None:
        """Rebuild the "Open Recent" submenu from a list of project paths.

        Args:
            recent_paths: Paths as returned by
                :meth:`~src.services.project_service.ProjectService.get_recent_projects`,
                most recent first. Each becomes a clickable action;
                connecting those actions to actually opening the
                project is :mod:`src.ui.main_window`'s job, done after
                calling this method, since this method only rebuilds
                the menu structure and does not know how to open a
                project itself.

        This clears and rebuilds the submenu each time rather than
        diffing against the previous contents, since the list is
        small (capped at 10 by
        :class:`~src.services.project_service.ProjectService`) and
        rebuilding is simpler and less error-prone than maintaining
        incremental menu state.
        """
        self.menu_recent_projects.clear()
        self.actions_recent_projects: list[QAction] = []

        if not recent_paths:
            empty_action = QAction("(No recent projects)", self)
            empty_action.setEnabled(False)
            self.menu_recent_projects.addAction(empty_action)
            return

        for path_str in recent_paths:
            action = QAction(path_str, self)
            action.setData(path_str)
            self.menu_recent_projects.addAction(action)
            self.actions_recent_projects.append(action)
