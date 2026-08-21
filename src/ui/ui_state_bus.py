# File: src/ui/ui_state_bus.py
"""Coalesced, no-polling notification of "workspace state may have changed."

Before this milestone, nothing in ``src/ui/`` ever called ``QAction.
setEnabled()`` at all (confirmed by grep against ``main_window.py``): every
action was permanently enabled, and each handler re-checked its own
precondition at call time, showing a message box if it did not hold (e.g.
"No project is open to save."). That is a real, working fallback -- not a
crash -- but it means a user can only discover an action is unavailable by
clicking it.

**Why a bus and not polling.** A ``QTimer`` re-running
:meth:`~src.ui.actions.action_context.ActionContext.capture` on an interval
would work, but it either recomputes uselessly most of the time (nothing
changed) or lags behind a real change by up to the timer's interval. This
class instead exposes :meth:`request_refresh`, called from the exact call
sites that mutate workspace/project state (``main_window.py``'s handler
methods, after a successful ``add_dataset``/``save_project``/etc.), and
coalesces a burst of calls within one event-loop turn into a single
:attr:`state_changed` emission via ``QTimer.singleShot(0, ...)`` -- ten
mutations in a row (e.g. reloading a project's ten recorded datasets)
produce one recompute, not ten.

A lazy safety net exists alongside this for the two cases a call site could
plausibly forget to notify: ``QMenu.aboutToShow`` and the command palette's
open event both call :meth:`request_refresh` themselves before the surface
becomes visible, so a missed call site produces at worst a stale-until-next-
interaction state rather than a permanently wrong one.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from src.core.logger import get_logger

_logger = get_logger(__name__)


class UiStateBus(QObject):
    """Emits :attr:`state_changed` once per coalesced burst of mutations.

    Args:
        parent: Optional owning ``QObject``, typically the ``MainWindow``
            that owns this bus for its lifetime.

    Signals:
        state_changed: Emitted with no arguments -- a listener (typically
            :meth:`~src.ui.actions.action_binder.ActionBinder.
            refresh_enablement`'s caller) re-captures a fresh
            :class:`~src.ui.actions.action_context.ActionContext` itself
            rather than this signal carrying one, since the bus has no
            reference to the services a context is built from (it is a
            pure Qt plumbing class, not a workspace-aware one) and
            shouldn't need one just to notify "something changed."
    """

    state_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending = False

    def request_refresh(self) -> None:
        """Ask for a :attr:`state_changed` emission on the next event-loop turn.

        Safe to call any number of times within one turn -- only the first
        call in a burst schedules the ``singleShot`` timer; subsequent
        calls before it fires are no-ops, which is the coalescing itself.
        """
        if self._pending:
            return
        self._pending = True
        QTimer.singleShot(0, self._emit_state_changed)

    def _emit_state_changed(self) -> None:
        self._pending = False
        self.state_changed.emit()
