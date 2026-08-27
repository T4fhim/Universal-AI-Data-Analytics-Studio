# File: src/plugins/plugin_manager.py
"""Session-wide plugin state: what's discovered, what's enabled, and how to toggle it.

:class:`PluginManager` is registered as a singleton in
:mod:`~src.core.bootstrap`, the same way
:class:`~src.services.workspace_service.WorkspaceService` and every
other session-wide service is — see that module's own docstring for
why services are constructed once and shared via the dependency
container rather than built ad hoc. :mod:`src.ui.main_window` resolves
this instance to build a "Plugins" settings panel: list installed,
enable/disable, show errors, per the milestone 12 plan.
"""

from __future__ import annotations

from pathlib import Path

from src.cleaning.operation_registry import unregister_operation
from src.core.logger import get_logger
from src.plugins.plugin_loader import LoadedPlugin, discover_plugins
from src.readers.reader_registry import unregister_reader
from src.visualization.chart_registry import unregister_chart

_logger = get_logger(__name__)


class PluginManager:
    """Owns the discovered plugin set and lets individual plugins be enabled/disabled.

    Args:
        search_paths: Directories to scan for plugins — normally
            :attr:`~src.core.config.AppConfig.plugin_search_paths`.
        enabled: Whether plugin loading is turned on at all — normally
            :attr:`~src.core.config.AppConfig.plugins_enabled`. When
            ``False``, :meth:`load_plugins` discovers and records
            nothing (not even to report "0 plugins found" as an
            error — plugins being off entirely is a normal,
            deliberate configuration state).
        disabled_plugin_names: Plugin names the user has previously
            chosen not to load, honored on the very first
            :meth:`load_plugins` call so a disabled plugin has zero
            side effects at startup (never imported at all), not just
            zero registered classes.
    """

    def __init__(
        self,
        search_paths: list[str],
        enabled: bool = True,
        disabled_plugin_names: set[str] | None = None,
    ) -> None:
        self._search_paths = search_paths
        self._enabled = enabled
        self._disabled_names: set[str] = set(disabled_plugin_names or ())
        self._loaded: list[LoadedPlugin] = []

    def load_plugins(self) -> list[LoadedPlugin]:
        """Discover and register every non-disabled plugin under the configured search paths.

        Safe to call more than once — each call first unregisters
        everything the previous scan's plugins registered (see
        :meth:`_unregister_all`), so a plugin added, removed, or
        edited on disk between calls is picked up correctly rather
        than accumulating stale registrations.
        """
        self._unregister_all()

        if not self._enabled:
            self._loaded = []
            _logger.info("Plugin loading is disabled (plugins.enabled=False).")
            return self._loaded

        self._loaded = discover_plugins(
            [Path(p) for p in self._search_paths], skip_names=self._disabled_names
        )
        _logger.info(
            "Plugin discovery complete: %d plugin(s) found, %d loaded cleanly.",
            len(self._loaded),
            sum(1 for p in self._loaded if p.loaded_successfully),
        )
        return self._loaded

    def list_plugins(self) -> list[LoadedPlugin]:
        """Return every plugin discovered on the most recent :meth:`load_plugins` call."""
        return list(self._loaded)

    def is_disabled(self, plugin_name: str) -> bool:
        return plugin_name in self._disabled_names

    def disable_plugin(self, plugin_name: str) -> None:
        """Mark a plugin disabled and unregister everything it currently provides.

        Takes effect immediately (the plugin's classes stop being
        reachable through the shared registries in this same running
        session) — not merely on the next restart. Safe to call for a
        plugin name that was never loaded or is already disabled.
        """
        self._disabled_names.add(plugin_name)
        for loaded in self._loaded:
            if loaded.manifest.name == plugin_name:
                self._unregister_plugin(loaded)
        _logger.info("Plugin disabled: %s", plugin_name)

    def enable_plugin(self, plugin_name: str) -> None:
        """Mark a plugin enabled again and reload it if it's on a configured search path.

        Re-running the full :meth:`load_plugins` scan (rather than
        re-importing just this one plugin) is the simplest way to
        restore its registrations without duplicating
        ``discover_plugins``'s own loading logic here — the cost of a
        full re-scan is not a concern given how infrequently a user
        toggles a plugin.
        """
        self._disabled_names.discard(plugin_name)
        self.load_plugins()
        _logger.info("Plugin enabled: %s", plugin_name)

    def _unregister_plugin(self, loaded: LoadedPlugin) -> None:
        for category, names in loaded.registered.items():
            classes = loaded.registered_classes.get(category, [])
            if category == "readers":
                for reader_class in classes:
                    unregister_reader(reader_class)
            elif category == "cleaning_operations":
                for name in names:
                    unregister_operation(name)
            elif category == "charts":
                for name in names:
                    unregister_chart(name)

    def _unregister_all(self) -> None:
        for loaded in self._loaded:
            self._unregister_plugin(loaded)
