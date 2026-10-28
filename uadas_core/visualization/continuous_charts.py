# File: uadas_core/visualization/continuous_charts.py
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

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.base_chart import (
    BaseChart,
    category_groups,
    validate_columns,
)

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


# The looks a line chart can take besides a plain line. "area" fills the line down to the baseline
# and marks the last value with a dot (the Tier-1 V02 idiom: a series whose latest value matters).
_LINE_VARIANTS = ("area",)

# Diameter in pixels of the dot on the latest value of an "area" line.
_END_DOT_SIZE = 8


def _end_dot_sizes(values: pd.Series) -> list[int]:
    """Marker sizes that are zero everywhere except on the last value that exists.

    A size per point (rather than a second one-point trace) keeps the dot the colour of its line
    without the core having to know the palette, and ``FigureResampler`` slices a size list
    along with the data and always keeps the last point, so the dot survives downsampling.
    """
    sizes = [0] * len(values)
    last = values.reset_index(drop=True).last_valid_index()
    if last is not None:
        sizes[int(last)] = _END_DOT_SIZE
    return sizes


class LineChart(BaseChart):
    """A line chart of one numeric column against another (or against the row index)."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        y_column: str,
        x_column: str | None = None,
        title: str | None = None,
        variant: str | None = None,
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
            variant: ``"area"`` fills the line down to the baseline and puts a
                dot on the last value (the last row that has one, as the line is
                drawn in row order). ``None`` (the default) is a plain line. A
                value, not a column, so the registry lists it under
                ``literal_fields``.

        Raises:
            ServiceError: If a named column does not exist,
                ``y_column`` is not numeric, or ``variant`` is not one of
                :data:`_LINE_VARIANTS`.
        """
        columns_to_check = [y_column] + ([x_column] if x_column else [])
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, y_column)
        if variant is not None and variant not in _LINE_VARIANTS:
            raise ServiceError(
                f"variant {variant!r} is not one of {list(_LINE_VARIANTS)}."
            )

        x_values = dataframe[x_column] if x_column else dataframe.index
        fig = go.Figure()
        trace = go.Scatter(x=x_values, y=dataframe[y_column], mode="lines")
        if variant == "area":
            # cliponaxis=False: the last point is the end of the axis range, so a clipped dot
            # would lose half its disc at the plot edge; Plotly still hides a point whose x is
            # outside the range, so zooming past the last value leaves no stray dot.
            trace.update(
                fill="tozeroy",
                mode="lines+markers",
                marker={"size": _end_dot_sizes(dataframe[y_column])},
                cliponaxis=False,
            )
        fig.add_trace(trace)
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
        columns_to_check = [x_column, y_column] + (
            [color_column] if color_column else []
        )
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, x_column)
        _require_numeric(dataframe, y_column)

        fig = go.Figure()
        if color_column and not pd.api.types.is_numeric_dtype(dataframe[color_column]):
            # A text column cannot colour one trace (Plotly raises): one trace per category.
            for label, group in category_groups(dataframe, color_column):
                fig.add_trace(
                    go.Scatter(
                        x=group[x_column],
                        y=group[y_column],
                        mode="markers",
                        name=label,
                    )
                )
        else:
            marker = {}
            if color_column:
                marker["color"] = dataframe[color_column]
                marker["showscale"] = True
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
        # return _maybe_resample(fig, len(dataframe))

        return fig
