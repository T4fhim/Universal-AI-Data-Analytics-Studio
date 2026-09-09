# File: uadas_core/visualization/chart_registry.py
"""The single registry of available chart types — resolves a gap milestone 9's plan flagged.

Before milestone 12, `uadas_core.ai.tool_registry`'s ``_CHART_BUILDERS`` and
`src.ui.dialogs.create_visualization_dialog``'s ``_CHART_REGISTRY``
each maintained their own independent name -> chart-class mapping,
kept in sync by hand — a genuine duplication risk the milestone 9
plan explicitly flagged and deferred fixing until dynamic plugin
discovery actually required one real registry. This module is that
one registry: both consumers now source their chart list from here,
and :class:`~uadas_core.plugins.plugin_manager.PluginManager` registers
plugin-provided chart types into this same registry, so a plugin chart
becomes available to the AI assistant and (when its parameters allow —
see :attr:`ChartRegistration.dialog_compatible`) the chart-builder
dialog without either of those two modules needing to know a plugin
exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger
from uadas_core.visualization.advanced_charts import (
    BubbleChart,
    FunnelChart,
    HeatmapChart,
    RadarChart,
    TreemapChart,
    WaterfallChart,
)
from uadas_core.visualization.base_chart import BaseChart
from uadas_core.visualization.categorical_charts import BarChart, PieChart
from uadas_core.visualization.continuous_charts import LineChart, ScatterChart
from uadas_core.visualization.distribution_charts import BoxPlotChart, HistogramChart

_logger = get_logger(__name__)


@dataclass(frozen=True)
class ChartRegistration:
    """One registered chart type.

    Attributes:
        chart_class: The :class:`~uadas_core.visualization.base_chart.BaseChart`
            subclass.
        required_fields: Column-parameter names ``build()`` requires,
            in the order a picker UI should present them.
        optional_fields: Column-parameter names ``build()`` accepts
            but does not require.
        dialog_compatible: Milestone 12 defaulted this to ``False`` for
            chart types whose fields include a ``list[str]`` parameter
            (e.g. Treemap's ``path_columns``, Radar's ``value_columns``)
            because :class:`~src.ui.dialogs.create_visualization_dialog.
            CreateVisualizationDialog`'s column picker built one
            ``QComboBox`` per field and had no multi-select variant.
            Milestone 24 added :class:`~src.ui.widgets.
            column_multi_select.ColumnMultiSelect` and wired the dialog
            to use it for any field named in :attr:`list_fields`, so
            Treemap/Radar are dialog-compatible again — this flag stays
            for the general mechanism (a future plugin chart with, say,
            a non-column list parameter the picker genuinely cannot
            represent) rather than being removed outright.
        list_fields: Which of :attr:`required_fields`/
            :attr:`optional_fields` take a ``list[str]`` of column names
            rather than a single column name — read by
            :class:`~src.ui.dialogs.create_visualization_dialog.
            CreateVisualizationDialog` and
            :class:`~src.ui.workbench.pages.visualize_page.VisualizePage`
            to decide whether a field gets a single :class:`QComboBox`
            or a :class:`~src.ui.widgets.column_multi_select.
            ColumnMultiSelect`. Empty by default — most chart types take
            only single-column fields.
    """

    chart_class: type[BaseChart]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    dialog_compatible: bool = True
    list_fields: tuple[str, ...] = ()


_REGISTRY: dict[str, ChartRegistration] = {}

# Web-transition 1.3: the built-ins are populated by
# :func:`uadas_core.core.bootstrap.bootstrap` rather than as a side effect of
# importing this module, so importing it has no global-state effect (see
# plans/phase-1-3-startup-graph.md §9). This flag makes :func:`_register_builtins`
# a no-op after its first successful call: ``bootstrap()`` runs several times per
# pytest session and ``tests/conftest.py`` also seeds the built-in registries, at
# module import (before test collection). Mirrors
# :data:`uadas_core.core.logger._configured`. One-shot seed: a later
# ``unregister_chart`` of a built-in is not restored by calling this again.
_builtins_registered: bool = False


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
            (compare :func:`~uadas_core.readers.reader_registry.register_reader`,
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

    Used by :class:`~uadas_core.plugins.plugin_manager.PluginManager` when a
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
    """Populate the registry with every built-in chart type.

    Called from :func:`uadas_core.core.bootstrap.bootstrap` (web-transition 1.3
    moved this off module import so importing this module has no global-state
    side effect). Idempotent via the module-level ``_builtins_registered`` guard,
    so the repeated ``bootstrap()`` calls in the test suite and the module-level
    registry seeding in ``tests/conftest.py`` are both safe.
    :mod:`~uadas_core.ai.tool_registry` and
    :mod:`~src.ui.dialogs.create_visualization_dialog` read this registry live
    (see :func:`~uadas_core.ai.tool_registry._chart_builders`), so they no longer
    depend on it being populated at their own import time.
    """
    global _builtins_registered
    if _builtins_registered:
        return
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
            TreemapChart,
            ("path_columns", "value_column"),
            list_fields=("path_columns",),
        ),
    )
    register_chart(
        "radar",
        ChartRegistration(
            RadarChart,
            ("category_column", "value_columns"),
            list_fields=("value_columns",),
        ),
    )
    register_chart(
        "waterfall",
        ChartRegistration(WaterfallChart, ("category_column", "value_column")),
    )
    register_chart(
        "funnel", ChartRegistration(FunnelChart, ("stage_column", "value_column"))
    )
    _builtins_registered = True
