# File: uadas_core/actions/__init__.py
"""Qt-free action catalogue, lifted from :mod:`src.ui.actions` in the
desktop->web transition's Phase 2.1.

The "what actions exist / what can the user do right now" data, split from
the per-window Qt binding -- ``action_binder`` (constructs ``QAction``
objects, asserts every spec has a handler) stays under ``src/ui/`` with the
shell.

* :mod:`~uadas_core.actions.action_registry` -- import-time-populated
  ``ActionSpec`` data; no handler and no ``QIcon`` (both need a live
  ``MainWindow`` / ``QApplication``).
* :mod:`~uadas_core.actions.action_context` -- ``ActionContext``, an
  immutable O(columns) snapshot of what the user can do right now.
* :mod:`~uadas_core.actions.builtin_actions` -- registers the pre-existing
  action set at import time (import for its side effect).
"""

from __future__ import annotations
