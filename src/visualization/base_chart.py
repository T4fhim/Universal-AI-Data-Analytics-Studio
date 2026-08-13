# File: src/visualization/base_chart.py
"""The shared interface every chart type implements.

Mirrors :class:`~src.readers.base_reader.BaseReader` and
:class:`~src.cleaning.base_operation.BaseOperation`: stateless
classmethod-only classes, one ``build`` method, validated inputs
before any Plotly call. Returns a ``plotly.graph_objects.Figure``
directly — not a custom wrapper type — since Plotly's figure object
already is the right shape for milestone 5b to embed (via
``fig.to_html()``) and there is nothing this project needs to add on
top of it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd
import plotly.graph_objects as go

from src.core.exceptions import ServiceError


def validate_columns(dataframe: pd.DataFrame, *column_names: str) -> None:
    """Raise ServiceError naming any of ``column_names`` not present in ``dataframe``.

    Shared by every chart type in this package rather than duplicated
    per file, for the same reason
    :mod:`~src.cleaning.missing_values`'s ``_validate_columns`` helper
    was shared between its two operations.
    """
    missing = [c for c in column_names if c not in dataframe.columns]
    if missing:
        raise ServiceError(
            f"Column(s) not found: {', '.join(missing)}. Available "
            f"columns: {', '.join(str(c) for c in dataframe.columns)}."
        )


class BaseChart(ABC):
    """Abstract base class every chart type inherits from."""

    @classmethod
    @abstractmethod
    def build(cls, dataframe: pd.DataFrame, **kwargs) -> go.Figure:
        """Build and return a Plotly figure from ``dataframe``.

        Args:
            dataframe: The data to chart.
            **kwargs: Chart-specific parameters (column names, chart
                title, and so on) — documented per concrete chart type
                rather than fixed here, matching
                :meth:`~src.cleaning.base_operation.BaseOperation.apply`'s
                same reasoning.

        Raises:
            ServiceError: If a named column does not exist, or the
                data cannot be meaningfully charted (empty dataframe,
                for instance).
        """
        raise NotImplementedError
