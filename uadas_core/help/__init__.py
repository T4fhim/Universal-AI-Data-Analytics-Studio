# File: uadas_core/help/__init__.py
"""Qt-free in-app manual model, lifted from :mod:`src.ui.help` in the
desktop->web transition's Phase 2.1.

* :mod:`~uadas_core.help.manual_index` -- ``ManualIndex``, a pure anchor ->
  page resolver over ``docs/manual/*.md`` frontmatter; used identically by
  the running application and by ``scripts/preview_manual.py``.
* :mod:`~uadas_core.help.manual_renderer` -- ``ManualRenderer``, compiles a
  resolved page's Markdown into the HTML subset ``QTextBrowser`` renders,
  via ``markdown_it``.

``help_router.resolve_help_anchor`` needs a live ``QApplication.focusWidget()``
and stays under ``src/ui/`` with the shell, as do the F1 controller and the
dialog that displays a rendered page.
"""

from __future__ import annotations
