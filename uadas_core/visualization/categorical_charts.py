# File: uadas_core/visualization/categorical_charts.py
"""Bar and pie charts, both guarding against high-cardinality columns.

A categorical column with dozens or hundreds of distinct values
produces an unreadable bar chart (illegible x-axis labels) or pie
chart (indistinguishable slivers) if charted directly. Both chart
types in this module cap the number of categories shown and group the
remainder into an "Other" bucket — the same category of decision as
:class:`~uadas_core.readers.image_reader.ImageReader`'s honest handling of
OCR uncertainty: rather than silently produce a technically-valid but
practically useless chart, this is a documented, visible
transformation of the data being shown.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from uadas_core.core.exceptions import ServiceError
from uadas_core.visualization.base_chart import BaseChart, validate_columns

# Maximum distinct categories shown individually before the remainder
# is grouped into "Other". Chosen as a readability limit, not a
# statistical one — a bar chart with 15 bars is still legible; one
# with 50 is not, regardless of what the data actually contains.
_MAX_CATEGORIES = 15


def _prepare_category_counts(series: pd.Series) -> pd.Series:
    """Return value counts, with anything past _MAX_CATEGORIES grouped into 'Other'.

    Shared by both :class:`BarChart` and :class:`PieChart` since both
    need identical grouping logic — duplicating it per chart type
    would risk the two silently diverging on where the cutoff falls.
    """
    counts = series.value_counts(dropna=False)
    if len(counts) <= _MAX_CATEGORIES:
        return counts

    top = counts.iloc[: _MAX_CATEGORIES - 1]
    other_total = counts.iloc[_MAX_CATEGORIES - 1 :].sum()
    return pd.concat([top, pd.Series({"Other": other_total})])


_MISSING = "(missing)"

# The looks a bar chart with series can take besides stacked columns. "grouped" puts the series
# side by side (the Tier-1 V14 idiom); "paired" is grouped for exactly two series, drawn as
# horizontal bars with their values written at the ends (V15, a comparison against a base).
_BAR_VARIANTS = ("grouped", "paired")

# Fill patterns of a grouped chart's series, in series order: solid first, then the named patterns
# (hatch, stipple, ...). The pattern is a second channel beside colour, so two series stay apart in
# greyscale or for a reader who cannot tell the colours apart. Plotly's own names; none needs a
# colour (a pattern is drawn in its bar's colour), so the core needs no palette.
_GROUP_PATTERNS = ("", "/", ".", "x", "\\", "-", "|", "+")


def _bucket_labels(column: pd.Series) -> pd.Series:
    """Text labels for a category column; dates as dates, a missing value as its own label."""
    if pd.api.types.is_datetime64_any_dtype(column):
        known = column.dropna()
        has_time = bool((known != known.dt.normalize()).any())
        text = column.dt.strftime("%Y-%m-%d %H:%M" if has_time else "%Y-%m-%d")
    else:
        text = column.astype("object")
    return text.where(column.notna(), _MISSING).astype(str)


def _stacked_bars(
    dataframe: pd.DataFrame,
    category_column: str,
    series_column: str,
    value_column: str | None,
    title: str | None,
    incomplete_from: str | None = None,
    variant: str | None = None,
) -> go.Figure:
    """Stacked columns: one bar per category value, one segment (trace) per series value.

    With ``variant="grouped"`` the same traces sit side by side instead (the name stayed because
    everything else -- the series ordering and cap, the totals -- is shared), each series with its
    own fill pattern from :data:`_GROUP_PATTERNS`. ``"paired"`` is that for exactly two series
    (the first, by label, is the base), drawn as horizontal bars: the categories run down the y
    axis from the top, and each bar carries its value at the end, since a comparison is read off
    the numbers.

    Why the categories are *not* capped at ``_MAX_CATEGORIES`` here: the axis is usually time
    buckets (two years of months is 24), and folding the oldest months into "Other" would destroy
    the very thing the chart shows. They keep the column's own order (dates in date order). The
    **series** are the high-cardinality side, so they get the shared cutoff: the largest
    ``_MAX_CATEGORIES - 1`` stay and the rest are summed into "Other". Series are ordered by label
    (not by size) so the same data always gets the same colours; "Other" goes last.

    ``incomplete_from`` marks buckets that are still filling (an export taken mid-month). From
    that bucket onward each bar is one total in a trace named "Incomplete" -- the web skin draws
    that name hatched -- with no series split, since a partial bucket's split would read as final.
    It is opt-in and never inferred: nothing in the data says which bucket is partial, and
    labelling a finished last bucket as incomplete would be a false statement about the data.
    """
    if dataframe.empty:
        raise ServiceError("There are no rows to chart.")
    values = (
        dataframe[value_column] if value_column else pd.Series(1, index=dataframe.index)
    )
    labels = _bucket_labels(dataframe[category_column])
    ordered = pd.DataFrame({"label": labels, "key": dataframe[category_column]})
    ordered = ordered.drop_duplicates("label")
    try:
        ordered = ordered.sort_values("key", na_position="last", kind="stable")
    except TypeError:  # mixed types have no natural order; fall back to the text
        ordered = ordered.sort_values("label", kind="stable")
    categories = list(ordered["label"])

    table = pd.DataFrame(
        {
            "category": labels,
            "series": _bucket_labels(dataframe[series_column]),
            "value": values,
        }
    ).pivot_table(
        index="category",
        columns="series",
        values="value",
        aggfunc="sum",
        fill_value=0,
    )
    table = table.reindex(categories, fill_value=0)

    if table.shape[1] > _MAX_CATEGORIES:
        biggest = table.sum().sort_values(ascending=False)
        keep = list(biggest.index[: _MAX_CATEGORIES - 1])
        rest = table.drop(columns=keep).sum(axis=1)
        table = table[keep]
        table["Other"] = table["Other"] + rest if "Other" in table else rest
    names = sorted(name for name in table.columns if name != "Other")
    if "Other" in table.columns:
        names.append("Other")
    grouped = variant in ("grouped", "paired")
    paired = variant == "paired"
    if paired and len(names) != 2:
        raise ServiceError(
            f"variant 'paired' compares exactly two series; '{series_column}' has "
            f"{len(names)}."
        )

    incomplete: pd.Series | None = None
    if incomplete_from is not None:
        if incomplete_from not in categories:
            raise ServiceError(
                f"incomplete_from '{incomplete_from}' is not one of the values of "
                f"'{category_column}'."
            )
        start = categories.index(incomplete_from)
        incomplete = pd.Series(0.0, index=table.index)
        incomplete.iloc[start:] = table.iloc[start:].sum(axis=1).to_numpy()
        table.iloc[start:] = 0

    y_title = value_column or "Count"
    # One format for every label of the chart, so a pair reads off in the same units: whole numbers
    # when every value is whole, else two decimals.
    whole = bool((table.to_numpy() == table.to_numpy().round()).all())
    traces = []
    for index, name in enumerate(names):
        heights = table[name].to_numpy()
        if paired:
            bar = go.Bar(
                name=name,
                x=heights,
                y=categories,
                orientation="h",
                text=[f"{v:,.0f}" if whole else f"{v:,.2f}" for v in heights],
                textposition="outside",
                # The longest bar ends at the edge of the axis range, so its label would be cut
                # off at the plot edge.
                cliponaxis=False,
            )
        else:
            bar = go.Bar(name=name, x=categories, y=heights)
        if grouped:
            shape = _GROUP_PATTERNS[index % len(_GROUP_PATTERNS)]
            bar.update(marker={"pattern": {"shape": shape}})
        traces.append(bar)
    if incomplete is not None:
        traces.append(go.Bar(name="Incomplete", x=categories, y=incomplete.to_numpy()))
    fig = go.Figure(data=traces)
    fig.update_layout(
        barmode="group" if grouped else "stack",
        title=title or f"{y_title} by {category_column} and {series_column}",
    )
    if paired:
        # Horizontal bars start at the bottom of the axis; reading order is from the top.
        fig.update_layout(
            xaxis_title=y_title, yaxis_title=category_column, yaxis_autorange="reversed"
        )
    else:
        fig.update_layout(xaxis_title=category_column, yaxis_title=y_title)
    return fig


class BarChart(BaseChart):
    """A bar chart of value counts for a categorical column, or of a numeric column by category."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        category_column: str,
        value_column: str | None = None,
        title: str | None = None,
        series_column: str | None = None,
        incomplete_from: str | None = None,
        variant: str | None = None,
    ) -> go.Figure:
        """Build a bar chart.

        Args:
            dataframe: The data to chart.
            category_column: Column whose distinct values become bars.
            value_column: If given, bar heights are the sum of this
                numeric column per category. If omitted, bar heights
                are the count of rows per category.
            title: Chart title. Defaults to a description derived from
                the column(s) used.
            series_column: If given, each bar is stacked from one segment
                per distinct value of this column (see :func:`_stacked_bars`
                for how categories and series are ordered and capped).
            incomplete_from: A value of ``category_column`` (as it is shown on
                the axis, e.g. ``"2025-12-01"``): that bucket and every later
                one is drawn as a single "Incomplete" total. Needs
                ``series_column``; off by default.
            variant: ``"grouped"`` puts the series side by side instead of
                stacked, each with its own fill pattern (solid, hatch, stipple,
                ...) so the series differ by more than colour. Needs
                ``series_column``; ``None`` (the default) is stacked.
                ``"paired"`` is for exactly two series: horizontal bars, the
                first series (by label) the base in solid and the second the
                comparison hatched, each bar labelled with its value. A value,
                not a column, so the registry lists it under ``literal_fields``.

        Raises:
            ServiceError: If a named column does not exist, or
                ``value_column`` is given but is not numeric, or
                ``series_column`` is given and there are no rows, or
                ``incomplete_from`` is not a bucket value or is given without
                ``series_column``, or ``variant`` is not one of
                :data:`_BAR_VARIANTS`, is given without ``series_column`` or
                together with ``incomplete_from``, or is ``"paired"`` and
                ``series_column`` does not have exactly two values.
        """
        if variant is not None and variant not in _BAR_VARIANTS:
            raise ServiceError(
                f"variant {variant!r} is not one of {list(_BAR_VARIANTS)}."
            )
        if variant is not None and not series_column:
            raise ServiceError(
                f"variant {variant!r} applies to bars with series; give series_column too."
            )
        if incomplete_from is not None and not series_column:
            raise ServiceError(
                "incomplete_from applies to stacked bars only; give series_column too."
            )
        if incomplete_from is not None and variant is not None:
            raise ServiceError(
                f"incomplete_from applies to stacked bars only; it cannot be combined "
                f"with variant {variant!r}."
            )
        if series_column:
            validate_columns(
                dataframe,
                category_column,
                series_column,
                *([value_column] if value_column else []),
            )
            if value_column and not pd.api.types.is_numeric_dtype(
                dataframe[value_column]
            ):
                raise ServiceError(
                    f"value_column '{value_column}' must be numeric; "
                    f"has dtype {dataframe[value_column].dtype}."
                )
            return _stacked_bars(
                dataframe,
                category_column,
                series_column,
                value_column,
                title,
                incomplete_from,
                variant=variant,
            )
        if value_column:
            validate_columns(dataframe, category_column, value_column)
            if not pd.api.types.is_numeric_dtype(dataframe[value_column]):
                raise ServiceError(
                    f"value_column '{value_column}' must be numeric; "
                    f"has dtype {dataframe[value_column].dtype}."
                )
            grouped = dataframe.groupby(category_column, dropna=False)[
                value_column
            ].sum()
            grouped = grouped.sort_values(ascending=False)
            if len(grouped) > _MAX_CATEGORIES:
                top = grouped.iloc[: _MAX_CATEGORIES - 1]
                other_total = grouped.iloc[_MAX_CATEGORIES - 1 :].sum()
                grouped = pd.concat([top, pd.Series({"Other": other_total})])
            y_title = value_column
        else:
            validate_columns(dataframe, category_column)
            grouped = _prepare_category_counts(dataframe[category_column])
            y_title = "Count"

        fig = go.Figure(
            data=[go.Bar(x=[str(i) for i in grouped.index], y=grouped.values)]
        )
        fig.update_layout(
            title=title or f"{y_title} by {category_column}",
            xaxis_title=category_column,
            yaxis_title=y_title,
        )
        return fig


class PieChart(BaseChart):
    """A pie chart of value counts (or a numeric total) for a categorical column."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        category_column: str,
        value_column: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a pie chart. See :meth:`BarChart.build` for parameter semantics — identical."""
        if value_column:
            validate_columns(dataframe, category_column, value_column)
            if not pd.api.types.is_numeric_dtype(dataframe[value_column]):
                raise ServiceError(
                    f"value_column '{value_column}' must be numeric; "
                    f"has dtype {dataframe[value_column].dtype}."
                )
            grouped = dataframe.groupby(category_column, dropna=False)[
                value_column
            ].sum()
            grouped = grouped.sort_values(ascending=False)
            if len(grouped) > _MAX_CATEGORIES:
                top = grouped.iloc[: _MAX_CATEGORIES - 1]
                other_total = grouped.iloc[_MAX_CATEGORIES - 1 :].sum()
                grouped = pd.concat([top, pd.Series({"Other": other_total})])
        else:
            validate_columns(dataframe, category_column)
            grouped = _prepare_category_counts(dataframe[category_column])

        fig = go.Figure(
            data=[go.Pie(labels=[str(i) for i in grouped.index], values=grouped.values)]
        )
        fig.update_layout(title=title or f"Distribution of {category_column}")
        return fig
