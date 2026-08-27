# File: src/ui/results/renderers/generic.py
"""The fallback renderer -- what :func:`~src.ui.results.result_renderer_registry.get_renderer`
returns for a result type nobody registered a dedicated renderer for.

Handles two real shapes rather than just stringifying everything:

* ``pandas.DataFrame`` -- :func:`~src.analysis.aggregation.aggregate` and
  :func:`~src.analysis.crosstab.cross_tabulate` are the two :mod:`src.analysis` functions with
  no dedicated result dataclass (see :mod:`~src.ui.results.result_renderer_registry`'s own
  docstring); both return a plain ``DataFrame``, which this renderer turns into a real
  :class:`~src.ui.results.base_result_renderer.TableSection` rather than a wall of ``repr()``
  text.
* ``dict`` -- a defensive path for a JSON-friendly dict (the shape :mod:`src.ai.tool_registry`'s
  own handlers return) reaching a renderer directly, rendered as a
  :class:`~src.ui.results.base_result_renderer.KeyValueSection`.

Anything else falls through to a plain :class:`~src.ui.results.base_result_renderer.ProseSection`
holding ``repr(result)`` -- deliberately unpolished rather than raising, since a renderer that
cannot fail is what makes :meth:`~src.ui.results.result_renderer_registry.get_renderer`'s own
"never raises" guarantee actually hold.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from src.core.expertise_level import ExpertiseLevel
from src.ui.results.base_result_renderer import (
    BaseResultRenderer,
    KeyValueSection,
    ProseSection,
    ResultSection,
    TableSection,
)

# Cap on rows rendered from a DataFrame result -- a generic fallback has no result-specific
# reason to know a "reasonable" size the way, say, a correlation matrix renderer would; this
# just keeps an accidentally huge aggregate/crosstab result from freezing
# :class:`~src.ui.results.result_card.ResultCard` while building hundreds of table rows.
_MAX_TABLE_ROWS = 200


class GenericResultRenderer(BaseResultRenderer):
    """Fallback renderer for any result type with no dedicated renderer registered."""

    @classmethod
    def title(cls, result: Any) -> str:
        return type(result).__name__.replace("_", " ").title() or "Result"

    @classmethod
    def headline(cls, result: Any, level: ExpertiseLevel) -> str:
        if isinstance(result, pd.DataFrame):
            return f"{len(result)} row(s), {len(result.columns)} column(s)."
        if isinstance(result, dict):
            return f"{len(result)} field(s)."
        return "No dedicated renderer is registered for this result type yet."

    @classmethod
    def sections(cls, result: Any, level: ExpertiseLevel) -> list[ResultSection]:
        if isinstance(result, pd.DataFrame):
            return [_dataframe_to_table_section(result)]
        if isinstance(result, dict):
            items = tuple((str(key), str(value)) for key, value in result.items())
            return [KeyValueSection(title="Fields", items=items)]
        return [ProseSection(title="Raw Result", text=repr(result))]

    @classmethod
    def help_anchor(cls) -> str:
        return "results.generic"


def _dataframe_to_table_section(dataframe: pd.DataFrame) -> TableSection:
    truncated = dataframe.head(_MAX_TABLE_ROWS)
    columns = tuple(str(c) for c in truncated.reset_index().columns)
    rows = tuple(
        tuple(str(value) for value in row)
        for row in truncated.reset_index().itertuples(index=False)
    )
    return TableSection(title="Result Table", columns=columns, rows=rows)
