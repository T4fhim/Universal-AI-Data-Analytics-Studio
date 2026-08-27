# File: src/plugins/__init__.py
"""Milestone 12: dynamic plugin discovery and registration.

:mod:`~src.plugins.plugin_manifest` defines the on-disk manifest
format a plugin declares itself with; :mod:`~src.plugins.plugin_loader`
scans configured search paths for plugins and validates each provided
class against the relevant existing ``Base*`` ABC before it is usable;
:mod:`~src.plugins.plugin_manager` is the session-wide service
(registered in :mod:`~src.core.bootstrap`) that owns the discovered
set and lets a "Plugins" settings panel enable/disable individual
plugins without restarting the application.
"""

from __future__ import annotations
