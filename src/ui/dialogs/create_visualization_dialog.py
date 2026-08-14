# File: src/ui/dialogs/create_visualization_dialog.py
"""Dialog for building a chart from the active dataset's columns.

Maps a small, fixed registry of chart-type names to their
:mod:`src.visualization` builder classes and the columns each one
needs — rather than a fully dynamic parameter form driven by
inspecting each builder's signature, which would need real parameter
introspection this project's chart classes were not built to support
(their ``build`` signatures use plain keyword arguments, not a
declarative parameter-schema format). A fixed registry is less
extensible to a chart type added later without also updating this
dialog, but is far simpler and less error-prone for the six chart
types milestone 5a actually built.
"""

from __future__ import annotations

import pandas as pd
from pptx import exc
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QLineEdit, QMessageBox, QWidget)

from src.core.exceptions import ApplicationError
from src.core.logger import get_logger
from src.visualization.categorical_charts import BarChart, PieChart
from src.visualization.continuous_charts import LineChart, ScatterChart
from src.visualization.distribution_charts import BoxPlotChart, HistogramChart

_logger = get_logger(__name__)

# Each entry: (builder class, required column-picker fields, optional
# column-picker fields). Field names here match each builder's own
# keyword argument names exactly, since they are passed straight
# through — see _on_accept below.
_CHART_REGISTRY: dict[str, tuple[type, list[str], list[str]]] = {
    "Bar": (BarChart, ["category_column"], ["value_column"]),
    "Pie": (PieChart, ["category_column"], ["value_column"]),
    "Line": (LineChart, ["y_column"], ["x_column"]),
    "Scatter": (ScatterChart, ["x_column", "y_column"], ["color_column"]),
    "Histogram": (HistogramChart, ["column"], []),
    "Box Plot": (BoxPlotChart, ["value_column"], ["group_column"]),
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

        self.setWindowTitle("Create Visualization")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QFormLayout(self)

        self._title_field = QLineEdit(self)
        layout.addRow("Title (optional):", self._title_field)

        self._chart_type_combo = QComboBox(self)
        self._chart_type_combo.addItems(list(_CHART_REGISTRY.keys()))
        self._chart_type_combo.currentTextChanged.connect(self._rebuild_column_fields)
        layout.addRow("Chart type:", self._chart_type_combo)

        self._column_field_layout = QFormLayout()
        layout.addRow(self._column_field_layout)
        self._column_combos: dict[str, QComboBox] = {}

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
        self._column_combos.clear()

        _builder_class, required_fields, optional_fields = _CHART_REGISTRY[chart_type_name]

        for field_name in required_fields:
            combo = QComboBox(self)
            combo.addItems(self._column_names)
            self._column_field_layout.addRow(f"{_humanize(field_name)}:", combo)
            self._column_combos[field_name] = combo

        for field_name in optional_fields:
            combo = QComboBox(self)
            combo.addItem("(none)")
            combo.addItems(self._column_names)
            self._column_field_layout.addRow(f"{_humanize(field_name)} (optional):", combo)
            self._column_combos[field_name] = combo

    def _on_accept(self) -> None:
        chart_type_name = self._chart_type_combo.currentText()
        builder_class, _required, _optional = _CHART_REGISTRY[chart_type_name]

        parameters: dict = {}
        for field_name, combo in self._column_combos.items():
            value = combo.currentText()
            if value != "(none)":
                parameters[field_name] = value

        title = self._title_field.text().strip()
        if title:
            parameters["title"] = title

        try:
            figure = builder_class.build(self._dataframe, **parameters)
        except ApplicationError as exc:
            QMessageBox.critical(self, "Failed to Build Chart", str(exc))
            _logger.warning("Chart build failed: %s", exc)
            return
        except Exception as exc:
            QMessageBox.critical(self, "Failed to Build Chart", f"Unexpected error: {exc}")
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
