# File: uadas_core/a11y/__init__.py
"""Qt-free accessibility data, lifted from :mod:`src.ui.a11y` in the
desktop->web transition's Phase 2.1.

Only ``contrast_manifest`` -- the authoritative list of foreground/background
token pairings that must meet WCAG 2.2 Level AA, consumed by
:mod:`~uadas_core.theme.contrast`'s checker and by the test suite -- is
Qt-free and belongs here. The rest of :mod:`src.ui.a11y` stays under
``src/ui/`` with the shell: ``accessible`` (``setAccessibleName`` / focus
helpers on live widgets), ``audit`` (a ``QWidget``-tree walker), and
``rules`` (consumes both).
"""

from __future__ import annotations
