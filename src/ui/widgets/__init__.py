# File: src/ui/__init__.py
"""Presentation layer: main window, menus, docks, dialogs, and widgets.

Like ``uadas_core.services``, this package depends on ``uadas_core.core`` and
``uadas_core.services`` but nothing in ``uadas_core.core`` or ``uadas_core.services``
depends back on it — the presentation layer sits above both in this
project's layered architecture (Application -> Service -> Business
Logic -> Data -> Presentation -> Plugin), so it can freely import from
either without creating a circular dependency in either direction.
"""
