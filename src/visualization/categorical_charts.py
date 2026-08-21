# File: src/visualization/categorical_charts.py
"""Bar and pie charts, both guarding against high-cardinality columns.

A categorical column with dozens or hundreds of distinct values
produces an unreadable bar chart (illegible x-axis labels) or pie
chart (indistinguishable slivers) if charted directly. Both chart
types in this module cap the number of categories shown and group the
remainder into an "Other" bucket — the same category of decision as
:class:`~src.readers.image_reader.ImageReader`'s honest handling of
OCR uncertainty: rather than silently produce a technically-valid but
practically useless chart, this is a documented, visible
transformation of the data being shown.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.core.exceptions import ServiceError
from src.visualization.base_chart import BaseChart, validate_columns

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


class BarChart(BaseChart):
    """A bar chart of value counts for a categorical column, or of a numeric column by category."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        category_column: str,
        value_column: str | None = None,
        title: str | None = None,
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

        Raises:
            ServiceError: If a named column does not exist, or
                ``value_column`` is given but is not numeric.
        """
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
