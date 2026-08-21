# File: src/ui/actions/__init__.py
"""The single source of truth every action-presenting surface derives from.

Before milestone 17, ``menu_bar.py`` constructed ``QAction`` objects ad hoc
and exposed each as a named attribute (``self.action_save_project``), which
``main_window.py`` connected by hand. Nothing enforced that a constructed
action actually got a handler -- ``Edit > Undo``/``Redo`` and the
"Open Recent" submenu were exactly this: real, visible menu items connected
to nothing, found by the audit behind this whole overhaul.

This package fixes that by splitting "what actions exist" from "what a
window does when one fires" into three pieces, mirroring
:mod:`src.visualization.chart_registry`'s registration shape:

- :mod:`~src.ui.actions.action_registry` -- Qt-free, import-time-populated
  data (:class:`~src.ui.actions.action_registry.ActionSpec`). No handler and
  no ``QIcon`` live here: handlers are bound methods of a ``MainWindow``
  that does not exist at import time, and constructing a ``QIcon`` before
  ``QApplication`` exists is undefined behavior -- putting either in the
  registration would force per-window mutable state onto what should stay
  pure data.
- :mod:`~src.ui.actions.action_context` -- :class:`ActionContext`, an
  immutable snapshot of "what can the user do right now," captured in
  O(columns), never O(rows).
- :mod:`~src.ui.actions.action_binder` -- the per-window Qt side.
  :meth:`~src.ui.actions.action_binder.ActionBinder.assert_all_bound` turns
  "every registered action has a real handler" from a code-review hope into
  a startup-time hard failure.

Alongside the registry: :mod:`src.ui.actions.builtin_actions` registers
every action that predates this milestone (constructing this list at
import time, matching how :mod:`~src.visualization.chart_registry` seeds
its own built-ins).
"""

from __future__ import annotations
