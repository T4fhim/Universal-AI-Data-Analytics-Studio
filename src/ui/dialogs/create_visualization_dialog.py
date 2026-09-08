# File: src/ui/dialogs/create_visualization_dialog.py
"""Dialog for building a chart from the active dataset's columns.

Maps a small, fixed registry of chart-type names to their
:mod:`uadas_core.visualization` builder classes and the columns each one
needs — rather than a fully dynamic parameter form driven by
inspecting each builder's signature, which would need real parameter
introspection this project's chart classes were not built to support
(their ``build`` signatures use plain keyword arguments, not a
declarative parameter-schema format). A fixed registry is less
extensible to a chart type added later without also updating this
dialog, but is far simpler and less error-prone for the twelve chart
types this registry now lists.

**Milestone 24: rebuilt on the shared multi-select picker, unlocking Treemap/Radar.**
Before this milestone, every field got one :class:`QComboBox`, which cannot represent a
``list[str]`` parameter (Treemap's ``path_columns``, Radar's ``value_columns``) — so
:attr:`~uadas_core.visualization.chart_registry.ChartRegistration.dialog_compatible` excluded both
chart types from this dialog entirely, even though their column requirements are otherwise
exactly as expressible as any other chart's. Now a field named in
:attr:`~uadas_core.visualization.chart_registry.ChartRegistration.list_fields` gets a
:class:`~src.ui.widgets.column_multi_select.ColumnMultiSelect` instead, and
``chart_registry._register_builtins`` flips both chart types' ``dialog_compatible`` back to
``True`` (its default) now that this dialog can actually represent their fields.
"""

from __future__ import annotations

import pandas as pd
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from src.ui.widgets.column_multi_select import ColumnMultiSelect
from uadas_core.core.exceptions import ApplicationError
from uadas_core.core.logger import get_logger
from uadas_core.visualization.base_chart import BaseChart
from uadas_core.visualization.chart_registry import display_name_for, list_dialog_charts

_logger = get_logger(__name__)


# Milestone 12: sourced from uadas_core.visualization.chart_registry rather
# than a dict this dialog maintained independently — see that
# module's own docstring for why. Each entry: (builder class,
# required column-picker fields, optional column-picker fields,
# list-typed field names). Field names match each builder's own
# keyword argument names exactly, since they are passed straight
# through — see _on_accept below. Only chart_registry.
# list_dialog_charts()'s entries appear here — as of milestone 24
# that is every registered chart type (see this module's own
# docstring for why Treemap/Radar are no longer excluded).
#
# Web-transition 1.3: this was a module-level dict frozen at import. Because
# chart_registry._register_builtins() now runs inside bootstrap() -- after this
# module imports -- the frozen snapshot was empty. Recomputed per call so the
# dialog always offers whatever chart types are registered now (built-ins plus
# any plugin charts) -- the same live-read fix applied to tool_registry's
# _chart_builders() in this commit.
def _chart_registry() -> (
    dict[str, tuple[type[BaseChart], list[str], list[str], frozenset[str]]]
):
    return {
        display_name_for(name): (
            registration.chart_class,
            list(registration.required_fields),
            list(registration.optional_fields),
            frozenset(registration.list_fields),
        )
        for name, registration in list_dialog_charts().items()
    }


class CreateVisualizationDialog(QDialog):
    """A dialog for choosing a chart type and its columns, then building the figure.

    Args:
        dataframe: The active dataset's dataframe — used to populate
            column pickers and to actually build the chart.
        parent: Parent widget, typically the main window.
    """

    def __init__(self, dataframe: pd.DataFrame, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._dataframe = dataframe
        self._column_names = [str(c) for c in dataframe.columns]
        self._built_figure = None
        self._built_chart_type: str | None = None
        self._built_parameters: dict = {}

        self.setWindowTitle(self.tr("Create Visualization"))
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QFormLayout(self)

        self._title_field = QLineEdit(self)
        layout.addRow("Title (optional):", self._title_field)

        self._chart_type_combo = QComboBox(self)
        self._chart_type_combo.addItems(list(_chart_registry().keys()))
        self._chart_type_combo.currentTextChanged.connect(self._rebuild_column_fields)
        layout.addRow("Chart type:", self._chart_type_combo)

        self._column_field_layout = QFormLayout()
        layout.addRow(self._column_field_layout)
        # Milestone 24: a field's widget is either a single-column QComboBox
        # or a multi-column ColumnMultiSelect -- see _rebuild_column_fields
        # for which fields get which, driven by ChartRegistration.list_fields.
        self._column_fields: dict[str, QComboBox | ColumnMultiSelect] = {}

        self._rebuild_column_fields(self._chart_type_combo.currentText())

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        _logger.debug("CreateVisualizationDialog constructed.")

    def _rebuild_column_fields(self, chart_type_name: str) -> None:
        """Rebuild the column-picker fields for the newly selected chart type.

        Clears and repopulates ``self._column_field_layout`` each time
        the chart-type combo changes, since different chart types need
        different column pickers (e.g. Histogram needs one column,
        Scatter needs two required plus one optional) — matching the
        same clear-and-rebuild approach
        :meth:`~src.ui.menu_bar.ApplicationMenuBar.
        update_recent_projects_menu` already uses for a small,
        frequently-rebuilt UI list.
        """
        while self._column_field_layout.rowCount() > 0:
            self._column_field_layout.removeRow(0)
        self._column_fields.clear()

        _builder_class, required_fields, optional_fields, list_fields = (
            _chart_registry()[chart_type_name]
        )

        for field_name in required_fields:
            if field_name in list_fields:
                multi_select = ColumnMultiSelect(self)
                multi_select.set_columns(self._column_names)
                self._column_field_layout.addRow(
                    f"{_humanize(field_name)}:", multi_select
                )
                self._column_fields[field_name] = multi_select
            else:
                combo = QComboBox(self)
                combo.addItems(self._column_names)
                self._column_field_layout.addRow(f"{_humanize(field_name)}:", combo)
                self._column_fields[field_name] = combo

        for field_name in optional_fields:
            if field_name in list_fields:
                multi_select = ColumnMultiSelect(self)
                multi_select.set_columns(self._column_names)
                self._column_field_layout.addRow(
                    f"{_humanize(field_name)} (optional):", multi_select
                )
                self._column_fields[field_name] = multi_select
            else:
                combo = QComboBox(self)
                combo.addItem("(none)")
                combo.addItems(self._column_names)
                self._column_field_layout.addRow(
                    f"{_humanize(field_name)} (optional):", combo
                )
                self._column_fields[field_name] = combo

    def _on_accept(self) -> None:
        chart_type_name = self._chart_type_combo.currentText()
        builder_class, required_fields, _optional, _list_fields = _chart_registry()[
            chart_type_name
        ]

        parameters: dict = {}
        missing: list[str] = []
        for field_name, widget in self._column_fields.items():
            if isinstance(widget, ColumnMultiSelect):
                selected = widget.selected_columns()
                if selected:
                    parameters[field_name] = selected
                elif field_name in required_fields:
                    missing.append(field_name)
            else:
                value = widget.currentText()
                if value != "(none)":
                    parameters[field_name] = value

        if missing:
            QMessageBox.warning(
                self,
                "Missing Required Fields",
                "Please select at least one column for: "
                + ", ".join(_humanize(f) for f in missing),
            )
            return

        title = self._title_field.text().strip()
        if title:
            parameters["title"] = title

        try:
            figure = builder_class.build(self._dataframe, **parameters)
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Build Chart", str(exc))
            _logger.warning("Chart build failed: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001 -- builder_class.build() is a
            # BaseChart implementation (see uadas_core/visualization/base_chart.py), a plugin
            # extension point that can raise anything; this dialog must surface any
            # failure as a QMessageBox rather than crash the whole application.
            QMessageBox.critical(
                self, "Failed to Build Chart", f"Unexpected error: {exc}"
            )
            _logger.error("Chart build failed unexpectedly: %s", exc)
            return

        self._built_figure = figure
        self._built_chart_type = builder_class.__name__
        self._built_parameters = parameters
        self.accept()

    def get_result(self) -> tuple:
        """Return ``(figure, chart_type_name, parameters)`` after a successful accept.

        Only meaningful after :meth:`exec` has returned
        ``QDialog.DialogCode.Accepted`` — callers should not call this
        after a rejection, since the fields it reads are never
        populated on that path.
        """
        return self._built_figure, self._built_chart_type, self._built_parameters


def _humanize(field_name: str) -> str:
    """Turn a snake_case parameter name into a readable label, e.g. 'category_column' -> 'Category column'."""
    return field_name.replace("_", " ").capitalize()
