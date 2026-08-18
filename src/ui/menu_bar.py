# File: src/ui/menu_bar.py
"""Constructs the application's menu bar from the action registry.

Milestone 17 rewrite. Before this milestone, ``ApplicationMenuBar``
constructed each ``QAction`` itself and exposed it as a named attribute
(``self.action_new_project``), which ``main_window.py`` connected by hand --
nothing enforced that every constructed action actually got a handler. Now
each menu is a flat, declarative list of
:class:`~src.ui.actions.action_registry.ActionSpec` ids, handed to
:meth:`~src.ui.actions.action_binder.ActionBinder.build_menu`, which
constructs (or reuses) the real ``QAction`` for each id -- the same
``QAction`` the toolbar and command palette also reference, so there is
exactly one object per action rather than three independent ones that could
drift out of sync.

The **Edit menu was removed** in milestone 17, not merely emptied --
``Undo``/``Redo`` were real, clickable ``QAction``s connected to nothing at
the time, exactly the dead-action defect this whole overhaul's audit
flagged (the same "absence over inert placeholder" reasoning milestone 20
applies to the Project Explorer dock). **It returns here in milestone 23**,
now that ``edit.undo``/``edit.redo`` have real semantics -- see
:mod:`~src.ui.command_stack`'s own docstring.

"Open Recent" stays bespoke rather than becoming registry entries: each
item's target path is per-instance data no static
:class:`~src.ui.actions.action_registry.ActionSpec` could represent (there
is no fixed set of "recent project" ids to register). See
:meth:`update_recent_projects_menu`.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenuBar

from src.core.logger import get_logger
from src.ui.actions.action_binder import ActionBinder
from src.ui.ui_state_bus import UiStateBus

_logger = get_logger(__name__)

_ANALYSIS_MENU_ACTIONS: tuple[str | None, ...] = (
    "analysis.visualize",
    "analysis.dashboard",
    None,
    "analysis.generate_report",
)

_HELP_MENU_ACTIONS: tuple[str | None, ...] = ("help.about",)


class ApplicationMenuBar(QMenuBar):
    """The application's top-level menu bar.

    Args:
        parent_window: The main window this menu bar belongs to.
        binder: Constructs and owns every ``QAction`` this menu bar
            displays -- see the module docstring for why menu construction
            no longer owns its own actions directly.
        state_bus: If given, connected to ``aboutToShow`` on every
            registry-backed menu, so enablement is recomputed just before a
            menu opens even if a call site failed to call
            :meth:`~src.ui.ui_state_bus.UiStateBus.request_refresh` itself
            -- the lazy safety net that module's docstring describes.
    """

    def __init__(
        self,
        parent_window: QMainWindow,
        binder: ActionBinder,
        state_bus: UiStateBus | None = None,
    ) -> None:
        super().__init__(parent_window)
        self.binder = binder
        self._state_bus = state_bus

        self._build_file_menu()
        self._build_edit_menu()
        self._build_view_menu()
        self._build_analysis_menu()
        self._build_help_menu()
        _logger.debug("Menu bar constructed.")

    def _connect_refresh(self, menu) -> None:
        if self._state_bus is not None:
            menu.aboutToShow.connect(self._state_bus.request_refresh)

    def _build_file_menu(self) -> None:
        file_menu = self.addMenu("&File")
        self._connect_refresh(file_menu)

        self.binder.build_menu(file_menu, ("project.new", "project.open"))

        self.menu_recent_projects = file_menu.addMenu("Open &Recent")

        file_menu.addSeparator()
        self.binder.build_menu(
            file_menu,
            (
                "dataset.open",
                "dataset.connect_database",
                None,
                "project.save",
                "project.save_as",
                None,
                "project.settings",
                None,
                "project.exit",
            ),
        )

    def _build_edit_menu(self) -> None:
        self.menu_edit = self.addMenu("&Edit")
        self._connect_refresh(self.menu_edit)
        self.binder.build_menu(self.menu_edit, ("edit.undo", "edit.redo"))

    def _build_view_menu(self) -> None:
        view_menu = self.addMenu("&View")
        self._connect_refresh(view_menu)
        self.binder.build_menu(view_menu, ("view.toggle_theme",))
        view_menu.addSeparator()

        # Dock-widget visibility toggles are added here by main_window.py
        # after DockManager has constructed the actual dock widgets --
        # unchanged from before this milestone; a dock's own
        # toggleViewAction() is per-instance state this class has no
        # reason to know about, the same category of exception "Open
        # Recent" is.
        self.menu_view = view_menu

    def _build_analysis_menu(self) -> None:
        analysis_menu = self.addMenu("&Analysis")
        self._connect_refresh(analysis_menu)
        self.binder.build_menu(analysis_menu, _ANALYSIS_MENU_ACTIONS)

    def _build_help_menu(self) -> None:
        help_menu = self.addMenu("&Help")
        self._connect_refresh(help_menu)
        self.binder.build_menu(help_menu, _HELP_MENU_ACTIONS)

    def update_recent_projects_menu(
        self, recent_paths: list[str], on_open: Callable[[str], None]
    ) -> None:
        """Rebuild the "Open Recent" submenu and wire each entry to actually open.

        Args:
            recent_paths: Paths as returned by
                :meth:`~src.services.project_service.ProjectService.get_recent_projects`,
                most recent first.
            on_open: Called with the clicked path when a recent-project
                entry is selected. Wiring happens *here*, in the same
                method that (re)builds the submenu, rather than at each of
                this method's several call sites in ``main_window.py`` --
                before this milestone, no call site did this at all,
                which is exactly why "Open Recent" was a no-op; doing it
                in one place means a future call site cannot reintroduce
                that gap by forgetting to connect.

        This clears and rebuilds the submenu each time rather than
        diffing against the previous contents, since the list is small
        (capped at 10 by
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
            # Bound as a default argument, not a closure over the loop
            # variable -- `lambda: on_open(path_str)` without the default
            # would have every action in this loop end up calling on_open
            # with whatever path_str happened to be *last* in the list,
            # the classic late-binding-closure bug.
            action.triggered.connect(
                lambda _checked=False, path=path_str: on_open(path)
            )
            self.menu_recent_projects.addAction(action)
            self.actions_recent_projects.append(action)
