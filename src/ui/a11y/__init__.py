# File: src/ui/a11y/__init__.py
"""Accessibility helpers, applied at widget-construction time.

The application reached milestone 14 with thirteen accessibility API calls in
the entire repository, nine of which were menu keyboard shortcuts -- no
``setAccessibleName``, no ``setTabOrder``, no focus policy management, and no
focus ring on any button, list, tree, or tab. This package is how that stops
being true, and stops being true *by default* rather than by remembering.

The target is WCAG 2.2 Level AA, the standard EN 301 549 references for
non-web software.

Deliberately plain functions rather than a mixin: a mixin has to enter the
MRO of every Qt base class the UI uses, and PySide6 multiple inheritance with
Qt C++ bases is fragile -- only one Qt base is permitted, metaclass conflicts
are easy to trigger, and ``super().__init__`` ordering bugs are hard to
diagnose. A free function taking a widget has none of those problems and no
less reach.
"""

from __future__ import annotations
