# File: uadas_core/data_table/__init__.py
"""Qt-free dataframe-cell formatting, lifted from
:mod:`src.ui.widgets.data_table` in the desktop->web transition's Phase 2.1.

Only ``column_formatters`` -- per-dtype value -> display-string functions
over a pandas column, plus ``MISSING_ACCESSIBLE_TEXT`` -- is Qt-free.
``PandasTableModel`` (a ``QAbstractTableModel``) and the ``QTableView``
wrapper stay under ``src/ui/`` with the shell.
"""

from __future__ import annotations
