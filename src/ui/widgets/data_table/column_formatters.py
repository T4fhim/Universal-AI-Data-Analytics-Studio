# File: src/ui/widgets/data_table/column_formatters.py
"""Cell-value formatting for :class:`~src.ui.widgets.data_table.pandas_table_model.PandasTableModel`.

Kept as plain functions in their own module (rather than inlined into the
model's ``data()`` method) so they are unit-testable with zero Qt and zero
``QAbstractTableModel`` machinery -- exactly the same reasoning
``src/ui/theme/contrast.py`` documents for staying Qt-free.
"""

from __future__ import annotations

from datetime import date, datetime, time
from typing import Any

import pandas as pd

#: Rendered for a missing (NaN/NaT/None) cell's display text. An em-dash,
#: not a blank cell -- a blank cell is visually indistinguishable from a
#: real empty string, which is a different, meaningful value (see
#: is_missing's own docstring).
MISSING_DISPLAY = "—"

#: Returned for a missing cell's Qt.ItemDataRole.AccessibleTextRole. WCAG
#: 1.4.1 (never color alone) is the immediate reason this exists, but the
#: real failure mode it prevents is narrower: MISSING_DISPLAY is a visible
#: glyph, not a color, so a sighted user is never depending on color alone
#: either way -- what a screen reader needs is a *word*, since "em dash"
#: read aloud communicates nothing about the cell being empty.
MISSING_ACCESSIBLE_TEXT = "missing"


def is_missing(value: Any) -> bool:
    """Return whether ``value`` represents a missing cell.

    ``pd.isna()`` raises ``ValueError`` for array-like values (a cell that
    happens to hold a list or a small array, rather than a scalar) because
    "is this missing" is ambiguous for a collection -- caught here and
    treated as "not missing," since a non-scalar cell is a real (if
    unusual) value, not an absence of one.
    """
    if value is None:
        return True
    try:
        result = pd.isna(value)
    except (TypeError, ValueError):
        return False
    # pd.isna() on a scalar always returns a Python/numpy bool; the
    # hasattr guard only matters for the rare array-like case that can
    # still slip through despite the scalar-looking call above.
    return bool(result) if not hasattr(result, "__len__") else False


def format_value(value: Any) -> str:
    """Return ``value``'s display text.

    Missing values render as :data:`MISSING_DISPLAY`. Floats that are
    exact integers (``3.0``) render without a trailing ``.0`` -- a
    dataframe with an integer-valued float column (common after any
    operation that introduces NaN into an originally-integer column,
    forcing pandas to upcast to float64) should not visually look like it
    lost precision it never had. Other floats render at 6 significant
    figures via ``%g``, matching how ``repr(float)`` truncates
    floating-point noise without this module needing its own rounding
    policy.
    """
    if is_missing(value):
        return MISSING_DISPLAY
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f"{value:.6g}"
    if isinstance(value, (pd.Timestamp, datetime, date, time)):
        return str(value)
    return str(value)
