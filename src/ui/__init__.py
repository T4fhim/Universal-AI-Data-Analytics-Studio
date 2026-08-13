# File: src/ui/__init__.py
"""Presentation layer: main window, menus, docks, dialogs, and widgets.

Like ``src.services``, this package depends on ``src.core`` and
``src.services`` but nothing in ``src.core`` or ``src.services``
depends back on it — the presentation layer sits above both in this
project's layered architecture (Application -> Service -> Business
Logic -> Data -> Presentation -> Plugin), so it can freely import from
either without creating a circular dependency in either direction.
"""
