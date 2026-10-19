# File: apps/api/uadas_api/stages/execute.py
"""Run one stage operation on a frame and describe the outcome as result sections. Django-free.

Why a second table next to the tool registry: the registry's handlers return a plain ``dict``
(they are shaped for an LLM's tool-result message), which would reach the web as a bag of
strings. The core's result *renderers* want the typed result object (``TTestResult``,
``ForecastResult``, ...) to produce the proper sections -- including ``AssumptionsSection``. So
:data:`RAW_RUNNERS` calls the same ``uadas_core.analysis`` / ``forecasting`` functions with the same
defaults as the tool handlers and hands the object to ``get_renderer``. Cleaning and charting go
through the registry handlers themselves (they already return a ``Dataset`` / ``go.Figure``), so a
stage run and a chat tool call share one code path for them.

Parity (``tests/test_web_stages.py``): every ``RESULT`` operation of the catalog has a raw runner and
every raw runner is in the catalog; two operations are run both ways and must agree. A function
added to the core tool registry therefore fails a test, not a user.

No Django here: the module is exercised without a database, and the worker handler
(:mod:`uadas_api.stages.run`) owns everything stateful.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import plotly.graph_objects as go  # type: ignore[import-untyped]

from uadas_api.stages.catalog import Operation, OperationKind
from uadas_core.ai.tool_registry import get_tool_by_name
from uadas_core.analysis.aggregation import aggregate
from uadas_core.analysis.anova import one_way_anova
from uadas_core.analysis.chi_square import chi_square_test
from uadas_core.analysis.clustering import k_means_clustering
from uadas_core.analysis.correlation import compute_correlation
from uadas_core.analysis.crosstab import cross_tabulate
from uadas_core.analysis.dataset_profile import profile_dataset
from uadas_core.analysis.normality import check_normality
from uadas_core.analysis.pca import compute_pca
from uadas_core.analysis.regression import linear_regression
from uadas_core.analysis.t_test import independent_t_test, paired_t_test
from uadas_core.core.expertise_level import ExpertiseLevel
from uadas_core.forecasting.arima_forecast import forecast_arima
from uadas_core.forecasting.exponential_smoothing import forecast_exponential_smoothing
from uadas_core.forecasting.linear_regression_forecast import forecast_linear_regression
from uadas_core.forecasting.model_comparison import compare_forecast_models
from uadas_core.forecasting.prophet_forecast import forecast_prophet
from uadas_core.forecasting.random_forest_forecast import forecast_random_forest
from uadas_core.models import Dataset
from uadas_core.results.base_result_renderer import (
    FigureSection,
    KeyValueSection,
    ResultSection,
)
from uadas_core.results.result_renderer_registry import get_renderer


@dataclass(frozen=True)
class Executed:
    """The outcome of one operation: what to show, and the derived dataset (cleaning only)."""

    title: str
    headline: str
    sections: list[ResultSection]
    derived: Dataset | None = None


def _frame(dataset: Dataset) -> Any:
    return dataset.dataframe


# name -> callable(dataset, **parameters) returning the core's typed result object. Defaults
# mirror the matching handler in uadas_core.ai.tool_registry (the parity test runs two of them
# both ways).
RAW_RUNNERS: dict[str, Callable[..., Any]] = {
    "profile_dataset": lambda ds: profile_dataset(ds),
    "compute_correlation": lambda ds, method="pearson": compute_correlation(
        _frame(ds), method=method
    ),
    "aggregate": lambda ds, group_by, agg_column, agg_function="mean": aggregate(
        _frame(ds), group_by=group_by, agg_column=agg_column, agg_function=agg_function
    ),
    "cross_tabulate": lambda ds, row_column, column_column: cross_tabulate(
        _frame(ds), row_column=row_column, column_column=column_column
    ),
    "independent_t_test": lambda ds, value_column, group_column, group_a, group_b, equal_variance=False: independent_t_test(
        _frame(ds), value_column, group_column, group_a, group_b, equal_variance
    ),
    "paired_t_test": lambda ds, column_a, column_b: paired_t_test(
        _frame(ds), column_a, column_b
    ),
    "one_way_anova": lambda ds, value_column, group_column: one_way_anova(
        _frame(ds), value_column, group_column
    ),
    "chi_square_test": lambda ds, row_column, column_column: chi_square_test(
        _frame(ds), row_column, column_column
    ),
    "linear_regression": lambda ds, target_column, feature_columns: linear_regression(
        _frame(ds), target_column, feature_columns
    ),
    "check_normality": lambda ds, column, method="shapiro_wilk": check_normality(
        _frame(ds), column, method
    ),
    "compute_pca": lambda ds, columns=None, n_components=None: compute_pca(
        _frame(ds), columns=columns, n_components=n_components
    ),
    "k_means_clustering": lambda ds, k, columns=None: k_means_clustering(
        _frame(ds), k, columns=columns
    ),
    "forecast_exponential_smoothing": lambda ds, date_column, value_column, periods, trend="add", seasonal=None, seasonal_periods=None: forecast_exponential_smoothing(
        _frame(ds),
        date_column=date_column,
        value_column=value_column,
        periods=periods,
        trend=trend,
        seasonal=seasonal,
        seasonal_periods=seasonal_periods,
    ),
    "forecast_prophet": lambda ds, date_column, value_column, periods: forecast_prophet(
        _frame(ds),
        date_column=date_column,
        value_column=value_column,
        periods=periods,
        include_confidence_interval=True,
    ),
    "forecast_linear_regression": lambda ds, date_column, value_column, periods, degree=1: forecast_linear_regression(
        _frame(ds), date_column, value_column, periods, degree=degree
    ),
    "forecast_arima": lambda ds, date_column, value_column, periods, seasonal=False, seasonal_periods=None: forecast_arima(
        _frame(ds),
        date_column,
        value_column,
        periods,
        seasonal=seasonal,
        seasonal_periods=seasonal_periods,
    ),
    "forecast_random_forest": lambda ds, date_column, value_column, periods: forecast_random_forest(
        _frame(ds), date_column, value_column, periods
    ),
    "compare_forecast_models": lambda ds, date_column, value_column, periods: compare_forecast_models(
        _frame(ds), date_column, value_column, periods
    ),
}


def _pretty(name: str) -> str:
    return name.replace("_", " ").title()


def _dataset_outcome(
    operation: Operation, source: Dataset, derived: Dataset
) -> Executed:
    items = (
        ("Rows before", str(source.row_count)),
        ("Rows after", str(derived.row_count)),
        ("Columns before", str(source.column_count)),
        ("Columns after", str(derived.column_count)),
        ("What changed", derived.derivation_description or ""),
    )
    return Executed(
        title=_pretty(operation.name),
        headline=derived.derivation_description
        or f"{_pretty(operation.name)} applied.",
        sections=[KeyValueSection(title="Derived dataset", items=items)],
        derived=derived,
    )


def execute(
    operation: Operation,
    dataset: Dataset,
    parameters: dict[str, Any],
    level: ExpertiseLevel,
) -> Executed:
    """Run ``operation`` on ``dataset`` with already-validated ``parameters``.

    Raises the core's own exceptions (``ServiceError``, ``ValueError``, ...); the caller maps them
    to a closed job error code and never forwards their text.
    """
    if operation.kind is OperationKind.DATASET:
        derived = get_tool_by_name(operation.name).handler(dataset, **parameters)
        return _dataset_outcome(operation, dataset, derived)
    if operation.kind is OperationKind.FIGURE:
        figure = get_tool_by_name(operation.name).handler(dataset, **parameters)
        if not isinstance(figure, go.Figure):
            raise TypeError("a figure operation returned something else")
        title = str(parameters.get("title") or _pretty(str(parameters["chart_type"])))
        return Executed(
            title=title,
            headline=f"{_pretty(str(parameters['chart_type']))} chart of {dataset.row_count} rows.",
            sections=[FigureSection(title=title, figure=figure)],
        )
    result = RAW_RUNNERS[operation.name](dataset, **parameters)
    renderer = get_renderer(type(result))
    return Executed(
        title=renderer.title(result),
        headline=renderer.headline(result, level),
        sections=renderer.sections(result, level),
    )
