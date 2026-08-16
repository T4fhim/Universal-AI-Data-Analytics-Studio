# File: src/ai/tool_registry.py
"""Maps tool names to schemas and implementations, every tool a thin wrapper over existing code.

No new capability is invented in this module. Every tool below calls
directly into a function already built and tested in an earlier
milestone — :mod:`src.cleaning`, :mod:`src.analysis`,
:mod:`src.forecasting`. This means every validation path those
functions already enforce (column existence, type checks, minimum row
counts) applies identically whether a human calls them through the UI
or the assistant calls them on a human's behalf — there is no
assistant-specific bypass of any check built in earlier phases.

Cleaning tools never mutate the active dataset. Each one returns a new
:class:`~src.services.workspace_service.Dataset` with lineage set,
exactly as :class:`~src.cleaning.base_operation.BaseOperation`
requires when called directly — the assistant is not exempted from
this rule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go

from src.analysis.aggregation import aggregate
from src.analysis.correlation import compute_correlation
from src.analysis.crosstab import cross_tabulate
from src.analysis.dataset_profile import profile_dataset
from src.cleaning.duplicates import DropDuplicates
from src.cleaning.missing_values import DropMissingValues, FillMissingValues
from src.cleaning.text_normalization import NormalizeText
from src.cleaning.type_conversion import ConvertType
from src.forecasting.exponential_smoothing import forecast_exponential_smoothing
from src.forecasting.prophet_forecast import forecast_prophet
from src.services.workspace_service import Dataset
from src.visualization.categorical_charts import BarChart, PieChart
from src.visualization.continuous_charts import LineChart, ScatterChart
from src.visualization.distribution_charts import BoxPlotChart, HistogramChart

# Milestone 9: the AI charting tool needs the same chart-name ->
# builder-class mapping src.ui.dialogs.create_visualization_dialog
# already has as its own private _CHART_REGISTRY. Deliberately
# duplicated here rather than imported from that module — the
# milestone plan itself (see Milestone 12) flags that charts have no
# shared public registry yet and defers building one until the plugin
# milestone actually requires dynamic discovery; importing a UI
# module's private name from this AI module would also be a layering
# violation (src.ai should not depend on src.ui). Keep this in sync
# with that dialog's registry by hand until Milestone 12 replaces both
# with one real registry.
_CHART_BUILDERS: dict[str, type] = {
    "bar": BarChart,
    "pie": PieChart,
    "line": LineChart,
    "scatter": ScatterChart,
    "histogram": HistogramChart,
    "box_plot": BoxPlotChart,
}


@dataclass
class ToolDefinition:
    """One callable tool: its Anthropic-format schema and its implementation.

    Attributes:
        name: Tool name as sent to and returned by the API.
        description: Shown to the model — what the tool does and when
            to use it.
        input_schema: JSON Schema for the tool's parameters, in the
            exact shape the Anthropic API's ``tools`` parameter
            expects.
        handler: The actual function. Always takes the active
            ``Dataset`` as its first argument plus the tool's declared
            parameters as keyword arguments, and returns either a new
            ``Dataset`` (cleaning tools) or a plain JSON-serializable
            result (analysis/forecast tools) — never mutates its
            input.
    """

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Any]


def _drop_missing_values(dataset: Dataset, columns: list[str] | None = None) -> Dataset:
    return DropMissingValues.apply(dataset, columns=columns)


def _fill_missing_values(
    dataset: Dataset, fill_value: Any, columns: list[str] | None = None
) -> Dataset:
    return FillMissingValues.apply(dataset, fill_value=fill_value, columns=columns)


def _drop_duplicates(dataset: Dataset, columns: list[str] | None = None) -> Dataset:
    return DropDuplicates.apply(dataset, columns=columns)


def _normalize_text(
    dataset: Dataset,
    columns: list[str],
    trim_whitespace: bool = True,
    case: str | None = None,
) -> Dataset:
    return NormalizeText.apply(
        dataset, columns=columns, trim_whitespace=trim_whitespace, case=case
    )


def _convert_type(dataset: Dataset, column: str, target_type: str) -> Dataset:
    return ConvertType.apply(dataset, column=column, target_type=target_type)


def _profile_dataset(dataset: Dataset) -> dict:
    profile = profile_dataset(dataset)
    return {
        "row_count": profile.row_count,
        "column_count": profile.column_count,
        "duplicate_row_count": profile.duplicate_row_count,
        "ambiguous_type_columns": profile.ambiguous_type_columns,
        "columns": [
            {
                "name": c.name,
                "dtype": c.dtype,
                "missing_percentage": c.missing_percentage,
                "unique_count": c.unique_count,
            }
            for c in profile.column_profiles
        ],
    }


def _compute_correlation(dataset: Dataset, method: str = "pearson") -> dict:
    result = compute_correlation(dataset.dataframe, method=method)
    return {
        "included_columns": result.included_columns,
        "excluded_columns": result.excluded_columns,
        "matrix": result.matrix.round(3).to_dict(),
    }


def _aggregate(
    dataset: Dataset, group_by: list[str], agg_column: str, agg_function: str = "mean"
) -> dict:
    result = aggregate(
        dataset.dataframe,
        group_by=group_by,
        agg_column=agg_column,
        agg_function=agg_function,
    )
    return {"result": result.reset_index().to_dict(orient="records")}


def _cross_tabulate(dataset: Dataset, row_column: str, column_column: str) -> dict:
    result = cross_tabulate(
        dataset.dataframe, row_column=row_column, column_column=column_column
    )
    return {"table": result.to_dict()}


def _forecast_result_to_dict(result) -> dict:
    """Shared JSON-friendly conversion for both forecast tools' ``ForecastResult``.

    Dates become ISO strings and forecast values become plain floats
    (with ``lower``/``upper`` bounds included when Prophet's interval
    DataFrame is what ``forecast_values`` holds) — matches every other
    handler in this module returning a plain, JSON-serializable dict
    rather than the richer dataclass/DataFrame objects the underlying
    forecasting functions return.
    """
    import pandas as pd

    forecast_values = result.forecast_values
    if isinstance(forecast_values, pd.DataFrame):
        points = [
            {
                "date": date.isoformat(),
                "value": float(row["yhat"]),
                "lower": float(row["lower"]),
                "upper": float(row["upper"]),
            }
            for date, row in forecast_values.iterrows()
        ]
    else:
        points = [
            {"date": date.isoformat(), "value": float(value)}
            for date, value in forecast_values.items()
        ]

    return {
        "method": result.method,
        "historical_point_count": len(result.historical_values),
        "forecast": points,
    }


def _forecast_exponential_smoothing_tool(
    dataset: Dataset,
    date_column: str,
    value_column: str,
    periods: int,
    trend: str | None = "add",
    seasonal: str | None = None,
    seasonal_periods: int | None = None,
) -> dict:
    result = forecast_exponential_smoothing(
        dataset.dataframe,
        date_column=date_column,
        value_column=value_column,
        periods=periods,
        trend=trend,
        seasonal=seasonal,
        seasonal_periods=seasonal_periods,
    )
    return _forecast_result_to_dict(result)


def _forecast_prophet_tool(
    dataset: Dataset, date_column: str, value_column: str, periods: int
) -> dict:
    # include_confidence_interval fixed to True here — this is the one
    # meaningful capability Prophet has over exponential smoothing (see
    # prophet_forecast.py's own docstring); exposing it as a tool that
    # discards it would give the AI no reason to ever prefer this tool
    # over the exponential-smoothing one.
    result = forecast_prophet(
        dataset.dataframe,
        date_column=date_column,
        value_column=value_column,
        periods=periods,
        include_confidence_interval=True,
    )
    return _forecast_result_to_dict(result)


def _build_chart(
    dataset: Dataset, chart_type: str, title: str | None = None, **chart_kwargs: Any
) -> go.Figure:
    """Build a chart from the active dataset — the one tool in this module that doesn't return a plain dict.

    Returns a ``plotly.graph_objects.Figure`` directly, same as every
    ``BaseChart.build()`` implementation — :meth:`~src.ai.
    assistant_service.AssistantService._execute_tool` special-cases a
    ``go.Figure`` result exactly the way it already special-cases a
    ``Dataset`` result (registering it into ``WorkspaceService`` rather
    than trying to JSON-serialize a figure object).
    """
    if chart_type not in _CHART_BUILDERS:
        raise ServiceError(
            f"Unknown chart_type: {chart_type!r}. Must be one of: "
            f"{', '.join(sorted(_CHART_BUILDERS))}."
        )
    builder = _CHART_BUILDERS[chart_type]
    figure = builder.build(dataset.dataframe, **chart_kwargs)
    if title:
        figure.update_layout(title=title)
    return figure


TOOLS: list[ToolDefinition] = [
    ToolDefinition(
        name="drop_missing_values",
        description="Remove rows with missing values from the active dataset. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to check. Omit to check all columns.",
                }
            },
        },
        handler=_drop_missing_values,
    ),
    ToolDefinition(
        name="fill_missing_values",
        description="Replace missing values with a given value. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "fill_value": {
                    "description": "Value to substitute for missing entries."
                },
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to fill. Omit to fill all columns.",
                },
            },
            "required": ["fill_value"],
        },
        handler=_fill_missing_values,
    ),
    ToolDefinition(
        name="drop_duplicates",
        description="Remove duplicate rows. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "columns": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Columns to consider when identifying duplicates. Omit to require all columns to match.",
                }
            },
        },
        handler=_drop_duplicates,
    ),
    ToolDefinition(
        name="normalize_text",
        description="Trim whitespace and/or normalize casing on text columns. Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "columns": {"type": "array", "items": {"type": "string"}},
                "trim_whitespace": {"type": "boolean", "default": True},
                "case": {"type": "string", "enum": ["lower", "upper", "title"]},
            },
            "required": ["columns"],
        },
        handler=_normalize_text,
    ),
    ToolDefinition(
        name="convert_type",
        description="Convert a column to a different data type (numeric, integer, string, boolean, datetime). Returns a new derived dataset.",
        input_schema={
            "type": "object",
            "properties": {
                "column": {"type": "string"},
                "target_type": {
                    "type": "string",
                    "enum": ["numeric", "integer", "string", "boolean", "datetime"],
                },
            },
            "required": ["column", "target_type"],
        },
        handler=_convert_type,
    ),
    ToolDefinition(
        name="profile_dataset",
        description="Get a statistical profile of the active dataset: row/column counts, missing values, types, duplicates.",
        input_schema={"type": "object", "properties": {}},
        handler=_profile_dataset,
    ),
    ToolDefinition(
        name="compute_correlation",
        description="Compute a correlation matrix over the active dataset's numeric columns.",
        input_schema={
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["pearson", "spearman", "kendall"],
                    "default": "pearson",
                }
            },
        },
        handler=_compute_correlation,
    ),
    ToolDefinition(
        name="aggregate",
        description="Group the active dataset and aggregate a numeric column.",
        input_schema={
            "type": "object",
            "properties": {
                "group_by": {"type": "array", "items": {"type": "string"}},
                "agg_column": {"type": "string"},
                "agg_function": {
                    "type": "string",
                    "enum": ["sum", "mean", "median", "min", "max", "count", "std"],
                    "default": "mean",
                },
            },
            "required": ["group_by", "agg_column"],
        },
        handler=_aggregate,
    ),
    ToolDefinition(
        name="cross_tabulate",
        description="Cross-tabulate frequency counts between two categorical columns.",
        input_schema={
            "type": "object",
            "properties": {
                "row_column": {"type": "string"},
                "column_column": {"type": "string"},
            },
            "required": ["row_column", "column_column"],
        },
        handler=_cross_tabulate,
    ),
    ToolDefinition(
        name="forecast_exponential_smoothing",
        description=(
            "Forecast future values of a numeric column using Holt-Winters "
            "exponential smoothing. Good default for shorter series or series "
            "with one simple seasonal pattern."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "periods": {
                    "type": "integer",
                    "description": "How many future periods to project.",
                },
                "trend": {
                    "type": "string",
                    "enum": ["add", "mul"],
                    "description": "Omit for no trend component.",
                },
                "seasonal": {
                    "type": "string",
                    "enum": ["add", "mul"],
                    "description": "Omit for no seasonal component.",
                },
                "seasonal_periods": {
                    "type": "integer",
                    "description": "Length of one seasonal cycle (e.g. 12 for monthly data with yearly seasonality). Required if seasonal is set.",
                },
            },
            "required": ["date_column", "value_column", "periods"],
        },
        handler=_forecast_exponential_smoothing_tool,
    ),
    ToolDefinition(
        name="forecast_prophet",
        description=(
            "Forecast future values of a numeric column using Prophet, including "
            "a confidence interval. Better for longer series with multiple "
            "seasonal patterns or missing dates/outliers."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "date_column": {"type": "string"},
                "value_column": {"type": "string"},
                "periods": {
                    "type": "integer",
                    "description": "How many future periods to project.",
                },
            },
            "required": ["date_column", "value_column", "periods"],
        },
        handler=_forecast_prophet_tool,
    ),
    ToolDefinition(
        name="build_chart",
        description=(
            "Build a chart from the active dataset. Returns a visualization "
            "shown to the user, not raw data — use this when the user asks to "
            "see or visualize something rather than just compute a number."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "chart_type": {
                    "type": "string",
                    "enum": sorted(_CHART_BUILDERS.keys()),
                },
                "title": {"type": "string"},
                "category_column": {"type": "string", "description": "Bar/Pie charts."},
                "value_column": {
                    "type": "string",
                    "description": "Bar/Pie/Box Plot charts.",
                },
                "x_column": {"type": "string", "description": "Line/Scatter charts."},
                "y_column": {"type": "string", "description": "Line/Scatter charts."},
                "color_column": {
                    "type": "string",
                    "description": "Scatter chart (optional).",
                },
                "column": {"type": "string", "description": "Histogram chart."},
                "group_column": {
                    "type": "string",
                    "description": "Box Plot chart (optional).",
                },
            },
            "required": ["chart_type"],
        },
        handler=_build_chart,
    ),
]


def get_anthropic_tool_schemas() -> list[dict[str, Any]]:
    """Return every tool's schema in the exact shape the Anthropic API's ``tools`` parameter expects."""
    return [
        {"name": t.name, "description": t.description, "input_schema": t.input_schema}
        for t in TOOLS
    ]


def get_tool_by_name(name: str) -> ToolDefinition:
    """Look up a tool by name.

    Raises:
        KeyError: If no tool with this name is registered — deliberately
            a plain KeyError, not a project ServiceError, since this is
            an internal lookup failure (the model requested a tool name
            that does not exist), not a user-facing data error.
    """
    for tool in TOOLS:
        if tool.name == name:
            return tool
    raise KeyError(f"No tool registered with name: {name!r}")
