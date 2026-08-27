# File: src/cleaning/operation_registry.py
"""The registry of available cleaning operations, mirroring src.visualization.chart_registry.

Before milestone 12, :mod:`~src.ai.tool_registry` called each cleaning
operation's class directly (``DropMissingValues.apply(...)``,
``FillMissingValues.apply(...)``, and so on) rather than looking it up
by name — workable with a small, fixed set of built-in operations, but
with no way for a plugin-provided operation to become reachable
without editing that module's source. This registry gives
:class:`~src.plugins.plugin_manager.PluginManager` one real place to
register a plugin's cleaning operations into. Milestone 12 does not
change ``tool_registry.py``'s existing hand-written tool handlers for
the 5 built-in operations (each already has its own hand-authored
Anthropic tool schema, since the API's schema format cannot be
derived from a bare ``apply(cls, dataset, **kwargs)`` signature) — a
plugin operation registered here is available to any code that looks
it up by name (a "Plugins" settings panel listing what's installed,
future tooling), even though it does not yet get its own auto-
generated AI tool. That gap is explicitly out of scope for this
milestone, tracked rather than silently left unstated.
"""

from __future__ import annotations

from src.cleaning.base_operation import BaseOperation
from src.cleaning.duplicates import DropDuplicates
from src.cleaning.missing_values import DropMissingValues, FillMissingValues
from src.cleaning.text_normalization import NormalizeText
from src.cleaning.type_conversion import ConvertType
from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

_REGISTRY: dict[str, type[BaseOperation]] = {}


def register_operation(name: str, operation_class: type[BaseOperation]) -> None:
    """Register a cleaning operation under ``name``.

    Args:
        name: Machine-friendly identifier (e.g. ``"drop_duplicates"``).
        operation_class: A :class:`~src.cleaning.base_operation.BaseOperation`
            subclass.

    Raises:
        ServiceError: If ``name`` is already registered — same
            collision-is-an-error convention as
            :func:`~src.visualization.chart_registry.register_chart`
            and :func:`~src.readers.reader_registry.register_reader`.
    """
    if name in _REGISTRY:
        raise ServiceError(
            f"A cleaning operation named '{name}' is already registered "
            f"({_REGISTRY[name].__name__}). Choose a different name."
        )
    _REGISTRY[name] = operation_class
    _logger.debug(
        "Registered cleaning operation '%s' -> %s.", name, operation_class.__name__
    )


def unregister_operation(name: str) -> None:
    """Remove a previously registered cleaning operation.

    Used by :class:`~src.plugins.plugin_manager.PluginManager` when a
    plugin is disabled — same reasoning as
    :func:`~src.visualization.chart_registry.unregister_chart`.
    """
    _REGISTRY.pop(name, None)


def get_operation(name: str) -> type[BaseOperation]:
    """Look up a registered cleaning operation by name.

    Raises:
        ServiceError: If no operation named ``name`` is registered.
    """
    if name not in _REGISTRY:
        raise ServiceError(
            f"Unknown cleaning operation: {name!r}. Registered "
            f"operations: {', '.join(sorted(_REGISTRY))}."
        )
    return _REGISTRY[name]


def list_operations() -> dict[str, type[BaseOperation]]:
    """Return every registered cleaning operation, keyed by name."""
    return dict(_REGISTRY)


def _register_builtins() -> None:
    """Populate the registry with every cleaning operation built before milestone 12.

    Called at import time, same reasoning as
    :func:`~src.visualization.chart_registry._register_builtins`.
    """
    register_operation("drop_missing_values", DropMissingValues)
    register_operation("fill_missing_values", FillMissingValues)
    register_operation("drop_duplicates", DropDuplicates)
    register_operation("normalize_text", NormalizeText)
    register_operation("convert_type", ConvertType)


_register_builtins()
