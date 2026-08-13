# File: src/visualization/distribution_charts.py
"""Histogram and box plot charts for a numeric column's distribution."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.core.exceptions import ServiceError
from src.visualization.base_chart import BaseChart, validate_columns


class HistogramChart(BaseChart):
    """A histogram of a numeric column's value distribution."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        column: str,
        bins: int | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a histogram.

        Args:
            dataframe: The data to chart.
            column: The numeric column to bin.
            bins: Number of bins. If omitted, Plotly chooses
                automatically.
            title: Chart title.

        Raises:
            ServiceError: If ``column`` does not exist or is not
                numeric.
        """
        validate_columns(dataframe, column)
        if not pd.api.types.is_numeric_dtype(dataframe[column]):
            raise ServiceError(
                f"Column '{column}' must be numeric for a histogram; "
                f"has dtype {dataframe[column].dtype}."
            )

        histogram_kwargs = {"x": dataframe[column]}
        if bins is not None:
            histogram_kwargs["nbinsx"] = bins

        fig = go.Figure(data=[go.Histogram(**histogram_kwargs)])
        fig.update_layout(
            title=title or f"Distribution of {column}",
            xaxis_title=column,
            yaxis_title="Count",
        )
        return fig


class BoxPlotChart(BaseChart):
    """A box plot of a numeric column, optionally grouped by a categorical column."""

    @classmethod
    def build(
        cls,
        dataframe: pd.DataFrame,
        value_column: str,
        group_column: str | None = None,
        title: str | None = None,
    ) -> go.Figure:
        """Build a box plot.

        Args:
            dataframe: The data to chart.
            value_column: The numeric column to summarize.
            group_column: If given, produces one box per distinct
                value in this column, side by side. If omitted,
                produces a single box for the whole column.
            title: Chart title.

        Raises:
            ServiceError: If a named column does not exist, or
                ``value_column`` is not numeric.
        """
        columns_to_check = [value_column] + ([group_column] if group_column else [])
        validate_columns(dataframe, *columns_to_check)
        if not pd.api.types.is_numeric_dtype(dataframe[value_column]):
            raise ServiceError(
                f"value_column '{value_column}' must be numeric; "
                f"has dtype {dataframe[value_column].dtype}."
            )

        fig = go.Figure()
        if group_column:
            fig.add_trace(
                go.Box(
                    x=dataframe[group_column].astype(str),
                    y=dataframe[value_column],
                )
            )
        else:
            fig.add_trace(go.Box(y=dataframe[value_column], name=value_column))

        fig.update_layout(
            title=title or (
                f"{value_column} by {group_column}" if group_column else f"Distribution of {value_column}"
            ),
            yaxis_title=value_column,
        )
        return fig
