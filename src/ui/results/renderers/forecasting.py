# File: src/ui/results/renderers/forecasting.py
"""Renders :class:`~src.forecasting.exponential_smoothing.ForecastResult` and
:class:`~src.forecasting.model_comparison.ModelComparisonResult` -- milestone 25's own two
result types.

The first :mod:`~src.ui.results.renderers` module to return a :class:`~src.ui.results.
base_result_renderer.FigureSection` -- every renderer before this one (:mod:`~src.ui.results.
renderers.regression`, :mod:`~src.ui.results.renderers.multivariate`, and siblings) summarizes
its result as tables and metrics only. A forecast's own shape genuinely needs a chart: a table of
projected numbers does not communicate "does this trend look right" the way seeing history and
projection on the same axes does, so :class:`ForecastResultRenderer` and
:class:`ModelComparisonResultRenderer` both build a real :class:`~src.visualization.
forecast_charts.ForecastChart` figure and embed it via ``FigureSection`` rather than reducing the
result to numbers alone.

:class:`ModelComparisonResultRenderer`'s ranked table marks the winning row's ``Model`` cell with
a literal ``" (Winner)"`` suffix rather than relying on :class:`~src.ui.results.result_card.
ResultCard`'s plain ``QTableWidget`` rendering to distinguish it by color or bold weight alone --
matching this overhaul's A7 accessibility rule ("never color alone"): a screen reader, a
colorblind user, and a sighted user glancing at the table all get the same unambiguous answer to
"which model won" from the cell text itself, with no change needed to ``ResultCard``'s single
shared ``TableSection`` rendering path.
"""

from __future__ import annotations

import pandas as pd

from src.core.expertise_level import ExpertiseLevel
from src.forecasting.exponential_smoothing import ForecastResult
from src.forecasting.model_comparison import ModelComparisonResult
from src.ui.results.base_result_renderer import (
    BaseResultRenderer,
    FigureSection,
    KeyValueSection,
    ResultSection,
    TableSection,
)
from src.visualization.forecast_charts import ForecastChart

# Forecast tables can run long for a large `periods` value -- capped for the same reason
# src.ui.results.renderers.generic._MAX_TABLE_ROWS caps a DataFrame result: keeping ResultCard's
# QTableWidget construction cheap, not a statement that later rows are unimportant.
_MAX_FORECAST_ROWS = 200


def _forecast_point_estimates(result: ForecastResult) -> pd.Series:
    """See :func:`~src.visualization.forecast_charts._forecast_point_estimates`'s own docstring
    for why this one-line Prophet-DataFrame normalization is kept as a private copy here rather
    than a shared import."""
    if isinstance(result.forecast_values, pd.DataFrame):
        return result.forecast_values["yhat"]
    return result.forecast_values


def _historical_dataframe(result: ForecastResult) -> tuple[pd.DataFrame, str, str]:
    """Reconstruct the (date_column, value_column) historical slice a ``ForecastResult`` was
    fit from, for :meth:`~src.visualization.forecast_charts.ForecastChart.build`'s own
    ``dataframe``/``date_column``/``value_column`` arguments -- see that module's own docstring
    for why a forecast chart's real historical data is read off the result's own series rather
    than re-fetching the caller's full active dataset."""
    date_column = result.historical_dates.name or "date"
    value_column = result.historical_values.name or "value"
    dataframe = pd.DataFrame(
        {date_column: result.historical_dates, value_column: result.historical_values}
    )
    return dataframe, str(date_column), str(value_column)


class ForecastResultRenderer(BaseResultRenderer):
    """Renderer for a single :class:`~src.forecasting.exponential_smoothing.ForecastResult`."""

    @classmethod
    def title(cls, result: ForecastResult) -> str:
        return f"{result.method.replace('_', ' ').title()} Forecast"

    @classmethod
    def headline(cls, result: ForecastResult, level: ExpertiseLevel) -> str:
        periods = len(result.forecast_dates)
        return (
            f"Projected {periods} period(s) ahead using "
            f"{result.method.replace('_', ' ')}."
        )

    @classmethod
    def sections(
        cls, result: ForecastResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        dataframe, date_column, value_column = _historical_dataframe(result)
        values = _forecast_point_estimates(result)
        rows = tuple(
            (date.isoformat(), f"{value:.4f}")
            for date, value in list(zip(result.forecast_dates, values))[
                :_MAX_FORECAST_ROWS
            ]
        )
        return [
            KeyValueSection(
                title="Summary",
                items=(
                    ("Method", result.method.replace("_", " ").title()),
                    ("Historical points", str(len(result.historical_values))),
                    ("Periods projected", str(len(result.forecast_dates))),
                ),
            ),
            TableSection(title="Forecast Values", columns=("Date", "Value"), rows=rows),
            FigureSection(
                title="Forecast Chart",
                figure=ForecastChart.build(
                    dataframe, date_column, value_column, [result]
                ),
            ),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.forecast"


class ModelComparisonResultRenderer(BaseResultRenderer):
    """Renderer for :class:`~src.forecasting.model_comparison.ModelComparisonResult` --
    the "Automatic Model Competition" result, made visible for the first time by this milestone.
    """

    @classmethod
    def title(cls, result: ModelComparisonResult) -> str:
        return "Automatic Model Competition"

    @classmethod
    def headline(cls, result: ModelComparisonResult, level: ExpertiseLevel) -> str:
        winner = result.winner
        mape_text = (
            f"{winner.mape:.2f}% MAPE"
            if winner.mape is not None
            else "no MAPE (all zero actuals)"
        )
        return (
            f"{winner.method.replace('_', ' ').title()} was the best of "
            f"{len(result.candidates)} candidate model(s) ({mape_text})."
        )

    @classmethod
    def sections(
        cls, result: ModelComparisonResult, level: ExpertiseLevel
    ) -> list[ResultSection]:
        winner_method = result.winner.method
        rows = tuple(
            (
                str(rank),
                candidate.method.replace("_", " ").title()
                + (" (Winner)" if candidate.method == winner_method else ""),
                f"{candidate.mape:.2f}%" if candidate.mape is not None else "n/a",
                f"{candidate.rmse:.4f}",
            )
            for rank, candidate in enumerate(result.candidates, start=1)
        )

        dataframe, date_column, value_column = _historical_dataframe(
            result.winner.result
        )
        overlay_figure = ForecastChart.build(
            dataframe,
            date_column,
            value_column,
            [candidate.result for candidate in result.candidates],
            winner_method=winner_method,
        )

        return [
            KeyValueSection(
                title="Summary",
                items=(
                    ("Candidates evaluated", str(len(result.candidates))),
                    ("Winning model", result.winner.method.replace("_", " ").title()),
                ),
            ),
            TableSection(
                title="Ranked Candidates",
                columns=("Rank", "Model", "MAPE", "RMSE"),
                rows=rows,
            ),
            FigureSection(title="Forecast Comparison", figure=overlay_figure),
        ]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.forecast_comparison"
