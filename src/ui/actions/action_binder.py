# File: src/ui/actions/action_binder.py
"""The per-window Qt side of the action registry.

:class:`ActionBinder` is where an :class:`~src.ui.actions.action_registry.
ActionSpec` finally becomes a real ``QAction`` -- constructed lazily, on
first reference (from either :meth:`bind`, :meth:`build_menu`, or
:meth:`action_for`), and cached so the menu bar, the toolbar, and the
command palette all share the *same* ``QAction`` object for a given
``action_id``. That sharing is what makes "selecting an action in the
command palette invokes the same handler the menu/toolbar would" true by
construction rather than by convention: there is only ever one ``QAction``
per id to trigger.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QWidget

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.ui.actions.action_registry import get_action, list_actions
from src.ui.theme.icon_provider import IconProvider

if TYPE_CHECKING:
    from src.ui.actions.action_context import ActionContext

_logger = get_logger(__name__)


class ActionBinder(QObject):
    """Builds, binds, and keeps enabled/disabled every window's ``QAction``s.

    Args:
        parent_window: The window whose actions these are -- passed as both
            this ``QObject``'s Qt parent and each constructed ``QAction``'s
            parent, matching how ``menu_bar.py`` parented its actions
            before this milestone.
        icon_provider: Recolors each action's ``icon_name`` for the active
            theme. Optional so this class stays constructible (and its
            enablement/binding logic testable) without a live
            ``QApplication`` -- a caller with no theming concern, e.g. a
            unit test, can pass ``None`` and every action simply has no
            icon.
    """

    def __init__(
        self, parent_window: QWidget, icon_provider: IconProvider | None = None
    ) -> None:
        super().__init__(parent_window)
        self._parent_window = parent_window
        self._icon_provider = icon_provider
        self._actions: dict[str, QAction] = {}
        self._handlers: dict[str, Callable[[], None]] = {}
        if icon_provider is not None:
            # A QIcon already handed to a QAction is a value copy -- the
            # icon cache being cleared and repopulated on a theme change
            # does not, on its own, update anything already on screen.
            # This is the other half of that: re-setIcon every bound
            # action whenever the provider announces a new theme.
            icon_provider.icons_changed.connect(self._refresh_icons)

    def _get_or_create_action(self, action_id: str) -> QAction:
        existing = self._actions.get(action_id)
        if existing is not None:
            return existing

        spec = get_action(action_id)
        action = QAction(spec.label, self._parent_window)
        if spec.shortcut:
            action.setShortcut(QKeySequence(spec.shortcut))
        if spec.status_tip:
            action.setStatusTip(spec.status_tip)
        action.setCheckable(spec.checkable)
        if self._icon_provider is not None and spec.icon_name:
            action.setIcon(self._icon_provider.icon(spec.icon_name))

        self._actions[action_id] = action
        return action

    def bind(self, action_id: str, handler: Callable[[], None]) -> QAction:
        """Connect ``handler`` to ``action_id``'s ``triggered`` signal.

        Constructs the underlying ``QAction`` if nothing has referenced
        ``action_id`` yet -- callable before or after :meth:`build_menu`,
        in either order, since both funnel through the same lazily-created
        action.

        Returns:
            The bound ``QAction``, for a caller that needs to add it
            somewhere :meth:`build_menu` does not already cover (e.g.
            ``toolbar.py`` via :meth:`action_for`).
        """
        action = self._get_or_create_action(action_id)
        action.triggered.connect(handler)
        self._handlers[action_id] = handler
        return action

    def action_for(self, action_id: str) -> QAction:
        """Return the shared ``QAction`` for ``action_id``, creating it if needed.

        This is what ``toolbar.py`` calls to reuse the exact ``QAction``
        ``menu_bar.py`` already built (or will build), rather than
        constructing a second, independent action for the same operation --
        the same reuse the pre-milestone-17 toolbar already relied on, just
        routed through this class instead of a direct
        ``menu_bar.action_save_project`` attribute reference.
        """
        return self._get_or_create_action(action_id)

    def build_menu(self, menu: QMenu, action_ids: Iterable[str | None]) -> None:
        """Populate ``menu`` with one action per id, in the given order.

        Args:
            action_ids: A ``None`` entry inserts a separator -- lets a
                caller pass one flat, declarative list (matching the
                plan's "menu_bar.py rewritten as declarative id lists")
                instead of interleaving ``menu.addSeparator()`` calls by
                hand.
        """
        for action_id in action_ids:
            if action_id is None:
                menu.addSeparator()
                continue
            menu.addAction(self._get_or_create_action(action_id))

    def refresh_enablement(self, context: ActionContext) -> None:
        """Recompute every bound action's enabled state against ``context``.

        Called from :mod:`src.ui.ui_state_bus`'s coalesced recompute, not
        from a timer -- see that module's docstring for why polling was
        rejected. Only actions that have actually been constructed
        (referenced via :meth:`bind`/:meth:`build_menu`/:meth:`action_for`)
        are touched; an ``ActionSpec`` nothing has referenced yet has no
        ``QAction`` to enable or disable.
        """
        for action_id, action in self._actions.items():
            spec = get_action(action_id)
            enabled = all(context.satisfies(req) for req in spec.requires)
            if enabled and spec.predicate is not None:
                enabled = spec.predicate(context)
            action.setEnabled(enabled)

    def assert_all_bound(self) -> None:
        """Raise if any registered action has never been bound to a handler.

        This is the check that turns the pre-milestone-17 class of bug --
        ``Edit > Undo``/``Redo`` and "Open Recent" existing as real,
        clickable, connected-to-nothing menu items -- into a startup-time
        :class:`~src.core.exceptions.ServiceError` instead of something a
        code review has to remember to catch. Checked against
        :func:`~src.ui.actions.action_registry.list_actions` (every
        *registered* action), not just ``self._actions`` (every
        *constructed* one) -- an action that was registered but never
        referenced by :meth:`bind`/:meth:`build_menu`/:meth:`action_for` at
        all is exactly as dead as one that was built but never connected.

        Raises:
            ServiceError: Naming every unbound action id, sorted for a
                deterministic message.
        """
        missing = sorted(
            action_id for action_id in list_actions() if action_id not in self._handlers
        )
        if missing:
            raise ServiceError(
                f"The following registered actions have no bound handler: "
                f"{missing}. Call ActionBinder.bind(action_id, handler) for "
                f"each one before the window finishes constructing."
            )

    def _refresh_icons(self) -> None:
        if self._icon_provider is None:
            return
        for action_id, action in self._actions.items():
            spec = get_action(action_id)
            if spec.icon_name:
                action.setIcon(self._icon_provider.icon(spec.icon_name))
