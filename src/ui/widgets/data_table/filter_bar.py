# File: src/ui/widgets/data_table/filter_bar.py
"""A single search box that filters a :class:`~src.ui.widgets.data_table.data_table_view.DataTableView`.

Deliberately whole-row, substring, case-insensitive filtering -- not a
per-column query language. This is a small text box next to a table, not a
query builder; :class:`~src.ui.widgets.data_table.data_table_view.
DataTableView` is what decides how ``filter_changed``'s text is actually
turned into a boolean mask (including routing that computation through a
background worker above the plan's ~200k-row threshold), not this widget.
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from src.ui.a11y.accessible import describe


class FilterBar(QWidget):
    """A labeled, keyboard-reachable text filter.

    Signals:
        filter_changed: Emitted with the current search text on every
            keystroke (``QLineEdit.textChanged``) -- debouncing/threshold
            decisions belong to the consumer, not this widget.
    """

    filter_changed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._search = QLineEdit(self)
        self._search.setPlaceholderText("Filter rows…")
        self._search.setClearButtonEnabled(True)
        describe(
            self._search,
            name="Filter rows",
            description="Shows only rows containing this text in any column",
        )
        layout.addWidget(self._search)

        self._search.textChanged.connect(self.filter_changed)

    def text(self) -> str:
        return self._search.text()

    def clear(self) -> None:
        """Clear the search text without emitting an extra spurious signal.

        ``QLineEdit.clear()`` already emits ``textChanged("")``, which is
        exactly the notification a caller resetting the view (e.g.
        loading a new dataset) wants -- this method exists only so
        callers do not need to reach into the private ``_search`` widget
        themselves.
        """
        self._search.clear()
