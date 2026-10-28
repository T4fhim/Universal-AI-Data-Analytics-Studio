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

import contextlib
import html

import pandas as pd
import plotly.graph_objects as go

from uadas_core.analysis.correlation import compute_correlation
from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.base_chart import (
    BaseChart,
    category_groups,
    validate_columns,
)
from uadas_core.visualization.categorical_charts import ordered_buckets
from uadas_core.visualization.continuous_charts import _end_dot_sizes


def _require_numeric(dataframe: pd.DataFrame, column: str) -> None:
    if not pd.api.types.is_numeric_dtype(dataframe[column]):
        raise ServiceError(
            f"Column '{column}' must be numeric for this chart type; "
            f"has dtype {dataframe[column].dtype}."
        )


# The looks a pivot heatmap can take. "numbers" writes each cell's value in it (the Tier-1 V29
# numeric matrix); "grid" is a monochrome grid of cells set apart by a gap, no numbers (V31). The
# cells are as square as the chart's own proportions make them: Plotly cannot hold a category
# axis to a scale ratio (`scaleanchor` is ignored on one), so squares need a chart whose aspect
# ratio is the grid's columns to rows.
_HEATMAP_VARIANTS = ("numbers", "grid")

# At most this many rows, and this many columns, in a pivot heatmap: the smallest fold into
# "Other". Higher than the 15 of a bar or pie because the axes are often weeks or days.
_MAX_MATRIX = 40

# The gap between the squares of a "grid" heatmap, in pixels.
_GRID_CELL_GAP = 2


def _cap_axis(table: pd.DataFrame, limit: int) -> pd.DataFrame:
    """``table`` with at most ``limit`` columns: the ``limit - 1`` largest (by column total) stay,
    in their own order, and the rest are summed into one "Other" column after them.

    Unlike :func:`~uadas_core.visualization.categorical_charts._fold_into_other` the kept columns
    are not re-sorted by label: a matrix's axes are dates or numbers, and an order by text would
    put week 10 before week 2. An empty cell stays empty (NaN), also in the folded column when
    every folded cell was empty. Rows are capped by passing the transposed table.
    """
    if table.shape[1] <= limit:
        return table
    biggest = table.sum().sort_values(ascending=False)
    keep = set(biggest.index[: limit - 1])
    kept = [column for column in table.columns if column in keep]
    capped = table[kept].copy()
    folded = table.drop(columns=kept).sum(axis=1, min_count=1)
    if "Other" in capped:
        # A real category called "Other" among the kept ones: add to it, do not overwrite it.
        folded = pd.concat([capped["Other"], folded], axis=1).sum(axis=1, min_count=1)
    capped["Other"] = folded
    return capped


def _pivot_heatmap(
    dataframe: pd.DataFrame,
    row_column: str,
    column_column: str,
    value_column: str | None,
    variant: str | None,
    title: str | None,
) -> go.Figure:
    """A matrix of ``row_column`` by ``column_column``: each cell the sum of ``value_column``
    over its rows, or the row count.

    Rows and columns come in their own order (dates in date order, numbers in numeric order) with
    the first row at the top, as a table reads. A combination with no rows is an empty cell, not
    a zero: the hover skips it (``hoverongaps``) and no number is written in it.
    """
    if dataframe.empty:
        raise ServiceError("There are no rows to chart.")
    values = (
        dataframe[value_column] if value_column else pd.Series(1, index=dataframe.index)
    )
    row_labels, rows = ordered_buckets(dataframe[row_column])
    column_labels, columns = ordered_buckets(dataframe[column_column])
    table = (
        pd.DataFrame({"row": row_labels, "column": column_labels, "value": values})
        # min_count=1: a cell whose values are all missing stays empty, not a 0 (a plain "sum"
        # would make it one).
        .pivot_table(
            index="row",
            columns="column",
            values="value",
            aggfunc=lambda cell: cell.sum(min_count=1),
        ).reindex(index=rows, columns=columns)
    )
    table = _cap_axis(_cap_axis(table, _MAX_MATRIX).T, _MAX_MATRIX).T

    cells = table.to_numpy(dtype=float)
    heat = go.Heatmap(
        z=cells,
        x=[str(c) for c in table.columns],
        y=[str(r) for r in table.index],
        colorscale="Blues",
        hoverongaps=False,
    )
    if variant == "numbers":
        finite = cells[~pd.isna(cells)]
        whole = bool((finite == finite.round()).all())
        heat.update(
            text=[
                [
                    "" if pd.isna(v) else (f"{v:,.0f}" if whole else f"{v:,.2f}")
                    for v in row
                ]
                for row in cells
            ],
            texttemplate="%{text}",
        )
    elif variant == "grid":
        heat.update(xgap=_GRID_CELL_GAP, ygap=_GRID_CELL_GAP)
    fig = go.Figure(data=heat)
    fig.update_layout(
        title=title or f"{value_column or 'Count'} by {row_column} and {column_column}",
        xaxis_title=column_column,
        yaxis_title=row_column,
        yaxis_autorange="reversed",
    )
    return fig


class HeatmapChart(BaseChart):
    """A correlation matrix heatmap over the dataset's numeric columns, or a pivot matrix."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        method: str = "pearson",
        title: str | None = None,
        row_column: str | None = None,
        column_column: str | None = None,
        value_column: str | None = None,
        variant: str | None = None,
    ) -> go.Figure:
        """Build a heatmap: a correlation matrix, or (with ``row_column`` and ``column_column``)
        a pivot matrix of any two columns.

        Args:
            dataframe: The data to chart.
            method: Correlation method — see
                :func:`~uadas_core.analysis.correlation.compute_correlation`. Not used by
                the pivot matrix.
            title: Chart title.
            row_column: With ``column_column``: the column whose values are the rows of a pivot
                matrix. Needs ``column_column``.
            column_column: The column whose values are the columns of the matrix.
            value_column: Numeric column whose sum fills each cell; if omitted the cells
                count rows.
            variant: For the pivot matrix only. ``"numbers"`` writes each cell's value in it;
                ``"grid"`` draws a monochrome grid of cells set apart by a gap, with no numbers.
                A value, not a column, so the registry lists it under ``literal_fields``.

        Raises:
            ServiceError: Propagated from
                :func:`~uadas_core.analysis.correlation.compute_correlation`
                if fewer than 2 genuinely numeric columns are available; or, for the pivot
                matrix, if a named column does not exist, ``value_column`` is not numeric,
                only one of ``row_column``/``column_column`` is given (or the two are the
                same column), or ``variant`` is not one of :data:`_HEATMAP_VARIANTS` or is
                given without a pivot matrix.
        """
        if variant is not None and variant not in _HEATMAP_VARIANTS:
            raise ServiceError(
                f"variant {variant!r} is not one of {list(_HEATMAP_VARIANTS)}."
            )
        if row_column or column_column or value_column:
            if not (row_column and column_column):
                raise ServiceError(
                    "A pivot heatmap needs both row_column and column_column."
                )
            if row_column == column_column:
                raise ServiceError(
                    f"row_column must differ from column_column; both are '{row_column}'."
                )
            validate_columns(
                dataframe,
                row_column,
                column_column,
                *([value_column] if value_column else []),
            )
            if value_column:
                _require_numeric(dataframe, value_column)
            return _pivot_heatmap(
                dataframe, row_column, column_column, value_column, variant, title
            )
        if variant is not None:
            raise ServiceError(
                f"variant {variant!r} applies to a pivot heatmap; give row_column and "
                f"column_column."
            )
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


# The mini charts a KPI card can carry under its number (the Tier-1 V21 idiom): a line with a dot
# on the latest value (the default), bars, bars in a dash pattern (segmented), or lollipops.
_KPI_VARIANTS = ("line", "bars", "lollipop", "dashes")

# Diameter in pixels of the dot on the head of a lollipop.
_LOLLIPOP_HEAD = 6


class KpiChart(BaseChart):
    """A KPI card: the latest value and its change, over a small chart of the series."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        value_column: str,
        x_column: str | None = None,
        title: str | None = None,
        variant: str | None = None,
    ) -> go.Figure:
        """Build a KPI card.

        The number is the last value that exists, with its change from the one before it (an
        absolute change, with an arrow: direction is not left to colour alone). Under it a mini
        chart of the whole series with no axes: the card is read at a glance, the figures are in
        the number.

        Args:
            dataframe: The data, one row per period.
            value_column: Numeric column: the measure the card is about.
            x_column: Column giving each row's period for the mini chart; the rows are put in
                its order first, so the latest value is the latest period's (a row with no
                period is left out). If omitted, the row order is the time order.
            title: Chart title; the card is titled with the column's name regardless.
            variant: The mini chart: ``"line"`` (the default; a dot marks the latest value),
                ``"bars"``, ``"dashes"`` (bars in a dash pattern, so segmented) or
                ``"lollipop"``. A value, not a column, so the registry lists it under
                ``literal_fields``.

        Raises:
            ServiceError: If a named column does not exist, ``value_column`` is not numeric or has
                no values, or ``variant`` is not one of :data:`_KPI_VARIANTS`.
        """
        validate_columns(dataframe, value_column, *([x_column] if x_column else []))
        _require_numeric(dataframe, value_column)
        if variant is not None and variant not in _KPI_VARIANTS:
            raise ServiceError(
                f"variant {variant!r} is not one of {list(_KPI_VARIANTS)}."
            )
        if x_column:
            # "Latest" means latest by period, not last in the file: put the rows in x order
            # (stable, so equal periods keep their order; a missing period has no place).
            dataframe = dataframe.dropna(subset=[x_column])
            # Mixed types have no natural order: keep the row order.
            with contextlib.suppress(TypeError):
                dataframe = dataframe.sort_values(x_column, kind="stable")
        series = dataframe[value_column]
        known = series.dropna()
        if known.empty:
            raise ServiceError(f"Column '{value_column}' has no values to chart.")
        latest = float(known.iloc[-1])
        previous = float(known.iloc[-2]) if len(known) > 1 else None
        # float.is_integer, not round(): round() raises on an infinite value.
        whole = latest.is_integer() and (previous is None or previous.is_integer())
        number_format = ",.0f" if whole else ",.2f"

        card: dict = {
            "mode": "number+delta" if previous is not None else "number",
            "value": latest,
            "number": {"valueformat": number_format},
            "title": {"text": html.escape(value_column, quote=False)},
            "domain": {"x": [0, 1], "y": [0.5, 1]},
        }
        if previous is not None:
            card["delta"] = {"reference": previous, "valueformat": number_format}
        # The mini chart comes first and the card last: Plotly hands out the series colours in trace
        # order, and the card has none to take, so the series gets the first one (as in any chart).
        fig = go.Figure()

        x_values = dataframe[x_column] if x_column else dataframe.index
        look = variant or "line"
        if look == "line":
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=series,
                    mode="lines+markers",
                    marker={"size": _end_dot_sizes(series)},
                    # The latest point is at the edge of the range: do not cut its dot in half.
                    cliponaxis=False,
                )
            )
        elif look in ("bars", "dashes"):
            bar = go.Bar(x=x_values, y=series)
            if look == "dashes":
                bar.update(marker={"pattern": {"shape": "-"}})
            fig.add_trace(bar)
        else:
            # One trace, so a stem and its head are one colour: each value is a path from zero
            # up to the value with a gap (None) before the next, and the marker sizes are zero
            # on the feet and on the gaps, so only the heads show a dot.
            stem_x: list = []
            stem_y: list = []
            sizes: list[int] = []
            for x, y in zip(x_values, series, strict=True):
                if not pd.isna(y):
                    stem_x += [x, x, None]
                    stem_y += [0, y, None]
                    sizes += [0, _LOLLIPOP_HEAD, 0]
            fig.add_trace(
                go.Scatter(
                    x=stem_x,
                    y=stem_y,
                    mode="lines+markers",
                    marker={"size": sizes},
                )
            )
        fig.add_trace(go.Indicator(**card))
        fig.update_layout(
            showlegend=False,
            xaxis={"visible": False, "domain": [0, 1]},
            yaxis={"visible": False, "domain": [0, 0.42]},
        )
        if title:
            fig.update_layout(title=title)
        return fig
