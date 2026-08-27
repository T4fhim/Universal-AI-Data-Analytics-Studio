# File: tests/ui/help/test_help_router.py
"""Unit coverage for resolve_help_anchor's parent-chain (and QAction) walk.

Complements tests/ui/help/test_manual_anti_rot.py -- that module proves every real anchor
*resolves to a page*; this one proves the *mechanism that finds an anchor from a focused
widget* actually walks correctly, independent of which anchors exist in the manual.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QToolBar, QToolButton, QWidget

from src.ui.a11y.accessible import describe
from src.ui.help.help_router import resolve_help_anchor


def test_returns_none_for_a_widget_with_no_stamped_anchor_anywhere(qapp) -> None:
    widget = QWidget()
    assert resolve_help_anchor(widget) is None


def test_returns_none_for_none() -> None:
    assert resolve_help_anchor(None) is None


def test_finds_the_anchor_stamped_directly_on_the_widget(qapp) -> None:
    widget = QWidget()
    describe(widget, name="Test widget", help_anchor="index")
    assert resolve_help_anchor(widget) == "index"


def test_finds_an_ancestors_anchor_when_the_focused_widget_has_none(qapp) -> None:
    parent = QWidget()
    describe(parent, name="Parent", help_anchor="settings")
    child = QWidget(parent)
    assert resolve_help_anchor(child) == "settings"


def test_the_nearest_ancestor_wins_over_a_more_distant_one(qapp) -> None:
    grandparent = QWidget()
    describe(grandparent, name="Grandparent", help_anchor="settings")
    parent = QWidget(grandparent)
    describe(parent, name="Parent", help_anchor="view/theme")
    child = QWidget(parent)
    assert resolve_help_anchor(child) == "view/theme"


def test_a_toolbutton_checks_its_represented_action_first(qapp) -> None:
    toolbar = QToolBar()
    action = QAction("Do the thing", toolbar)
    action.setProperty("helpAnchor", "edit/undo")
    toolbar.addAction(action)
    button = toolbar.widgetForAction(action)
    assert isinstance(button, QToolButton)
    assert resolve_help_anchor(button) == "edit/undo"


def test_a_toolbutton_falls_back_to_its_own_property_if_the_action_has_none(
    qapp,
) -> None:
    toolbar = QToolBar()
    describe(toolbar, name="Toolbar", help_anchor="index")
    action = QAction("Do the thing", toolbar)  # no helpAnchor property of its own
    toolbar.addAction(action)
    button = toolbar.widgetForAction(action)
    assert resolve_help_anchor(button) == "index"


def test_an_open_menus_active_action_is_checked(qapp) -> None:
    menu = QMenu()
    action = menu.addAction("Item")
    action.setProperty("helpAnchor", "report/generate")
    menu.setActiveAction(action)
    assert resolve_help_anchor(menu) == "report/generate"
