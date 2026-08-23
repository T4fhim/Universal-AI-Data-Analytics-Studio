# File: src/ui/help/help_router.py
"""Resolves which manual anchor F1 should open, from wherever keyboard focus currently is.

:func:`resolve_help_anchor` is the function :func:`~src.ui.a11y.accessible.describe`'s own
module docstring already promises exists ("stamps a ``helpAnchor`` dynamic property ... which
:func:`src.ui.help.help_router.resolve_help_anchor` walks up the parent chain to answer F1") --
this module is where that promise is kept.

**Two things carry a ``helpAnchor`` property, not one.** Every widget :func:`~src.ui.a11y.
accessible.describe` was called with a ``help_anchor`` keyword has the property directly (a
:class:`~src.ui.workbench.stage_page.StagePage`'s own run button, or the page itself -- see
that class's own docstring for why the page container is stamped too, not just its buttons).
But a menu item and a toolbar button do not carry their own identity the way an ordinary
``QWidget`` does: a ``QToolBar``'s buttons and a ``QMenu``'s items are views onto a ``QAction``,
and it is the ``QAction`` (built once per :class:`~src.ui.actions.action_registry.ActionSpec`
by :class:`~src.ui.actions.action_binder.ActionBinder`) that actually carries the stamped
property -- so this function checks the focused widget's associated ``QAction`` first, falling
through to the widget's own property only if there is no such action.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMenu, QToolButton, QWidget

from src.ui.a11y.accessible import HELP_ANCHOR_PROPERTY


def _anchor_from_property(obj) -> str | None:
    value = obj.property(HELP_ANCHOR_PROPERTY)
    return value if isinstance(value, str) and value else None


def resolve_help_anchor(widget: QWidget | None) -> str | None:
    """Walk ``widget``'s parent chain looking for a stamped ``helpAnchor`` property.

    Args:
        widget: Typically ``QApplication.focusWidget()`` -- the widget keyboard focus is
            currently on when F1 is pressed. ``None`` (nothing has focus) is a valid input and
            simply returns ``None`` immediately, rather than requiring every caller to guard
            against it first.

    Returns:
        The nearest ancestor's (or its represented ``QAction``'s) ``helpAnchor`` value, or
        ``None`` if neither ``widget`` nor any of its ancestors carries one. Callers decide the
        final fallback -- see :meth:`~src.ui.controllers.help_controller.HelpController.
        show_help_for_focus`, which falls back to the workbench's currently visible stage page,
        then to the manual's own ``"index"`` page, matching the plan's documented fallback
        chain (``resolve_help_anchor`` -> active ``StagePage`` -> ``"index"``).
    """
    node: QWidget | None = widget
    while node is not None:
        action = None
        if isinstance(node, QToolButton):
            action = node.defaultAction()
        elif isinstance(node, QMenu):
            action = node.activeAction()
        if action is not None:
            anchor = _anchor_from_property(action)
            if anchor is not None:
                return anchor

        anchor = _anchor_from_property(node)
        if anchor is not None:
            return anchor

        node = node.parentWidget()
    return None
