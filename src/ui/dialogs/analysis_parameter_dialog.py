# File: src/ui/dialogs/analysis_parameter_dialog.py
"""One generic parameter form, driven by a :class:`~src.ai.tool_registry.ToolDefinition`'s own
JSON-schema ``input_schema`` -- replacing N bespoke per-analysis-tool dialogs (milestone 22).

:class:`~src.ui.dialogs.create_visualization_dialog.CreateVisualizationDialog` took the opposite
approach for charts: a small, fixed registry mapping each chart type to its own column-picker
fields (see that module's own docstring for why -- chart ``build()`` signatures are plain
keyword arguments with no declarative schema to introspect). Every :mod:`src.ai.tool_registry`
tool, by contrast, *already* ships a JSON-schema ``input_schema`` -- written once, for the AI
API's own ``tools`` parameter -- so building 11 more copies of ``CreateVisualizationDialog``'s
one-dialog-per-type shape here would duplicate information this module can instead read
directly. A field whose name ends in ``"_column"`` (or is exactly ``"columns"``/ends in
``"_columns"``) becomes a :class:`QComboBox` of the active dataset's real column names rather
than a free-text field, the same "don't make the user retype a column name that already exists"
reasoning :class:`CreateVisualizationDialog`'s own column pickers follow -- everything else
(numbers, booleans, enums, free-form arrays) falls back to a schema-driven generic widget, since
those parameter kinds have no dataset-specific values to offer as choices.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QWidget,
)

from src.ai.tool_registry import ToolDefinition
from src.core.logger import get_logger
from src.ui.a11y.accessible import describe, label_for

_logger = get_logger(__name__)


def _is_column_field(field_name: str) -> bool:
    return (
        field_name.endswith("_column")
        or field_name == "columns"
        or field_name.endswith("_columns")
    )


def _humanize(field_name: str) -> str:
    """Turn a snake_case parameter name into a readable label -- matches
    :func:`~src.ui.dialogs.create_visualization_dialog._humanize` exactly, kept as a private
    copy rather than a shared import since the two dialogs otherwise share no code and a shared
    one-line helper is not worth a new cross-dialog dependency."""
    return field_name.replace("_", " ").capitalize()


class AnalysisParameterDialog(QDialog):
    """A parameter form built entirely from ``tool.input_schema``.

    Args:
        tool: The :class:`~src.ai.tool_registry.ToolDefinition` to collect parameters for --
            any tool works, not only analysis tools, though this milestone's callers
            (:class:`~src.ui.workbench.pages.analyze_page.AnalyzePage` and
            :class:`~src.ui.workbench.pages.explore_page.ExplorePage`) only ever pass one of the
            12 analysis tools.
        column_names: The active dataset's column names, used to populate every
            column-shaped field's picker.
        parent: Parent widget.
    """

    def __init__(
        self,
        tool: ToolDefinition,
        column_names: list[str],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._tool = tool
        self._column_names = [str(c) for c in column_names]
        self._required = set(tool.input_schema.get("required", []))
        self._parameters: dict[str, Any] = {}

        self.setWindowTitle(f"Configure: {tool.name.replace('_', ' ').title()}")
        self.setModal(True)
        self.setMinimumWidth(360)

        layout = QFormLayout(self)
        self._fields: dict[str, tuple[QWidget, dict[str, Any]]] = {}

        properties = tool.input_schema.get("properties", {})
        for field_name, schema in properties.items():
            widget = self._build_field_widget(field_name, schema)
            label_text = _humanize(field_name) + (
                " *" if field_name in self._required else " (optional)"
            )
            layout.addRow(label_text, widget)
            row_label = layout.labelForField(widget)
            if isinstance(row_label, QLabel):
                label_for(widget, row_label, name=_humanize(field_name))
            describe(
                widget,
                name=_humanize(field_name),
                description=schema.get("description") or "",
            )
            self._fields[field_name] = (widget, schema)

        button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        button_box.accepted.connect(self._on_accept)
        button_box.rejected.connect(self.reject)
        layout.addRow(button_box)

        _logger.debug("AnalysisParameterDialog constructed for tool '%s'.", tool.name)

    def _build_field_widget(self, field_name: str, schema: dict[str, Any]) -> QWidget:
        # Only a *single*-column field (schema type "string") gets the combo-box picker --
        # a "columns"/"*_columns" field whose schema type is "array" (feature_columns,
        # group_by, path_columns, ...) still matches _is_column_field's name heuristic but
        # needs the comma-separated free-text path below instead, since QComboBox has no
        # built-in multi-select (the same limitation
        # CreateVisualizationDialog._CHART_REGISTRY's own dialog_compatible=False exists to
        # route around for chart types with a list-typed field).
        if _is_column_field(field_name) and schema.get("type") != "array":
            combo = QComboBox(self)
            if field_name not in self._required:
                combo.addItem("(none)")
            combo.addItems(self._column_names)
            return combo
        if "enum" in schema:
            combo = QComboBox(self)
            if field_name not in self._required:
                combo.addItem("(none)")
            combo.addItems([str(v) for v in schema["enum"]])
            return combo
        if schema.get("type") == "boolean":
            checkbox = QCheckBox(self)
            checkbox.setChecked(bool(schema.get("default", False)))
            return checkbox
        # Numbers, arrays, and plain strings all fall back to one line edit -- arrays are
        # entered comma-separated (e.g. "col_a, col_b") and split back into a list in
        # _on_accept, matching how src.ai.tool_registry's own JSON-schema arrays are just
        # `list[str]` under the hood.
        line_edit = QLineEdit(self)
        default = schema.get("default")
        if default is not None:
            line_edit.setText(str(default))
        return line_edit

    def _on_accept(self) -> None:
        parameters: dict[str, Any] = {}
        missing: list[str] = []

        for field_name, (widget, schema) in self._fields.items():
            value = _read_field_value(widget, schema)
            if value is None or value == "":
                if field_name in self._required:
                    missing.append(field_name)
                continue
            parameters[field_name] = _coerce_value(value, schema)

        if missing:
            QMessageBox.warning(
                self,
                "Missing Required Fields",
                "Please fill in: " + ", ".join(_humanize(f) for f in missing),
            )
            return

        self._parameters = parameters
        self.accept()

    def get_parameters(self) -> dict[str, Any]:
        """Return the collected parameters after a successful accept.

        Only meaningful after :meth:`exec` returns ``QDialog.DialogCode.Accepted`` -- matches
        :meth:`~src.ui.dialogs.create_visualization_dialog.CreateVisualizationDialog.get_result`'s
        own "not populated on a rejection" contract.
        """
        return dict(self._parameters)


def _read_field_value(widget: QWidget, schema: dict[str, Any]) -> Any:
    if isinstance(widget, QComboBox):
        text = widget.currentText()
        return None if text == "(none)" else text
    if isinstance(widget, QCheckBox):
        return widget.isChecked()
    if isinstance(widget, QLineEdit):
        return widget.text().strip()
    return (
        None  # pragma: no cover -- every field is one of the three widget types above.
    )


def _coerce_value(value: Any, schema: dict[str, Any]) -> Any:
    schema_type = schema.get("type")
    if schema_type == "array" and isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if schema_type == "integer" and isinstance(value, str):
        return int(value)
    if schema_type == "number" and isinstance(value, str):
        return float(value)
    return value
