# File: tests/ui/test_toolbar.py
"""Tests for the icon-rendering, registry-backed ApplicationToolBar.

The M17 acceptance criterion this backs: "Toolbar renders icons (from
M15's IconProvider) instead of text-only buttons."
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QMainWindow

import src.ui.actions.builtin_actions  # noqa: F401 -- populates the real registry
from src.ui.actions.action_binder import ActionBinder
from src.ui.theme.icon_provider import IconProvider
from src.ui.theme.tokens import DARK_TOKENS
from src.ui.toolbar import ApplicationToolBar


def test_toolbar_actions_have_real_icons_when_binder_has_a_provider(
    qapp: QApplication,
) -> None:
    window = QMainWindow()
    provider = IconProvider(DARK_TOKENS)
    binder = ActionBinder(window, provider)
    toolbar = ApplicationToolBar(window, binder)

    real_actions = [a for a in toolbar.actions() if not a.isSeparator()]
    assert real_actions, "toolbar constructed with no actions at all"
    for action in real_actions:
        assert (
            not action.icon().isNull()
        ), f"toolbar action {action.text()!r} has no icon"


def test_toolbar_reuses_the_binders_shared_qaction(qapp: QApplication) -> None:
    """The toolbar button and a menu built from the same ActionBinder must
    be the exact same QAction -- proving there is no risk of the two
    drifting out of enabled/checked/icon sync, the property the old
    (pre-milestone-17) toolbar.py's own docstring already relied on.
    """
    window = QMainWindow()
    binder = ActionBinder(window)
    toolbar = ApplicationToolBar(window, binder)

    # project.new is always the toolbar's first entry (see toolbar.py's
    # _TOOLBAR_ACTIONS) -- checking object identity against the binder's
    # own cache is the whole point, not just that a QAction with the
    # right label happens to be first.
    assert toolbar.actions()[0] is binder.action_for("project.new")


def test_toolbar_has_a_separator(qapp: QApplication) -> None:
    window = QMainWindow()
    binder = ActionBinder(window)
    toolbar = ApplicationToolBar(window, binder)
    assert any(a.isSeparator() for a in toolbar.actions())
