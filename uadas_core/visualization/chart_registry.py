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

from uadas_core.analysis.fingerprint import SemanticRole
from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger
from uadas_core.visualization.advanced_charts import (
    BubbleChart,
    CandlestickChart,
    FunnelChart,
    HeatmapChart,
    KpiChart,
    RadarChart,
    TreemapChart,
    WaterfallChart,
)
from uadas_core.visualization.base_chart import BaseChart
from uadas_core.visualization.categorical_charts import BarChart, PieChart
from uadas_core.visualization.chart_fit import (
    Bounds,
    ChartFit,
    ChartIntent,
    Need,
    Renderer,
    Slot,
    Variant,
)
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
            because ``CreateVisualizationDialog``'s column picker built one
            ``QComboBox`` per field and had no multi-select variant.
            Milestone 24 added ``ColumnMultiSelect`` and wired the dialog
            to use it for any field named in :attr:`list_fields`, so
            Treemap/Radar are dialog-compatible again — this flag stays
            for the general mechanism (a future plugin chart with, say,
            a non-column list parameter the picker genuinely cannot
            represent) rather than being removed outright.
        list_fields: Which of :attr:`required_fields`/
            :attr:`optional_fields` take a ``list[str]`` of column names
            rather than a single column name — read by
            ``CreateVisualizationDialog`` and
            ``VisualizePage``
            to decide whether a field gets a single :class:`QComboBox`
            or a ``ColumnMultiSelect``. Empty by default — most chart types take
            only single-column fields.
        literal_fields: Optional string parameters whose value is *not* a column
            name (e.g. ``BarChart``'s ``incomplete_from``, a value of the category
            column, or ``LineChart``'s ``variant``, a look). Kept apart from :attr:`optional_fields` so a column picker
            never offers them as columns; the API's chart-spec check accepts both.
            Empty by default.
        fit: The chart's selection metadata for the recommender (chart intelligence, CI.2): which
            question it answers, which columns and data shape it needs, which variants it has and which
            renderers can draw it. ``None`` for a chart that declares none, which is simply never
            recommended (it stays buildable by hand), so a plugin chart is not forced to supply one. Every
            *built-in* has one, pinned by ``tests/visualization/test_chart_fit.py``.
    """

    chart_class: type[BaseChart]
    required_fields: tuple[str, ...]
    optional_fields: tuple[str, ...] = ()
    dialog_compatible: bool = True
    list_fields: tuple[str, ...] = ()
    literal_fields: tuple[str, ...] = ()
    fit: ChartFit | None = None


_REGISTRY: dict[str, ChartRegistration] = {}

# Web-transition 1.3: the built-ins are populated by
# :func:`uadas_core.bootstrap.bootstrap` rather than as a side effect of
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


def fit_for(name: str) -> ChartFit | None:
    """The selection metadata of the chart registered as ``name``, or ``None`` if it declares none.

    Raises:
        ServiceError: If no chart type named ``name`` is registered.
    """
    return get_chart(name).fit


def list_fits() -> dict[str, ChartFit]:
    """Every registered chart that declares a :class:`ChartFit`, keyed by name.

    This is the recommender's candidate list: a chart without a fit (a plugin that declared none) is
    absent, so it is never suggested, but it can still be built by hand.
    """
    return {name: reg.fit for name, reg in _REGISTRY.items() if reg.fit is not None}


# Role groups shared by the built-in fits (chart intelligence, CI.2). Every number in a fit is a starting
# value that CI.3 tunes against the gold set, not a fact about charts.
_LEVELS = (SemanticRole.DIMENSION, SemanticRole.ORDINAL, SemanticRole.BINARY)
_LEVELS_OR_TIME = (*_LEVELS, SemanticRole.TIME)
_LABEL_ROLES = (SemanticRole.DIMENSION, SemanticRole.IDENTIFIER, SemanticRole.TEXT)
_MEASURE = (SemanticRole.MEASURE,)
_ORDERED_AXIS = (SemanticRole.TIME, SemanticRole.ORDINAL, SemanticRole.MEASURE)
# Every built-in is drawn by Plotly today. A CI.8 port wave adds Renderer.ECHARTS to a chart's list, in
# front, only when that chart's golden passes: declaring a renderer that cannot draw it yet would make the
# render plan pick one that does not exist.
_PLOTLY = (Renderer.PLOTLY,)
_SERIES = Bounds(2, 8, 2, 5)
_GROUPS = Bounds(2, 12, 2, 8)
_A_SHARE = frozenset({Need.NON_NEGATIVE, Need.ADDITIVE})
# The axis of a series bar: sorted by label, never folded, so more levels read fine than on a plain bar.
_AXIS = Bounds(2, 60, 3, 24)


def _pivot_axes(axis: Bounds) -> tuple[Slot, Slot]:
    """The two axes of a pivot heatmap: dimensions (or periods) whose levels become rows and columns."""
    return (
        Slot("row_column", _LEVELS_OR_TIME, distinct=axis),
        Slot("column_column", _LEVELS_OR_TIME, distinct=axis),
    )


def _register_builtins() -> None:
    """Populate the registry with every built-in chart type.

    Called from :func:`uadas_core.bootstrap.bootstrap` (web-transition 1.3
    moved this off module import so importing this module has no global-state
    side effect). Idempotent via the module-level ``_builtins_registered`` guard,
    so the repeated ``bootstrap()`` calls in the test suite and the module-level
    registry seeding in ``tests/conftest.py`` are both safe.
    :mod:`~uadas_core.ai.tool_registry` and
    ``create_visualization_dialog`` read this registry live
    (see :func:`~uadas_core.ai.tool_registry._chart_builders`), so they no longer
    depend on it being populated at their own import time.
    """
    global _builtins_registered
    if _builtins_registered:
        return
    register_chart(
        "bar",
        ChartRegistration(
            BarChart,
            ("category_column",),
            ("value_column", "series_column"),
            literal_fields=("incomplete_from", "variant"),
            fit=ChartFit(
                "bar",
                (ChartIntent.COMPARISON,),
                (
                    # The plain bar sorts its bars by value and folds past 15 into "Other", so a time axis
                    # (months, which must stay in order) is not a category here; the series bars below sort
                    # by label and do not fold, which is what lets them take one.
                    Slot("category_column", _LEVELS, distinct=Bounds(2, None, 3, 15)),
                    Slot("value_column", _MEASURE, required=False),
                ),
                _PLOTLY,
                min_rows=2,
                variants=(
                    Variant(
                        "stacked",
                        slots=(
                            Slot("category_column", _LEVELS_OR_TIME, distinct=_AXIS),
                            Slot("series_column", _LEVELS, distinct=_SERIES),
                            Slot(
                                "value_column",
                                _MEASURE,
                                required=False,
                                needs=_A_SHARE,
                            ),
                        ),
                        intents=(ChartIntent.COMPOSITION,),
                    ),
                    Variant(
                        "grouped",
                        literals=(("variant", "grouped"),),
                        slots=(
                            Slot("category_column", _LEVELS_OR_TIME, distinct=_AXIS),
                            Slot("series_column", _LEVELS, distinct=_SERIES),
                        ),
                    ),
                    Variant(
                        "paired",
                        literals=(("variant", "paired"),),
                        slots=(
                            Slot("category_column", _LEVELS_OR_TIME, distinct=_AXIS),
                            # Exactly two series: the builder raises otherwise.
                            Slot("series_column", _LEVELS, distinct=Bounds(2, 2)),
                        ),
                        intents=(ChartIntent.COMPARISON, ChartIntent.DEVIATION),
                    ),
                ),
            ),
        ),
    )
    register_chart(
        "pie",
        ChartRegistration(
            PieChart,
            ("category_column",),
            ("value_column", "panel_column"),
            literal_fields=("variant",),
            fit=ChartFit(
                "pie",
                (ChartIntent.COMPOSITION,),
                (
                    # More than 6 slices cannot be read by angle: a bar is offered instead (plan 3.4).
                    Slot("category_column", _LEVELS, distinct=Bounds(2, 6, 2, 5)),
                    Slot("value_column", _MEASURE, required=False, needs=_A_SHARE),
                ),
                _PLOTLY,
                min_rows=2,
                variants=(
                    Variant("donut", literals=(("variant", "donut"),)),
                    Variant(
                        "panels",
                        slots=(
                            Slot("panel_column", _LEVELS, distinct=Bounds(2, 12, 2, 6)),
                        ),
                    ),
                ),
            ),
        ),
    )
    register_chart(
        "line",
        ChartRegistration(
            LineChart,
            ("y_column",),
            ("x_column", "y2_column"),
            literal_fields=("variant",),
            fit=ChartFit(
                "line",
                (ChartIntent.TREND,),
                (
                    Slot("y_column", _MEASURE),
                    # The builder leaves x optional (it then plots the row index), but a line over the index
                    # is not a trend, so a recommendation needs an axis. It draws one point per row and does not
                    # sort, so a repeated x (date x region x product) zig-zags: x must be unique.
                    Slot(
                        "x_column",
                        _ORDERED_AXIS,
                        needs=frozenset({Need.ORDERED}),
                        unique=True,
                    ),
                ),
                _PLOTLY,
                min_rows=3,
                variants=(
                    Variant(
                        "area",
                        literals=(("variant", "area"),),
                        slots=(
                            Slot(
                                "y_column",
                                _MEASURE,
                                needs=frozenset({Need.NON_NEGATIVE}),
                            ),
                        ),
                    ),
                    Variant(
                        "dual_axis",
                        slots=(Slot("y2_column", _MEASURE),),
                        intents=(ChartIntent.TREND, ChartIntent.RELATIONSHIP),
                    ),
                ),
            ),
        ),
    )
    register_chart(
        "scatter",
        ChartRegistration(
            ScatterChart,
            ("x_column", "y_column"),
            ("color_column", "label_column"),
            literal_fields=("frontier", "pin"),
            fit=ChartFit(
                "scatter",
                (ChartIntent.RELATIONSHIP,),
                (Slot("x_column", _MEASURE), Slot("y_column", _MEASURE)),
                _PLOTLY,
                min_rows=8,
                variants=(
                    Variant(
                        "grouped",
                        slots=(Slot("color_column", _LEVELS, distinct=_SERIES),),
                    ),
                    # Labels stop being readable past a few dozen points.
                    Variant(
                        "labelled",
                        slots=(Slot("label_column", _LABEL_ROLES),),
                        max_rows=40,
                    ),
                    # Which corner is "best" is a judgement about the data's meaning, so a frontier is only
                    # offered when the user asks for one (``pin`` names a value of ``label_column``, so it is
                    # not recommendable from shape and is not declared).
                    *(
                        Variant(
                            f"frontier_{corner}",
                            literals=(("frontier", corner),),
                            explicit=True,
                            min_rows=20,
                        )
                        for corner in (
                            "upper_left",
                            "upper_right",
                            "lower_left",
                            "lower_right",
                        )
                    ),
                ),
            ),
        ),
    )
    register_chart(
        "histogram",
        ChartRegistration(
            HistogramChart,
            ("column",),
            fit=ChartFit(
                "histogram",
                (ChartIntent.DISTRIBUTION,),
                # Fewer than 5 distinct values is a bar chart of levels, not a distribution.
                (Slot("column", _MEASURE, distinct=Bounds(5)),),
                _PLOTLY,
                min_rows=30,
            ),
        ),
    )
    register_chart(
        "box_plot",
        ChartRegistration(
            BoxPlotChart,
            ("value_column",),
            ("group_column",),
            fit=ChartFit(
                "box_plot",
                (ChartIntent.DISTRIBUTION,),
                (Slot("value_column", _MEASURE),),
                _PLOTLY,
                min_rows=10,
                variants=(
                    Variant(
                        "grouped",
                        slots=(Slot("group_column", _LEVELS, distinct=_GROUPS),),
                        intents=(ChartIntent.DISTRIBUTION, ChartIntent.COMPARISON),
                    ),
                ),
            ),
        ),
    )
    register_chart(
        "heatmap",
        ChartRegistration(
            HeatmapChart,
            (),
            ("row_column", "column_column", "value_column"),
            literal_fields=("variant",),
            fit=ChartFit(
                "heatmap",
                # Only the pivot mode (two dimensions on the axes) is declared. The other mode, a correlation
                # matrix, takes no column parameter: it correlates EVERY numeric column of the frame, identifiers
                # and ordinals included, so a spec cannot bind or avoid a column, and the API reads no columns for
                # it. It becomes recommendable when HeatmapChart.build takes a ``columns`` list (a new registry
                # field, so a deliberate change to the AI tool schema); until then it is buildable by hand only.
                (ChartIntent.PATTERN,),
                (
                    *_pivot_axes(Bounds(2, 40, 3, 20)),
                    Slot("value_column", _MEASURE, required=False),
                ),
                _PLOTLY,
                min_rows=4,
                variants=(
                    # Numbers fit in the cells up to about 12 x 12; beyond that the gapped grid reads better.
                    Variant(
                        "numbers",
                        literals=(("variant", "numbers"),),
                        slots=_pivot_axes(Bounds(2, 40, 2, 12)),
                    ),
                    Variant(
                        "grid",
                        literals=(("variant", "grid"),),
                        slots=_pivot_axes(Bounds(2, 40, 13, 40)),
                    ),
                ),
            ),
        ),
    )
    register_chart(
        "bubble",
        ChartRegistration(
            BubbleChart,
            ("x_column", "y_column", "size_column"),
            ("color_column",),
            fit=ChartFit(
                "bubble",
                (ChartIntent.RELATIONSHIP,),
                (
                    Slot("x_column", _MEASURE),
                    Slot("y_column", _MEASURE),
                    Slot("size_column", _MEASURE, needs=frozenset({Need.NON_NEGATIVE})),
                    Slot("color_column", _LEVELS, required=False, distinct=_SERIES),
                ),
                _PLOTLY,
                min_rows=8,
                max_rows=500,
            ),
        ),
    )
    register_chart(
        "treemap",
        ChartRegistration(
            TreemapChart,
            ("path_columns", "value_column"),
            list_fields=("path_columns",),
            fit=ChartFit(
                "treemap",
                (ChartIntent.COMPOSITION,),
                (
                    # Two nested levels (country inside region), per plan 3.5; the builder takes one or two but
                    # an unnested pair is just a cross-tab. 200 leaves is already unreadable (and a customer
                    # list of 500 is not a composition).
                    Slot(
                        "path_columns",
                        _LEVELS,
                        min_count=2,
                        max_count=2,
                        nested=True,
                        distinct=Bounds(2, 200, 3, 50),
                    ),
                    Slot("value_column", _MEASURE, needs=_A_SHARE),
                ),
                _PLOTLY,
                min_rows=4,
            ),
        ),
    )
    register_chart(
        "radar",
        ChartRegistration(
            RadarChart,
            ("category_column", "value_columns"),
            list_fields=("value_columns",),
            fit=ChartFit(
                "radar",
                (ChartIntent.PROFILE,),
                (
                    # One trace per row, so the rows are the entities being compared: a handful at most, each
                    # entity once (a repeated label is two overlapping traces under one name).
                    Slot(
                        "category_column",
                        _LABEL_ROLES,
                        distinct=Bounds(2, 8, 2, 5),
                        unique=True,
                    ),
                    Slot("value_columns", _MEASURE, min_count=3, max_count=8),
                ),
                _PLOTLY,
                min_rows=2,
                max_rows=8,
            ),
        ),
    )
    register_chart(
        "waterfall",
        ChartRegistration(
            WaterfallChart,
            ("category_column", "value_column"),
            fit=ChartFit(
                "waterfall",
                (ChartIntent.DEVIATION,),
                (
                    # One bar per row in the file's order, no aggregation: each step once.
                    Slot(
                        "category_column",
                        _LEVELS_OR_TIME,
                        needs=frozenset({Need.ORDERED}),
                        distinct=Bounds(3, 20, 4, 12),
                        unique=True,
                    ),
                    Slot(
                        "value_column",
                        _MEASURE,
                        needs=frozenset({Need.ADDITIVE, Need.SIGNED}),
                    ),
                ),
                _PLOTLY,
                min_rows=3,
                max_rows=20,
            ),
        ),
    )
    register_chart(
        "funnel",
        ChartRegistration(
            FunnelChart,
            ("stage_column", "value_column"),
            fit=ChartFit(
                "funnel",
                (ChartIntent.FLOW,),
                (
                    # One bar per row in the file's order, no aggregation: each stage once.
                    Slot(
                        "stage_column",
                        (SemanticRole.DIMENSION, SemanticRole.ORDINAL),
                        needs=frozenset({Need.ORDERED}),
                        distinct=Bounds(3, 12, 3, 7),
                        unique=True,
                    ),
                    Slot(
                        "value_column",
                        _MEASURE,
                        needs=frozenset({Need.NON_NEGATIVE, Need.NON_INCREASING}),
                    ),
                ),
                _PLOTLY,
                min_rows=3,
                max_rows=12,
            ),
        ),
    )
    register_chart(
        "candlestick",
        ChartRegistration(
            CandlestickChart,
            (
                "x_column",
                "open_column",
                "high_column",
                "low_column",
                "close_column",
            ),
            ("volume_column",),
            fit=ChartFit(
                "candlestick",
                (ChartIntent.TREND,),
                (
                    Slot(
                        "x_column",
                        (SemanticRole.TIME,),
                        needs=frozenset({Need.ORDERED}),
                        unique=True,
                    ),
                    # Four measures are not an OHLC series: the names say which is which.
                    Slot(
                        "open_column",
                        _MEASURE,
                        name_hints=("open",),
                        hint_required=True,
                    ),
                    Slot(
                        "high_column",
                        _MEASURE,
                        name_hints=("high",),
                        hint_required=True,
                    ),
                    Slot(
                        "low_column", _MEASURE, name_hints=("low",), hint_required=True
                    ),
                    Slot(
                        "close_column",
                        _MEASURE,
                        name_hints=("close",),
                        hint_required=True,
                    ),
                    Slot(
                        "volume_column",
                        _MEASURE,
                        required=False,
                        needs=frozenset({Need.NON_NEGATIVE}),
                        name_hints=("volume", "vol"),
                    ),
                ),
                _PLOTLY,
                min_rows=5,
            ),
        ),
    )
    register_chart(
        "kpi",
        ChartRegistration(
            KpiChart,
            ("value_column",),
            ("x_column",),
            literal_fields=("variant",),
            fit=ChartFit(
                "kpi",
                (ChartIntent.SUMMARY,),
                (
                    Slot("value_column", _MEASURE),
                    Slot(
                        "x_column",
                        _ORDERED_AXIS,
                        required=False,
                        needs=frozenset({Need.ORDERED}),
                    ),
                ),
                _PLOTLY,
                variants=(
                    # The default mini chart is the line. The other looks are taste, so they are only offered
                    # on request, and a lollipop stops reading past a dozen points.
                    Variant(
                        "bars",
                        literals=(("variant", "bars"),),
                        explicit=True,
                        max_rows=60,
                    ),
                    Variant(
                        "dashes",
                        literals=(("variant", "dashes"),),
                        explicit=True,
                        max_rows=60,
                    ),
                    Variant(
                        "lollipop",
                        literals=(("variant", "lollipop"),),
                        explicit=True,
                        max_rows=12,
                    ),
                ),
            ),
        ),
    )
    _builtins_registered = True
