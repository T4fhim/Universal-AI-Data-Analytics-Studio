# File: uadas_core/visualization/advanced_charts.py
"""Chart types beyond milestone 5a's original six: Heatmap, Bubble, Treemap, Radar, Waterfall, Funnel, Candlestick.

Same ``BaseChart`` shape as :mod:`~uadas_core.visualization.categorical_charts`/
:mod:`~uadas_core.visualization.continuous_charts`/
:mod:`~uadas_core.visualization.distribution_charts` — stateless classmethod,
validated inputs, a ``go.Figure`` returned directly. Grouped into one
module rather than one file per chart type since each of these seven is
short and none shares enough machinery with any *existing* chart
module to justify extending one of those instead (unlike, say,
:mod:`~uadas_core.analysis.chi_square` genuinely reusing
:mod:`~uadas_core.analysis.crosstab`).

Reuses :func:`~uadas_core.analysis.correlation.compute_correlation` for
:class:`HeatmapChart` rather than recomputing a correlation matrix
here — the same "one place this computation lives" reasoning as
:mod:`~uadas_core.analysis.chi_square` reusing ``cross_tabulate``.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from uadas_core.analysis.correlation import compute_correlation
from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.base_chart import (
    BaseChart,
    category_groups,
    validate_columns,
)


def _require_numeric(dataframe: pd.DataFrame, column: str) -> None:
    if not pd.api.types.is_numeric_dtype(dataframe[column]):
        raise ServiceError(
            f"Column '{column}' must be numeric for this chart type; "
            f"has dtype {dataframe[column].dtype}."
        )


class HeatmapChart(BaseChart):
    """A correlation matrix heatmap over the dataset's numeric columns."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        method: str = "pearson",
        title: str | None = None,
    ) -> go.Figure:
        """Build a correlation heatmap.

        Args:
            dataframe: The data to chart.
            method: Correlation method — see
                :func:`~uadas_core.analysis.correlation.compute_correlation`.
            title: Chart title.

        Raises:
            ServiceError: Propagated from
                :func:`~uadas_core.analysis.correlation.compute_correlation`
                if fewer than 2 genuinely numeric columns are available.
        """
        result = compute_correlation(dataframe, method=method)
        matrix = result.matrix

        fig = go.Figure(
            data=go.Heatmap(
                z=matrix.values,
                x=[str(c) for c in matrix.columns],
                y=[str(c) for c in matrix.index],
                colorscale="RdBu",
                zmid=0,
                text=matrix.round(2).values,
                texttemplate="%{text}",
            )
        )
        fig.update_layout(title=title or f"Correlation Heatmap ({method})")
        return fig


class BubbleChart(BaseChart):
    """A scatter plot with a third numeric dimension mapped to marker size."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        x_column: str,
        y_column: str,
        size_column: str,
        color_column: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a bubble chart.

        Args:
            dataframe: The data to chart.
            x_column: Column plotted on the x-axis. Must be numeric.
            y_column: Column plotted on the y-axis. Must be numeric.
            size_column: Column mapped to marker size. Must be numeric
                and non-negative (a negative marker size is undefined).
            color_column: If given, points are colored by this
                column's values.
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist, ``x_column``/
                ``y_column``/``size_column`` are not numeric, or
                ``size_column`` contains negative values.
        """
        columns_to_check = [x_column, y_column, size_column] + (
            [color_column] if color_column else []
        )
        validate_columns(dataframe, *columns_to_check)
        _require_numeric(dataframe, x_column)
        _require_numeric(dataframe, y_column)
        _require_numeric(dataframe, size_column)

        if (dataframe[size_column] < 0).any():
            raise ServiceError(
                f"size_column '{size_column}' contains negative values; "
                f"marker size cannot be negative."
            )

        # Plotly sizes markers by diameter in pixels — scaled here so
        # the largest bubble is a fixed, reasonable size regardless of
        # size_column's actual units, rather than raw values that
        # could render as either invisible or off-screen depending on
        # the column's scale.
        max_value = dataframe[size_column].max()
        sizeref = (2.0 * max_value / (40.0**2)) if max_value > 0 else 1.0

        marker: dict = {"sizemode": "area", "sizeref": sizeref, "sizemin": 4}
        fig = go.Figure()
        if color_column and not pd.api.types.is_numeric_dtype(dataframe[color_column]):
            # A text column cannot colour one trace (Plotly raises): one trace per category, all
            # sharing the one sizeref so bubbles stay comparable across categories.
            for label, group in category_groups(dataframe, color_column):
                fig.add_trace(
                    go.Scatter(
                        x=group[x_column],
                        y=group[y_column],
                        mode="markers",
                        name=label,
                        marker={**marker, "size": group[size_column]},
                    )
                )
        else:
            single = {**marker, "size": dataframe[size_column]}
            if color_column:
                single["color"] = dataframe[color_column]
                single["showscale"] = True
            fig.add_trace(
                go.Scatter(
                    x=dataframe[x_column],
                    y=dataframe[y_column],
                    mode="markers",
                    marker=single,
                )
            )
        fig.update_layout(
            title=title or f"{y_column} vs {x_column} (sized by {size_column})",
            xaxis_title=x_column,
            yaxis_title=y_column,
        )
        return fig


class TreemapChart(BaseChart):
    """A treemap of a numeric value broken down by one or two categorical levels."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        path_columns: list[str],
        value_column: str,
        title: str | None = None,
    ) -> go.Figure:
        """Build a treemap.

        Args:
            dataframe: The data to chart.
            path_columns: One or two categorical columns defining the
                hierarchy, outermost first (e.g. ``["region",
                "category"]``).
            value_column: Numeric column sized by; aggregated (summed)
                per hierarchy leaf.
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist,
                ``value_column`` is not numeric, ``path_columns`` is
                empty, or ``value_column`` contains negative values (a
                treemap segment cannot have negative area).
        """
        if not path_columns:
            raise ServiceError("path_columns must contain at least one column.")
        validate_columns(dataframe, *path_columns, value_column)
        _require_numeric(dataframe, value_column)

        if (dataframe[value_column] < 0).any():
            raise ServiceError(
                f"value_column '{value_column}' contains negative "
                f"values; a treemap segment cannot have negative area."
            )

        # Sum per leaf, then emit every ancestor as a node of its own: Plotly draws nothing (or a
        # wrong tree) when a parent named in ``parents`` is not itself a node, or when the same
        # label appears under two parents without unique ids. Ancestors carry value 0 with
        # ``branchvalues="remainder"``, so their area is exactly the sum of their children and
        # no float rounding can make a parent smaller than what it contains.
        leaves = dataframe.groupby(list(path_columns), dropna=False)[value_column].sum()
        paths = {
            tuple(
                str(part) for part in (key if isinstance(key, tuple) else (key,))
            ): total
            for key, total in leaves.items()
        }
        nodes: dict[tuple[str, ...], float] = {}
        for path, total in paths.items():
            for depth in range(1, len(path)):
                nodes.setdefault(path[:depth], 0.0)
            nodes[path] = float(total)
        ordered = sorted(nodes)
        fig = go.Figure(
            go.Treemap(
                ids=["/".join(path) for path in ordered],
                labels=[path[-1] for path in ordered],
                parents=["/".join(path[:-1]) for path in ordered],
                values=[nodes[path] for path in ordered],
                branchvalues="remainder",
            )
        )
        fig.update_layout(title=title or f"{value_column} by {', '.join(path_columns)}")
        return fig


class RadarChart(BaseChart):
    """A radar (spider) chart comparing multiple numeric columns across categories."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        category_column: str,
        value_columns: list[str],
        title: str | None = None,
    ) -> go.Figure:
        """Build a radar chart, one trace per row of ``dataframe``.

        Args:
            dataframe: The data to chart. Each row becomes one radar
                trace — appropriate for a small number of rows (a
                handful of products, teams, or scenarios being
                compared); a radar chart with many overlapping traces
                is not readable, but this is left to the caller to
                judge rather than enforced as a hard limit here.
            category_column: Column used to label each trace (e.g. a
                product name).
            value_columns: The numeric columns compared — these become
                the radar's axes.
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist, any
                ``value_columns`` entry is not numeric, or fewer than 3
                ``value_columns`` are given (a radar chart needs at
                least 3 axes to be a meaningfully different shape from
                a bar chart).
        """
        if len(value_columns) < 3:
            raise ServiceError(
                f"Radar chart requires at least 3 value_columns to form "
                f"a meaningful shape; got {len(value_columns)}."
            )
        validate_columns(dataframe, category_column, *value_columns)
        for column in value_columns:
            _require_numeric(dataframe, column)

        fig = go.Figure()
        for _, row in dataframe.iterrows():
            values = [row[c] for c in value_columns]
            fig.add_trace(
                go.Scatterpolar(
                    r=values + [values[0]],
                    theta=value_columns + [value_columns[0]],
                    fill="toself",
                    name=str(row[category_column]),
                )
            )
        fig.update_layout(
            title=title or f"Comparison across {', '.join(value_columns)}"
        )
        return fig


class WaterfallChart(BaseChart):
    """A waterfall chart showing cumulative effect of sequential positive/negative values."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        category_column: str,
        value_column: str,
        title: str | None = None,
    ) -> go.Figure:
        """Build a waterfall chart.

        Args:
            dataframe: The data to chart, in the order the sequential
                changes should be shown (no re-sorting is applied —
                the row order the caller provides is treated as the
                intended sequence, e.g. a chronological order already
                established upstream).
            category_column: Column labeling each step.
            value_column: Numeric column giving each step's change
                (positive or negative).
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist or
                ``value_column`` is not numeric.
        """
        validate_columns(dataframe, category_column, value_column)
        _require_numeric(dataframe, value_column)

        fig = go.Figure(
            go.Waterfall(
                x=[str(c) for c in dataframe[category_column]],
                y=dataframe[value_column],
            )
        )
        fig.update_layout(title=title or f"{value_column} by {category_column}")
        return fig


class FunnelChart(BaseChart):
    """A funnel chart showing sequential drop-off across stages."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        stage_column: str,
        value_column: str,
        title: str | None = None,
    ) -> go.Figure:
        """Build a funnel chart.

        Args:
            dataframe: The data to chart, in the order the stages
                should appear top-to-bottom (typically decreasing
                values — a conversion funnel — but this is not
                enforced; the caller's row order is what's shown).
            stage_column: Column labeling each stage.
            value_column: Numeric column giving each stage's count.
                Must be non-negative (a funnel stage cannot have
                negative volume).
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist,
                ``value_column`` is not numeric, or ``value_column``
                contains negative values.
        """
        validate_columns(dataframe, stage_column, value_column)
        _require_numeric(dataframe, value_column)

        if (dataframe[value_column] < 0).any():
            raise ServiceError(
                f"value_column '{value_column}' contains negative "
                f"values; a funnel stage cannot have negative volume."
            )

        fig = go.Figure(
            go.Funnel(
                y=[str(c) for c in dataframe[stage_column]],
                x=dataframe[value_column],
            )
        )
        fig.update_layout(title=title or f"{value_column} by {stage_column}")
        return fig


class CandlestickChart(BaseChart):
    """Price candles (open, high, low, close at each x), with an optional volume pane beneath."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        x_column: str,
        open_column: str,
        high_column: str,
        low_column: str,
        close_column: str,
        volume_column: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a candlestick chart.

        Args:
            dataframe: The data to chart, one row per period (a day, an hour).
            x_column: Column giving each candle's period — typically dates.
            open_column: Numeric column: the price at the start of the period.
            high_column: Numeric column: the highest price in the period.
            low_column: Numeric column: the lowest price in the period.
            close_column: Numeric column: the price at the end of the period.
            volume_column: Optional numeric column. If given, a bar pane
                titled "Volume" is drawn under the candles on the same x axis.
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist, or any of the
                price columns or ``volume_column`` is not numeric.
        """
        price_columns = [open_column, high_column, low_column, close_column]
        numeric_columns = price_columns + ([volume_column] if volume_column else [])
        validate_columns(dataframe, x_column, *numeric_columns)
        for column in numeric_columns:
            _require_numeric(dataframe, column)

        candles = go.Candlestick(
            x=dataframe[x_column],
            open=dataframe[open_column],
            high=dataframe[high_column],
            low=dataframe[low_column],
            close=dataframe[close_column],
            name="Price",
        )
        if volume_column:
            # The candles get three quarters of the height; the x axes are tied together so one
            # zoom or pan moves both panes.
            fig = go.Figure()
            fig.set_subplots(
                rows=2,
                cols=1,
                shared_xaxes=True,
                row_heights=[0.75, 0.25],
                vertical_spacing=0.03,
            )
            fig.add_trace(candles, row=1, col=1)
            fig.add_trace(
                go.Bar(
                    x=dataframe[x_column], y=dataframe[volume_column], name="Volume"
                ),
                row=2,
                col=1,
            )
            fig.update_xaxes(title_text=x_column, row=2, col=1)
            fig.update_yaxes(title_text="Price", row=1, col=1)
            fig.update_yaxes(title_text=volume_column, row=2, col=1)
        else:
            fig = go.Figure(candles)
            fig.update_layout(xaxis_title=x_column, yaxis_title="Price")
        # Plotly puts a range slider under every candlestick by default; it would take a third
        # of the plot, and the mode bar already zooms and pans.
        fig.update_xaxes(rangeslider_visible=False)
        fig.update_layout(title=title or f"{close_column} over {x_column}")
        return fig
