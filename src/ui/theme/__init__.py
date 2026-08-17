# File: src/ui/theme/__init__.py
"""The design-token layer: one definition of colour, space, and type.

Milestone 15 replaced two hand-maintained QSS files
(``resources/styles/dark.qss`` and ``light.qss``, twelve literal hex values
each, no shared vocabulary) with the pipeline in this package:

``tokens`` (semantic values, WCAG-validated)
    -> ``qss_compiler`` (substituted into one template)
    -> :class:`~src.ui.theme_manager.ThemeManager` (applied to the app)

``icon_provider`` and ``plotly_theme`` consume the same tokens for the two
surfaces a stylesheet cannot reach -- SVG icon strokes and Plotly figures --
which is why :class:`~src.ui.theme_manager.ThemeManager` emits
``theme_changed`` rather than relying on QSS cascade alone.

``contrast`` is the reason to trust any of it: every pairing these tokens
produce is asserted against WCAG 2.2 Level AA by the test suite, so a token
edit that breaks legibility fails CI instead of shipping.
"""

from __future__ import annotations
