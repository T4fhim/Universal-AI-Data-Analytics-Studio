# File: src/visualization/chart_registry.py
"""The single registry of available chart types — resolves a gap milestone 9's plan flagged.

Before milestone 12, `src.ai.tool_registry`'s ``_CHART_BUILDERS`` and
`src.ui.dialogs.create_visualization_dialog``'s ``_CHART_REGISTRY``
each maintained their own independent name -> chart-class mapping,
kept in sync by hand — a genuine duplication risk the milestone 9
plan explicitly flagged and deferred fixing until dynamic plugin
discovery actually required one real registry. This module is that
one registry: both consumers now source their chart list from here,
and :class:`~src.plugins.plugin_manager.PluginManager` registers
plugin-provided chart types into this same registry, so a plugin chart
becomes available to the AI assistant and (when its parameters allow —
see :attr:`ChartRegistration.dialog_compatible`) the chart-builder
dialog without either of those two modules needing to know a plugin
exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.visualization.advanced_charts import (
    BubbleChart,
    FunnelChart,
    HeatmapChart,
    RadarChart,
    TreemapChart,
    WaterfallChart,
)
from src.visualization.base_chart import BaseChart
from src.visualization.categorical_charts import BarChart, PieChart
from src.visualization.continuous_charts import LineChart, ScatterChart
from src.visualization.distribution_charts import BoxPlotChart, HistogramChart

_logger = get_logger(__name__)


@dataclass(frozen=True)
class ChartRegistration:
    """One registered chart type.

    Attributes:
        chart_class: The :class:`~src.visualization.base_chart.BaseChart`
            subclass.
        required_fields: Column-parameter names ``build()`` requires,
            in the order a picker UI should present them.
        optional_fields: Column-parameter names ``build()`` accepts
            but does not require.
        dialog_compatible: ``False`` for chart types whose fields
            include a ``list[str]`` parameter (e.g. Treemap's
            ``path_columns``, Radar's ``value_columns``) —
            :class:`~src.ui.dialogs.create_visualization_dialog.
            CreateVisualizationDialog`'s column picker builds one
            ``QComboBox`` per field and has no multi-select variant
            yet, so those chart types are excluded from the dialog's
            list but remain fully available to the AI assistant, whose
            JSON-schema tool parameters handle arrays natively. A
            plugin chart with a list-type field must set this to
            ``False`` itself (see :meth:`register_chart`) for the same
            reason.
    """

    chart_class: type[BaseChart]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    dialog_compatible: bool = True


_REGISTRY: dict[str, ChartRegistration] = {}


def register_chart(name: str, registration: ChartRegistration) -> None:
    """Register a chart type under ``name``.

    Args:
        name: Machine-friendly identifier (lowercase, underscore-
            separated — e.g. ``"box_plot"``), used as both the AI
            tool's ``chart_type`` enum value and the dialog's display
            name (title-cased on display; see
            :func:`display_name_for`).
        registration: The chart's class and field metadata.

    Raises:
        ServiceError: If ``name`` is already registered — this project
            has no "last registration wins" convention anywhere else
            (compare :func:`~src.readers.reader_registry.register_reader`,
            which raises for the same reason), so a name collision
            between two plugins, or a plugin and a built-in, surfaces
            immediately rather than silently shadowing one of them.
    """
    if name in _REGISTRY:
        raise ServiceError(
            f"A chart type named '{name}' is already registered "
            f"({_REGISTRY[name].chart_class.__name__}). Choose a "
            f"different name."
        )
    _REGISTRY[name] = registration
    _logger.debug(
        "Registered chart type '%s' -> %s.", name, registration.chart_class.__name__
    )


def get_chart(name: str) -> ChartRegistration:
    """Look up a registered chart type by name.

    Raises:
        ServiceError: If no chart type named ``name`` is registered.
    """
    if name not in _REGISTRY:
        raise ServiceError(
            f"Unknown chart type: {name!r}. Registered types: "
            f"{', '.join(sorted(_REGISTRY))}."
        )
    return _REGISTRY[name]


def unregister_chart(name: str) -> None:
    """Remove a previously registered chart type.

    Used by :class:`~src.plugins.plugin_manager.PluginManager` when a
    plugin is disabled — without this, disabling then re-enabling a
    plugin within the same running session would fail
    :func:`register_chart`'s duplicate-name check on the second
    load. Silently does nothing if ``name`` is not registered, since
    the caller (disabling a plugin that only partially registered
    before a load error) may legitimately not know which names it
    actually managed to register.
    """
    _REGISTRY.pop(name, None)


def list_charts() -> dict[str, ChartRegistration]:
    """Return every registered chart type, keyed by name."""
    return dict(_REGISTRY)


def list_dialog_charts() -> dict[str, ChartRegistration]:
    """Return only the chart types :attr:`ChartRegistration.dialog_compatible` allows."""
    return {name: reg for name, reg in _REGISTRY.items() if reg.dialog_compatible}


def display_name_for(name: str) -> str:
    """Turn a registry name into a dialog-friendly label, e.g. ``"box_plot"`` -> ``"Box Plot"``."""
    return name.replace("_", " ").title()


def _register_builtins() -> None:
    """Populate the registry with every chart type built before milestone 12.

    Called once at import time (bottom of this module) rather than
    left for each consumer to trigger — the registry should be fully
    populated with built-ins before either
    :mod:`~src.ai.tool_registry` or
    :mod:`~src.ui.dialogs.create_visualization_dialog` first reads
    from it, and both already import this module at their own import
    time, so import-time population is the simplest way to guarantee
    that ordering without adding an explicit "initialize the registry"
    call every entry point would need to remember to make.
    """
    register_chart(
        "bar", ChartRegistration(BarChart, ("category_column",), ("value_column",))
    )
    register_chart(
        "pie", ChartRegistration(PieChart, ("category_column",), ("value_column",))
    )
    register_chart("line", ChartRegistration(LineChart, ("y_column",), ("x_column",)))
    register_chart(
        "scatter",
        ChartRegistration(ScatterChart, ("x_column", "y_column"), ("color_column",)),
    )
    register_chart("histogram", ChartRegistration(HistogramChart, ("column",)))
    register_chart(
        "box_plot",
        ChartRegistration(BoxPlotChart, ("value_column",), ("group_column",)),
    )
    register_chart("heatmap", ChartRegistration(HeatmapChart, ()))
    register_chart(
        "bubble",
        ChartRegistration(
            BubbleChart, ("x_column", "y_column", "size_column"), ("color_column",)
        ),
    )
    register_chart(
        "treemap",
        ChartRegistration(
            TreemapChart, ("path_columns", "value_column"), dialog_compatible=False
        ),
    )
    register_chart(
        "radar",
        ChartRegistration(
            RadarChart,
            ("category_column", "value_columns"),
            dialog_compatible=False,
        ),
    )
    register_chart(
        "waterfall",
        ChartRegistration(WaterfallChart, ("category_column", "value_column")),
    )
    register_chart(
        "funnel", ChartRegistration(FunnelChart, ("stage_column", "value_column"))
    )


_register_builtins()
