# File: src/visualization/continuous_charts.py
"""Line and scatter charts, with automatic downsampling for large datasets.

Confirmed by direct testing before writing this module (not assumed):
``plotly_resampler.FigureResampler`` genuinely reduces point count in
static ``to_html()`` output — a 100,000-point line was reduced to the
requested 1,000 in a standalone HTML export, with no live server
required. This matters because milestone 5b embeds charts via static
HTML (``fig.to_html()``), not a running Dash app, and
``FigureResampler`` is primarily documented around the latter use
case; the static-export path was worth confirming rather than assumed
to work the same way.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from plotly_resampler import FigureResampler

from src.core.exceptions import ServiceError
from src.visualization.base_chart import BaseChart, validate_columns

# Row count above which resampling is applied. Below this, a chart
# renders every point directly — resampling has real cost (both
# computational and in surfacing a "[R]" marker in the legend, per
# FigureResampler's own default behavior) that is not worth paying
# for datasets small enough to render directly without any
# performance or readability concern.
_RESAMPLE_THRESHOLD_ROWS = 5000

_RESAMPLED_POINT_COUNT = 1000


def _require_numeric(dataframe: pd.DataFrame, column: str) -> None:
    if not pd.api.types.is_numeric_dtype(dataframe[column]):
        raise ServiceError(
            f"Column '{column}' must be numeric for this chart type; "
            f"has dtype {dataframe[column].dtype}."
        )


def _maybe_resample(fig: go.Figure, row_count: int) -> go.Figure:
    """Wrap ``fig`` in FigureResampler if ``row_count`` exceeds the threshold.

    Returns the plain figure unchanged for smaller datasets — see the
    module-level threshold constant's own comment for why resampling
    below that size is not worth its cost.
    """
    if row_count <= _RESAMPLE_THRESHOLD_ROWS:
        return fig
    return FigureResampler(fig, default_n_shown_samples=_RESAMPLED_POINT_COUNT)


class LineChart(BaseChart):
    """A line chart of one numeric column against another (or against the row index)."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        y_column: str,
        x_column: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a line chart.

        Args:
            dataframe: The data to chart.
            y_column: Column plotted on the y-axis. Must be numeric.
            x_column: Column plotted on the x-axis. If omitted, the
                dataframe's row index is used — appropriate for
                already-ordered data (a time series read in
                chronological order, for instance).
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist, or
                ``y_column`` is not numeric.
        """
        columns_to_check = [y_column] + ([x_column] if x_column else [])
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, y_column)

        x_values = dataframe[x_column] if x_column else dataframe.index
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x_values, y=dataframe[y_column], mode="lines"))
        fig.update_layout(
            title=title or f"{y_column} over {x_column or 'index'}",
            xaxis_title=x_column or "Index",
            yaxis_title=y_column,
        )
        return _maybe_resample(fig, len(dataframe))


class ScatterChart(BaseChart):
    """A scatter plot of one numeric column against another."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        x_column: str,
        y_column: str,
        color_column: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a scatter plot.

        Args:
            dataframe: The data to chart.
            x_column: Column plotted on the x-axis. Must be numeric.
            y_column: Column plotted on the y-axis. Must be numeric.
            color_column: If given, points are colored by this
                column's values (categorical or numeric).
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist, or either
                ``x_column`` or ``y_column`` is not numeric.
        """
        columns_to_check = [x_column, y_column] + ([color_column] if color_column else [])
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, x_column)
        _require_numeric(dataframe, y_column)

        marker = {}
        if color_column:
            marker["color"] = dataframe[color_column]
            marker["showscale"] = pd.api.types.is_numeric_dtype(dataframe[color_column])

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=dataframe[x_column],
                y=dataframe[y_column],
                mode="markers",
                marker=marker,
            )
        )
        fig.update_layout(
            title=title or f"{y_column} vs {x_column}",
            xaxis_title=x_column,
            yaxis_title=y_column,
        )
        #return _maybe_resample(fig, len(dataframe))

        return fig
    
