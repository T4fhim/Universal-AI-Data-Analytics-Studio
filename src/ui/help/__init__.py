# File: src/ui/help/__init__.py
"""The in-app manual and F1 help routing (milestone 29).

Foundation layer, alongside :mod:`src.ui.theme`, :mod:`src.ui.a11y`, and
:mod:`src.ui.actions` -- nothing here depends on :mod:`src.ui.workbench`,
:mod:`src.ui.controllers`, or any other non-leaf UI package (see
``tests/ui/test_import_layering.py``, which lists ``"help"`` alongside those three).

Two independent pieces live here:

* :class:`~uadas_core.help.manual_index.ManualIndex` -- a pure, Qt-free anchor resolver over
  ``docs/manual/*.md``. Every manual page's YAML frontmatter declares the anchor(s) it answers
  for; this class builds and caches the anchor -> page mapping once, so both the running
  application and ``scripts/preview_manual.py`` (an authoring tool, not part of the shipped
  application) read from the exact same source of truth.
* :class:`~uadas_core.help.manual_renderer.ManualRenderer` -- compiles a resolved page's Markdown
  body into the HTML subset ``QTextBrowser`` supports, via ``markdown_it`` (already a project
  dependency for this exact purpose -- see ``requirements.txt``'s own comment).

:func:`~src.ui.help.help_router.resolve_help_anchor` is the third piece: given a focused widget,
it walks the widget's parent chain (and, for a toolbar button or an open menu, the ``QAction``
it represents) looking for the ``helpAnchor`` dynamic property :func:`~src.ui.a11y.accessible.
describe` stamps. It is a free function, not a class, for the same reason
:mod:`src.ui.a11y.accessible` is all free functions -- see that package's own docstring.

The actual F1 keyboard shortcut and the dialog that displays a rendered page are **not** here:
those need :class:`~src.ui.controllers`-shaped wiring (a live ``QApplication.focusWidget()``,
a parent window to own the dialog) that would pull non-leaf UI packages into this one. See
``src/ui/controllers/help_controller.py`` and ``src/ui/dialogs/manual_dialog.py``.
"""

from __future__ import annotations
