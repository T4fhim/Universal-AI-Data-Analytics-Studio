# File: tests/ui/test_menu_bar.py
"""Tests for the declarative, registry-backed ApplicationMenuBar.

No pre-milestone-17 equivalent of this file existed -- menu_bar.py had
zero test coverage before this milestone, part of the broader "no UI test
infrastructure at all" gap milestone 15's harness closed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow, QWidgetAction

import src.ui.actions.builtin_actions  # noqa: F401 -- populates the real registry
from src.ui.actions.action_binder import ActionBinder
from src.ui.menu_bar import ApplicationMenuBar
from src.ui.widgets.empty_state import EmptyState


def _menu_titles(menu_bar: ApplicationMenuBar) -> set[str]:
    return {action.text().replace("&", "") for action in menu_bar.actions()}


def test_edit_menu_has_undo_and_redo(qapp: QApplication) -> None:
    """Milestone 23 reintroduces the Edit menu -- removed in milestone 17 because Undo/Redo
    were connected to nothing, restored now that they have real semantics (see
    src/ui/command_stack.py's own docstring).
    """
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)
    assert "Edit" in _menu_titles(menu_bar)
    assert {a.text().replace("&", "") for a in menu_bar.menu_edit.actions()} == {
        "Undo",
        "Redo",
    }


def test_expected_menus_exist(qapp: QApplication) -> None:
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)
    assert _menu_titles(menu_bar) == {"File", "Edit", "View", "Analysis", "Help"}


def test_recent_projects_menu_shows_placeholder_when_empty(
    qapp: QApplication,
) -> None:
    """Milestone 27: the old disabled "(No recent projects)" QAction text is replaced by a
    real EmptyState hosted in a QWidgetAction -- see update_recent_projects_menu's own comment.
    """
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)

    menu_bar.update_recent_projects_menu([], on_open=lambda path: None)

    actions = menu_bar.menu_recent_projects.actions()
    assert len(actions) == 1
    assert actions[0].isEnabled() is False
    assert isinstance(actions[0], QWidgetAction)
    empty_state = actions[0].defaultWidget()
    assert isinstance(empty_state, EmptyState)
    assert empty_state.accessibleName() == "No Recent Projects"


def test_recent_project_click_calls_on_open_with_its_path(
    qapp: QApplication,
) -> None:
    """The acceptance criterion this test exists for: "Recent Projects
    actually opens a project when clicked (was previously a no-op)."
    """
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)

    opened_paths: list[str] = []
    menu_bar.update_recent_projects_menu(
        ["/path/to/a.uads.json", "/path/to/b.uads.json"],
        on_open=opened_paths.append,
    )

    actions = menu_bar.menu_recent_projects.actions()
    assert len(actions) == 2

    actions[1].trigger()  # click the second entry
    assert opened_paths == ["/path/to/b.uads.json"]


def test_recent_projects_rebuild_does_not_confuse_which_path_each_action_opens(
    qapp: QApplication,
) -> None:
    """Regression guard for the classic late-binding-closure bug: without
    binding path_str as a default argument, every action in the loop would
    end up calling on_open with whichever path was last in the list.
    """
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)

    opened_paths: list[str] = []
    menu_bar.update_recent_projects_menu(
        [f"/path/{i}.uads.json" for i in range(5)],
        on_open=opened_paths.append,
    )

    actions = menu_bar.menu_recent_projects.actions()
    for action in actions:
        action.trigger()

    assert opened_paths == [f"/path/{i}.uads.json" for i in range(5)]


def test_menu_bar_exposes_the_binder(qapp: QApplication) -> None:
    window = QMainWindow()
    binder = ActionBinder(window)
    menu_bar = ApplicationMenuBar(window, binder)
    assert menu_bar.binder is binder
