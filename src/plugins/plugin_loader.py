# File: src/plugins/plugin_loader.py
"""Scans configured search paths for plugins and validates what each one provides.

:func:`discover_plugins` is the module's one entry point. It never
raises for an individual plugin's problems — a malformed manifest, an
import error, a provided class that doesn't subclass the right
``Base*`` ABC — since one broken plugin must not prevent every other
plugin (or the application itself) from starting; see the milestone
12 plan's own framing: "bad plugin = skipped + logged, not a
BootstrapError." Each problem is instead recorded on the returned
:class:`LoadedPlugin` so a "Plugins" settings panel can show the user
exactly what went wrong.
"""

from __future__ import annotations

import importlib
import sys
from dataclasses import dataclass, field
from pathlib import Path

from src.cleaning.base_operation import BaseOperation
from src.cleaning.operation_registry import register_operation
from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.plugins.plugin_manifest import PluginManifest
from src.readers.base_reader import BaseReader
from src.readers.reader_registry import register_reader
from src.visualization.base_chart import BaseChart
from src.visualization.chart_registry import ChartRegistration, register_chart

_logger = get_logger(__name__)

_MANIFEST_FILENAME = "plugin.json"

# Category name -> the Base* ABC a provided class must subclass. Kept
# here rather than in plugin_manifest.py since that module only owns
# the manifest *format*; validating against these live ABCs is this
# loader's job, and importing every Base* class into the manifest
# module would give it dependencies it otherwise has no reason to
# carry.
_CATEGORY_BASE_CLASSES: dict[str, type] = {
    "readers": BaseReader,
    "cleaning_operations": BaseOperation,
    "charts": BaseChart,
}


@dataclass
class LoadedPlugin:
    """The outcome of attempting to load one plugin.

    Attributes:
        manifest: The plugin's parsed manifest.
        registered: Category -> list of registry names this plugin
            successfully registered — what a "Plugins" settings panel
            displays.
        registered_classes: Category -> list of the actual classes
            this plugin successfully registered, parallel to
            ``registered`` — what
            :class:`~src.plugins.plugin_manager.PluginManager` walks
            to unregister everything if the plugin is later disabled,
            since readers are registered (and must be unregistered) by
            class object, not by name.
        errors: Human-readable problems encountered for this specific
            plugin (a malformed ``provides`` entry, an import failure,
            a class that isn't the right ``Base*`` subtype, a
            registry-name collision). An otherwise-successful plugin
            can still have partial errors here if only *some* of its
            provided classes failed — the plugin is not all-or-
            nothing.
        loaded_successfully: ``True`` if zero errors occurred;
            ``False`` otherwise. A plugin providing nothing at all (an
            empty ``provides``) counts as loaded successfully — an
            unusual but not invalid manifest.
    """

    manifest: PluginManifest
    registered: dict[str, list[str]] = field(default_factory=dict)
    registered_classes: dict[str, list[type]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def loaded_successfully(self) -> bool:
        return not self.errors


def _registry_name_for(module_path: str, class_name: str) -> str:
    """Derive a registry key from a provides entry, e.g. 'my_plugin.readers:Foo' -> 'my_plugin_foo'.

    Namespaced with the plugin's top-level module segment so two
    different plugins providing a same-named class (``Foo`` in two
    unrelated packages) do not collide in the shared registry purely
    by coincidence of class naming.
    """
    top_level_module = module_path.split(".")[0]
    return f"{top_level_module}_{class_name}".lower()


def _load_provided_class(entry: str) -> type:
    """Import and return the class named by a 'module.path:ClassName' provides entry.

    Raises:
        ServiceError: If ``entry`` is not in ``module:Class`` form, the
            module cannot be imported, or the class does not exist in
            it.
    """
    if ":" not in entry:
        raise ServiceError(
            f"Invalid provides entry {entry!r} — expected 'module.path:ClassName'."
        )
    module_path, class_name = entry.rsplit(":", 1)

    try:
        module = importlib.import_module(module_path)
    except Exception as exc:
        raise ServiceError(f"Could not import '{module_path}': {exc}") from exc

    if not hasattr(module, class_name):
        raise ServiceError(f"Module '{module_path}' has no attribute '{class_name}'.")
    return getattr(module, class_name)


def _load_one_plugin(plugin_dir: Path) -> LoadedPlugin:
    """Load and register a single plugin directory's manifest and provided classes."""
    manifest = PluginManifest.load(plugin_dir / _MANIFEST_FILENAME)
    result = LoadedPlugin(manifest=manifest)

    for category, entries in manifest.provides.items():
        base_class = _CATEGORY_BASE_CLASSES[category]
        for entry in entries:
            try:
                provided_class = _load_provided_class(entry)
            except ServiceError as exc:
                result.errors.append(f"{category}/{entry}: {exc}")
                continue

            if not (
                isinstance(provided_class, type)
                and issubclass(provided_class, base_class)
            ):
                result.errors.append(
                    f"{category}/{entry}: "
                    f"{getattr(provided_class, '__name__', provided_class)!r} "
                    f"does not subclass {base_class.__name__}."
                )
                continue

            registry_name = _registry_name_for(*entry.rsplit(":", 1))
            try:
                if category == "readers":
                    register_reader(provided_class)
                elif category == "cleaning_operations":
                    register_operation(registry_name, provided_class)
                elif category == "charts":
                    # A plugin manifest has no way to declare a
                    # chart's required/optional column fields — the
                    # dialog's column picker cannot be built for it
                    # automatically, so every plugin chart registers
                    # as dialog_compatible=False (AI-tool-only) until
                    # a future milestone extends the manifest format
                    # to describe fields, same limitation
                    # advanced_charts.py's Treemap/Radar already have.
                    register_chart(
                        registry_name,
                        ChartRegistration(provided_class, (), dialog_compatible=False),
                    )
            except ServiceError as exc:
                result.errors.append(f"{category}/{entry}: {exc}")
                continue

            result.registered.setdefault(category, []).append(registry_name)
            result.registered_classes.setdefault(category, []).append(provided_class)

    if result.loaded_successfully:
        _logger.info(
            "Loaded plugin '%s' (%s): %d class(es) registered.",
            manifest.name,
            manifest.version,
            sum(len(v) for v in result.registered.values()),
        )
    else:
        _logger.warning(
            "Plugin '%s' loaded with %d error(s): %s",
            manifest.name,
            len(result.errors),
            "; ".join(result.errors),
        )
    return result


def discover_plugins(
    search_paths: list[Path], skip_names: set[str] | None = None
) -> list[LoadedPlugin]:
    """Scan every directory in ``search_paths`` for plugins and load each one found.

    Args:
        search_paths: Directories to scan. Each immediate subdirectory
            containing a ``plugin.json`` is treated as one plugin. A
            search path that does not exist is skipped silently (at
            debug level) — a configured-but-not-yet-created plugin
            directory is a normal state for a freshly installed
            application, not an error.
        skip_names: Plugin names to skip entirely (not even imported) —
            used by :class:`~src.plugins.plugin_manager.PluginManager`
            to honor a user's "disabled" choice from a previous
            session. Checked against the manifest's ``name`` field
            after it is parsed, since the directory name and the
            manifest's declared name are not required to match.

    Returns:
        One :class:`LoadedPlugin` per plugin directory found under
        ``search_paths`` whose name is not in ``skip_names``, in
        discovery order. Never raises for an individual plugin's
        problems — see this module's own docstring.
    """
    skip_names = skip_names or set()
    results: list[LoadedPlugin] = []

    for search_path in search_paths:
        if not search_path.is_dir():
            _logger.debug(
                "Plugin search path does not exist, skipping: %s", search_path
            )
            continue

        # Plugins under this search path import as
        # "<plugin_dir_name>.<submodule>" — the search path itself
        # must be importable from, hence added to sys.path. Left on
        # sys.path for the remainder of the process rather than
        # removed after this loop; nothing in this application
        # constructs a second, independent PluginManager instance
        # within one process, so there is no "undo discovery" use case
        # that would need it removed.
        resolved = str(search_path.resolve())
        if resolved not in sys.path:
            sys.path.insert(0, resolved)

        for entry in sorted(search_path.iterdir()):
            if not entry.is_dir():
                continue
            manifest_path = entry / _MANIFEST_FILENAME
            if not manifest_path.exists():
                continue

            try:
                # Peek at the manifest's declared name before fully
                # loading, so a disabled plugin's Python code is never
                # imported and none of its classes are registered — a
                # disabled plugin should have zero side effects, not
                # merely zero registered classes. The manifest itself
                # is still recorded as a LoadedPlugin (with nothing in
                # registered/errors) so a settings panel can keep
                # showing and re-enabling a disabled plugin rather than
                # having it vanish from the list entirely.
                manifest = PluginManifest.load(manifest_path)
                if manifest.name in skip_names:
                    _logger.debug("Skipping disabled plugin: %s", manifest.name)
                    results.append(LoadedPlugin(manifest=manifest))
                    continue
                results.append(_load_one_plugin(entry))
            except ServiceError as exc:
                _logger.warning("Failed to load plugin at %s: %s", entry, exc)
                # A manifest that fails to parse at all has no 'name'
                # PluginManifest could validate — a placeholder
                # manifest carries the raw directory name instead, so
                # this failure still surfaces as one LoadedPlugin entry
                # a settings panel can display, rather than vanishing
                # silently.
                placeholder = PluginManifest(
                    name=entry.name,
                    version="unknown",
                    description="",
                    provides={},
                    manifest_path=manifest_path,
                )
                results.append(LoadedPlugin(manifest=placeholder, errors=[str(exc)]))

    return results
