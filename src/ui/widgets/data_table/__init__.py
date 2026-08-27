# File: src/ui/widgets/data_table/__init__.py
"""The missing dataframe viewer -- milestone 18.

Before this milestone, ``QTableView``/``QTableWidget``/``QAbstractTableModel``
appeared zero times in this repository. A user could open a dataset and
never see a single cell value: the Dataset Explorer only ever rendered a
dataset as ``"name (1,204 rows x 8 cols)"`` summary text. This package is
the fix -- :class:`~src.ui.widgets.data_table.data_table_view.DataTableView`
wraps a real, virtualized ``QTableView`` over
:class:`~src.ui.widgets.data_table.pandas_table_model.PandasTableModel`.
"""

from __future__ import annotations
