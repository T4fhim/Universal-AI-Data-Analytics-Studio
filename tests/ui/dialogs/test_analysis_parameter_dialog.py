# File: tests/ui/dialogs/test_analysis_parameter_dialog.py
"""Tests for the generic tool_registry-driven parameter dialog.

Never calls :meth:`QDialog.exec` -- like every other dialog test in this project's own
convention (see :mod:`tests.ui.conftest`'s ``block_modals``, which intercepts
``QMessageBox``/``QFileDialog`` for the same reason), an unguarded modal event loop would hang
offscreen. Instead these tests drive the dialog's own widgets directly, then call
:meth:`~src.ui.dialogs.analysis_parameter_dialog.AnalysisParameterDialog._on_accept` the same way
clicking "OK" would, and assert on :meth:`get_parameters`.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QLineEdit

from src.ai.tool_registry import get_tool_by_name
from src.ui.dialogs.analysis_parameter_dialog import AnalysisParameterDialog


def test_column_shaped_fields_become_combo_boxes_of_real_columns(
    qapp: QApplication,
) -> None:
    tool = get_tool_by_name("independent_t_test")
    dialog = AnalysisParameterDialog(tool, ["value", "group"])

    value_widget, _ = dialog._fields["value_column"]
    group_widget, _ = dialog._fields["group_column"]
    assert isinstance(value_widget, QComboBox)
    assert "value" in [value_widget.itemText(i) for i in range(value_widget.count())]
    assert isinstance(group_widget, QComboBox)


def test_boolean_field_becomes_a_checkbox_with_the_schema_default(
    qapp: QApplication,
) -> None:
    tool = get_tool_by_name("independent_t_test")
    dialog = AnalysisParameterDialog(tool, ["value", "group"])

    widget, schema = dialog._fields["equal_variance"]
    assert isinstance(widget, QCheckBox)
    assert widget.isChecked() == schema.get("default", False)


def test_accept_collects_parameters_and_coerces_types(qapp: QApplication) -> None:
    tool = get_tool_by_name("independent_t_test")
    dialog = AnalysisParameterDialog(tool, ["value", "group"])

    dialog._fields["value_column"][0].setCurrentText("value")
    dialog._fields["group_column"][0].setCurrentText("group")
    dialog._fields["group_a"][0].setText("A")
    dialog._fields["group_b"][0].setText("B")
    dialog._fields["equal_variance"][0].setChecked(True)

    dialog._on_accept()

    parameters = dialog.get_parameters()
    assert parameters == {
        "value_column": "value",
        "group_column": "group",
        "group_a": "A",
        "group_b": "B",
        "equal_variance": True,
    }


def test_missing_required_field_blocks_accept(qapp: QApplication, block_modals) -> None:
    tool = get_tool_by_name("independent_t_test")
    dialog = AnalysisParameterDialog(tool, ["value", "group"])
    # value_column left unset ("(none)") -- required, so accept should be blocked.

    dialog._on_accept()

    assert dialog.result() != dialog.DialogCode.Accepted
    assert any(call.kind == "warning" for call in block_modals)


def test_array_field_is_split_on_commas(qapp: QApplication) -> None:
    tool = get_tool_by_name("linear_regression")
    dialog = AnalysisParameterDialog(tool, ["y", "x1", "x2"])

    dialog._fields["target_column"][0].setCurrentText("y")
    feature_widget, _ = dialog._fields["feature_columns"]
    assert isinstance(feature_widget, QLineEdit)
    feature_widget.setText("x1, x2")

    dialog._on_accept()

    assert dialog.get_parameters()["feature_columns"] == ["x1", "x2"]
