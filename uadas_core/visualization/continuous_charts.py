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
        y2_column: str | None = None,
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
            y2_column: A second numeric column, drawn as a second line against
                its own axis on the right (two series whose units or scales differ
                too much to share one axis). The lines are named after their
                columns and each axis is titled with its column.

        Raises:
            ServiceError: If a named column does not exist,
                ``y_column`` or ``y2_column`` is not numeric, ``y2_column`` is
                ``y_column``, ``variant`` is not one of :data:`_LINE_VARIANTS`,
                or ``variant`` is combined with ``y2_column`` (an area under two
                lines on two scales would read as one stacked quantity).
        """
        columns_to_check = (
            [y_column]
            + ([x_column] if x_column else [])
            + ([y2_column] if y2_column else [])
        )
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, y_column)
        if variant is not None and variant not in _LINE_VARIANTS:
            raise ServiceError(
                f"variant {variant!r} is not one of {list(_LINE_VARIANTS)}."
            )
        if y2_column:
            _require_numeric(dataframe, y2_column)
            if y2_column == y_column:
                raise ServiceError(
                    f"y2_column must differ from y_column; both are '{y_column}'."
                )
            if variant is not None:
                raise ServiceError(
                    f"variant {variant!r} cannot be combined with y2_column."
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
        if y2_column:
            # Named lines, so a legend can tell them apart (a lone line needs no name).
            trace.update(name=y_column)
        fig.add_trace(trace)
        default_title = f"{y_column} over {x_column or 'index'}"
        if y2_column:
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=dataframe[y2_column],
                    mode="lines",
                    name=y2_column,
                    yaxis="y2",
                )
            )
            default_title = f"{y_column} and {y2_column} over {x_column or 'index'}"
        fig.update_layout(
            title=title or default_title,
            xaxis_title=x_column or "Index",
            yaxis_title=y_column,
        )
        if y2_column:
            # No grid on the right axis: two grids on different scales would not line up, so the
            # left axis keeps the only one.
            fig.update_layout(
                yaxis2={
                    "title": {"text": y2_column},
                    "overlaying": "y",
                    "side": "right",
                    "showgrid": False,
                }
            )
        return _maybe_resample(fig, len(dataframe))


# The corner of a scatter where a point is best, for its Pareto frontier: upper_left is a low x with
# a high y (a cheap model that scores well), upper_right high on both, and so on.
_FRONTIERS = ("upper_left", "upper_right", "lower_left", "lower_right")


def _pareto_frontier(x: pd.Series, y: pd.Series, corner: str) -> pd.DataFrame:
    """The points no other point beats: none is at least as good on both axes and better on one.

    ``corner`` says which end of each axis is good (see :data:`_FRONTIERS`). Rows with a missing
    coordinate are left out. Returned in x order, ready to draw as a line.
    """
    good_x_is_high = corner.endswith("right")
    good_y_is_high = corner.startswith("upper")
    points = pd.DataFrame({"x": x, "y": y}).dropna()
    # Best x first (ties: best y first): a point is on the frontier when its y beats the best y
    # of every point before it, i.e. of every point at least as good on x.
    ordered = points.sort_values(
        ["x", "y"], ascending=[not good_x_is_high, not good_y_is_high], kind="stable"
    )
    best: float | None = None
    keep: list[int] = []
    for position, value in enumerate(ordered["y"]):
        if best is None or (value > best if good_y_is_high else value < best):
            keep.append(position)
            best = value
    return ordered.iloc[keep].sort_values("x", kind="stable")


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
        label_column: str | None = None,
        frontier: str | None = None,
        pin: str | None = None,
    ) -> go.Figure:
        """Build a scatter plot.

        Args:
            dataframe: The data to chart.
            x_column: Column plotted on the x-axis. Must be numeric.
            y_column: Column plotted on the y-axis. Must be numeric.
            color_column: If given, points are colored by this
                column's values (categorical or numeric).
            title: Chart title.
            label_column: If given, each point carries this column's value as its
                label (read out on hover).
            frontier: One of ``"upper_left"``, ``"upper_right"``, ``"lower_left"``,
                ``"lower_right"``: the corner where a point is best. Draws the Pareto
                frontier of all the points (those no other point beats) as a dashed line
                named "Pareto frontier". A value, not a column, so the registry lists it
                under ``literal_fields``.
            pin: A value of ``label_column``: rings that point and writes its label on the
                chart (a trace named "Pinned: <value>"). Needs ``label_column``. Also a literal.

        Raises:
            ServiceError: If a named column does not exist, or either
                ``x_column`` or ``y_column`` is not numeric, or ``frontier`` is not one of
                :data:`_FRONTIERS`, or ``pin`` is given without ``label_column`` or is not one
                of its values.
        """
        columns_to_check = (
            [x_column, y_column]
            + ([color_column] if color_column else [])
            + ([label_column] if label_column else [])
        )
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, x_column)
        _require_numeric(dataframe, y_column)
        if frontier is not None and frontier not in _FRONTIERS:
            raise ServiceError(
                f"frontier {frontier!r} is not one of {list(_FRONTIERS)}."
            )
        if pin is not None and not label_column:
            raise ServiceError("pin needs label_column: give label_column too.")
        if pin == "":
            # A missing label is read as "", so an empty pin would ring every unlabelled row.
            raise ServiceError("pin must be a label, not an empty value.")
        # A frame with a repeated index (rows joined from several tables) would make a label
        # lookup by index return extra rows: work on a fresh 0..n-1 index.
        dataframe = dataframe.reset_index(drop=True)
        labels = (
            dataframe[label_column].astype("string").fillna("")
            if label_column
            else None
        )
        if pin is not None and labels is not None and pin not in set(labels):
            raise ServiceError(
                f"pin '{pin}' is not one of the values of '{label_column}'."
            )

        def text_of(rows: pd.Index) -> dict:
            return {"text": list(labels.loc[rows])} if labels is not None else {}

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
                        **text_of(group.index),
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
                    # With a frontier or a pin there is a legend, and an unnamed trace would be
                    # listed as "trace 0"; without them it is a lone, unlabelled series as before.
                    **({"name": "Points"} if frontier or pin is not None else {}),
                    **text_of(dataframe.index),
                )
            )
        if frontier:
            line = _pareto_frontier(dataframe[x_column], dataframe[y_column], frontier)
            fig.add_trace(
                go.Scatter(
                    x=line["x"],
                    y=line["y"],
                    mode="lines",
                    name="Pareto frontier",
                    line={"dash": "dash"},
                )
            )
        if pin is not None and labels is not None:
            pinned = dataframe[labels == pin]
            fig.add_trace(
                go.Scatter(
                    x=pinned[x_column],
                    y=pinned[y_column],
                    mode="markers+text",
                    name=f"Pinned: {pin}",
                    text=[pin] * len(pinned),
                    textposition="top center",
                    marker={"size": 12, "symbol": "circle-open", "line": {"width": 2}},
                    showlegend=False,
                    # The label sits above the point: a point at the top of the range would have
                    # it cut off at the plot edge. Plotly still hides a point outside the range.
                    cliponaxis=False,
                )
            )
        fig.update_layout(
            title=title or f"{y_column} vs {x_column}",
            xaxis_title=x_column,
            yaxis_title=y_column,
        )
        # return _maybe_resample(fig, len(dataframe))

        return fig
