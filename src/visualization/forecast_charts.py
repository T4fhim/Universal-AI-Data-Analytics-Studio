# File: src/visualization/forecast_charts.py
"""The PREDICT stage's own chart family: overlays historical data with one or more forecasts.

Every other chart family in this package (:mod:`~src.visualization.categorical_charts`,
:mod:`~src.visualization.continuous_charts`, :mod:`~src.visualization.distribution_charts`)
builds a figure from a dataframe plus a handful of *column names* the caller picked. A forecast
chart is a genuinely different shape: its real input is one or more already-computed
:class:`~src.forecasting.exponential_smoothing.ForecastResult` objects (from a single
``forecast_*`` call, or from every candidate :mod:`~src.forecasting.model_comparison` fit),
not columns the user is choosing from a picker. :class:`ForecastChart` still honors
:class:`~src.visualization.base_chart.BaseChart`'s exact contract (a classmethod-only,
stateless ``build(dataframe, **kwargs) -> go.Figure``) rather than inventing a parallel chart
abstraction — the ``dataframe``/``date_column``/``value_column`` triple is still validated via
:func:`~src.visualization.base_chart.validate_columns`, it is just the *historical* slice
reconstructed from the first forecast result's own series rather than the caller's full active
dataset (which may have columns this chart has no use for).

**Not registered in** :mod:`~src.visualization.chart_registry`. That registry's
``ChartRegistration`` shape (``required_fields``/``optional_fields`` naming single dataframe
columns a picker dialog can offer as a ``QComboBox``) fits every chart type a user builds by
picking column names out of an arbitrary dataset — it does not fit a chart whose real parameter
is a list of already-fitted :class:`~src.forecasting.model_comparison.ModelCandidateResult`
objects, which nothing in :class:`~src.ui.dialogs.create_visualization_dialog.
CreateVisualizationDialog`'s or :class:`~src.ui.workbench.pages.visualize_page.VisualizePage`'s
column-picker machinery could construct. :class:`~src.ui.workbench.pages.predict_page.
PredictPage` calls :meth:`ForecastChart.build` directly instead, the same way :class:`~src.ui.
workbench.pages.explain_page.ExplainPage` calls into its own result type directly rather than
going through a registry built for a different shape of caller.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.core.exceptions import ServiceError
from src.forecasting.exponential_smoothing import ForecastResult
from src.visualization.base_chart import BaseChart, validate_columns

# Historical line color, and the visual weight given to the winning model's trace (thicker,
# solid) versus every other candidate (thinner, dotted) -- a genuinely non-color-only signal
# (per this overhaul's A7 accessibility rules: "never color alone") on top of the "(Winner)"
# text this module also appends to the winning trace's own legend label.
_HISTORICAL_COLOR = "#333333"
_WINNER_LINE_WIDTH = 3
_CANDIDATE_LINE_WIDTH = 1.5


def _forecast_point_estimates(result: ForecastResult) -> pd.Series:
    """Normalize ``ForecastResult.forecast_values`` to a plain Series of point estimates.

    Mirrors :func:`~src.forecasting.model_comparison._forecast_values_as_series` exactly (a
    Prophet result built with ``include_confidence_interval=True`` returns a DataFrame of
    ``yhat``/``lower``/``upper`` columns instead of a plain Series) -- kept as a private copy
    here rather than importing that module's private helper, since :mod:`src.visualization` has
    no other reason to depend on :mod:`~src.forecasting.model_comparison` and this one-line
    normalization is not worth introducing that coupling for.
    """
    if isinstance(result.forecast_values, pd.DataFrame):
        return result.forecast_values["yhat"]
    return result.forecast_values


class ForecastChart(BaseChart):
    """Overlays historical values with one or more forecast models' projections.

    A single-element ``forecast_results`` list renders one model's own history-plus-forecast
    (:class:`~src.ui.workbench.pages.predict_page.PredictPage`'s single-forecaster path); a
    multi-element list overlays every candidate from :func:`~src.forecasting.model_comparison.
    compare_forecast_models` on the same axes, with ``winner_method`` naming which trace to
    render as the winner -- the "Automatic Model Competition" made visible for the first time
    (see that module's own docstring for the methodology behind the ranking this chart displays).
    """

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        date_column: str,
        value_column: str,
        forecast_results: list[ForecastResult],
        winner_method: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build the overlay chart.

        Args:
            dataframe: The historical (date_column, value_column) data -- see this module's own
                docstring for why this is a reconstructed slice of a forecast result's own
                series rather than the caller's full active dataset.
            date_column: Name of the date axis, for the x-axis title.
            value_column: Name of the forecast target, for the y-axis title.
            forecast_results: One or more forecasts to overlay, sharing the same historical
                series.
            winner_method: If given, the candidate whose
                :attr:`~src.forecasting.exponential_smoothing.ForecastResult.method` matches
                this is rendered with a thicker line and "(Winner)" appended to its legend
                label. ``None`` (default) renders every candidate identically -- the shape a
                single-forecaster build uses, where there is no "winner" to distinguish.
            title: Chart title. Defaults to a name built from the forecast method(s).

        Raises:
            ServiceError: If ``date_column``/``value_column`` are not present in ``dataframe``,
                or ``forecast_results`` is empty.
        """
        validate_columns(dataframe, date_column, value_column)
        if not forecast_results:
            raise ServiceError(
                "At least one forecast result is required to build a forecast chart."
            )

        fig = go.Figure()
        history = forecast_results[0]
        fig.add_trace(
            go.Scatter(
                x=history.historical_dates,
                y=history.historical_values,
                mode="lines",
                name="Historical",
                line={"color": _HISTORICAL_COLOR},
            )
        )

        for result in forecast_results:
            values = _forecast_point_estimates(result)
            is_winner = winner_method is not None and result.method == winner_method
            label = result.method.replace("_", " ").title()
            if is_winner:
                label += " (Winner)"
            fig.add_trace(
                go.Scatter(
                    x=result.forecast_dates,
                    y=values,
                    mode="lines",
                    name=label,
                    line={
                        "width": (
                            _WINNER_LINE_WIDTH if is_winner else _CANDIDATE_LINE_WIDTH
                        ),
                        "dash": (
                            None if (is_winner or len(forecast_results) == 1) else "dot"
                        ),
                    },
                )
            )

        default_title = (
            f"{forecast_results[0].method.replace('_', ' ').title()} Forecast"
            if len(forecast_results) == 1
            else "Forecast Model Comparison"
        )
        fig.update_layout(
            title=title or default_title,
            xaxis_title=date_column,
            yaxis_title=value_column,
        )
        return fig
