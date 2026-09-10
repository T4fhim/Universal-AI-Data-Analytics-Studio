# File: uadas_core/theme/__init__.py
"""Qt-free design tokens: the semantic colour/space/type vocabulary and the
two token consumers that need no ``QApplication``.

Lifted from :mod:`src.ui.theme` in the desktop->web transition's Phase 2.1.
The Qt-bound members of that package stay behind under ``src/ui/`` until the
shell is retired: ``qss_compiler`` (emits a Qt stylesheet), ``icon_provider``
(builds ``QIcon`` objects), and :class:`~src.ui.theme_manager.ThemeManager`
(applies stylesheets at the ``QApplication`` level).

What lives here:

* :mod:`~uadas_core.theme.tokens` -- :class:`ThemeTokens` and the built-in
  dark/light sets, each WCAG-2.2-validated by ``contrast`` plus the suite.
* :mod:`~uadas_core.theme.contrast` -- the WCAG contrast math that a token
  edit is checked against, so a change that breaks legibility fails CI.
* :mod:`~uadas_core.theme.plotly_theme` -- turns a :class:`ThemeTokens` into
  a Plotly layout/config, the one figure surface a Qt stylesheet cannot
  reach.
"""

from __future__ import annotations
