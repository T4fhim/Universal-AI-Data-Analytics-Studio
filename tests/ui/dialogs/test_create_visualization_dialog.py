# File: tests/ui/dialogs/test_create_visualization_dialog.py
"""Tests for CreateVisualizationDialog -- milestone 24's Treemap/Radar acceptance criterion.

Never calls :meth:`QDialog.exec` -- see :mod:`tests.ui.dialogs.test_analysis_parameter_dialog`'s
own docstring for why every dialog test in this project's convention drives the dialog's widgets
directly and calls its private accept handler instead.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
from PySide6.QtWidgets import QApplication, QComboBox

from src.ui.dialogs.create_visualization_dialog import CreateVisualizationDialog
from src.ui.widgets.column_multi_select import ColumnMultiSelect


def _sample_dataframe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "region": ["east", "east", "west", "west"],
            "product": ["a", "b", "a", "b"],
            "revenue": [10, 20, 30, 40],
            "cost": [1, 2, 3, 4],
            "profit": [9, 18, 27, 36],
        }
    )


def test_all_twelve_chart_types_are_offered(qapp: QApplication) -> None:
    dialog = CreateVisualizationDialog(_sample_dataframe())
    assert dialog._chart_type_combo.count() == 12
    names = {dialog._chart_type_combo.itemText(i) for i in range(12)}
    assert "Treemap" in names
    assert "Radar" in names


def test_treemap_path_columns_field_is_a_multi_select(qapp: QApplication) -> None:
    dialog = CreateVisualizationDialog(_sample_dataframe())
    dialog._chart_type_combo.setCurrentText("Treemap")

    assert isinstance(dialog._column_fields["path_columns"], ColumnMultiSelect)
    assert isinstance(dialog._column_fields["value_column"], QComboBox)


def test_treemap_builds_a_real_figure_from_a_multi_column_selection(
    qapp: QApplication,
) -> None:
    dialog = CreateVisualizationDialog(_sample_dataframe())
    dialog._chart_type_combo.setCurrentText("Treemap")

    dialog._column_fields["path_columns"].set_selected_columns(["region", "product"])
    dialog._column_fields["value_column"].setCurrentText("revenue")

    dialog._on_accept()

    figure, chart_type_name, parameters = dialog.get_result()
    assert isinstance(figure, go.Figure)
    assert chart_type_name == "TreemapChart"
    assert parameters["path_columns"] == ["region", "product"]
    assert parameters["value_column"] == "revenue"


def test_radar_builds_a_real_figure_from_a_multi_column_selection(
    qapp: QApplication,
) -> None:
    dialog = CreateVisualizationDialog(_sample_dataframe())
    dialog._chart_type_combo.setCurrentText("Radar")

    dialog._column_fields["category_column"].setCurrentText("region")
    dialog._column_fields["value_columns"].set_selected_columns(
        ["revenue", "cost", "profit"]
    )

    dialog._on_accept()

    figure, chart_type_name, parameters = dialog.get_result()
    assert isinstance(figure, go.Figure)
    assert chart_type_name == "RadarChart"
    assert parameters["value_columns"] == ["revenue", "cost", "profit"]


def test_treemap_with_no_path_columns_selected_shows_missing_field_warning(
    qapp: QApplication,
) -> None:
    dialog = CreateVisualizationDialog(_sample_dataframe())
    dialog._chart_type_combo.setCurrentText("Treemap")
    dialog._column_fields["value_column"].setCurrentText("revenue")
    # path_columns left with nothing checked.

    dialog._on_accept()

    # No figure was built -- the dialog did not accept.
    figure, _chart_type, _parameters = dialog.get_result()
    assert figure is None
