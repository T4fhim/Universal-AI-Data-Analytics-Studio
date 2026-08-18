# File: src/ui/workbench/pages/clean_page.py
"""The CLEAN stage's page: run a cleaning operation, see its before/after side by side.

Milestone 23's primary acceptance criterion: "All 5 ``operation_registry`` cleaning operations are
reachable from the Clean page -- first non-AI path to any cleaning operation." Before this
milestone, every one of :mod:`~src.cleaning.operation_registry`'s five operations
(``drop_missing_values``, ``fill_missing_values``, ``drop_duplicates``, ``normalize_text``,
``convert_type``) was reachable only through the AI assistant's tool-calling loop
(:mod:`src.ai.tool_registry`) -- a user with no AI provider configured had no way to clean data
through the UI at all, despite :mod:`src.cleaning` having existed since milestone 3b.

**Dispatches through ``operation_registry``, not ``tool_registry``, unlike its sibling pages.**
:class:`~src.ui.workbench.pages.analyze_page.AnalyzePage`/:class:`~src.ui.workbench.pages.
explore_page.ExplorePage` call :mod:`src.analysis` functions directly rather than through
:mod:`src.ai.tool_registry`'s handlers because those handlers convert a typed result dataclass
into a JSON dict, which would defeat :mod:`~src.ui.results.result_renderer_registry`'s
type-dispatch (see ``AnalyzePage``'s own docstring). Cleaning operations have no such problem --
:mod:`src.ai.tool_registry`'s own cleaning handlers (``_drop_missing_values`` and its four
siblings) are thin pass-throughs that already return the real, typed
:class:`~src.services.workspace_service.Dataset` :meth:`~src.cleaning.base_operation.
BaseOperation.apply` produced, nothing is lost by going through them. This page still bypasses
``tool_registry`` and calls :func:`~src.cleaning.operation_registry.get_operation` directly,
though, for a different reason: ``tool_registry`` is the *AI* layer's own module (see its
docstring: "Maps tool names to schemas and implementations... for the assistant"), and reaching a
cleaning operation from this page should not require importing AI-layer plumbing at all --
matching this milestone's own "first non-AI path" framing literally, not just in outcome.
:func:`~src.ai.tool_registry.get_tool_by_name` is still used for one thing:
:class:`~src.ai.tool_registry.ToolDefinition.input_schema`, which
:class:`~src.ui.dialogs.analysis_parameter_dialog.AnalysisParameterDialog` needs to build a
parameter form -- pure JSON-schema *data*, not a live AI call, the same narrow reuse
``AnalyzePage`` already established for its own parameter dialogs.

**The before/after split.** :attr:`before_table`/:attr:`after_table` are two independent
:class:`~src.ui.widgets.data_table.data_table_view.DataTableView` instances (not one view
re-loaded twice) so a user can compare the parent dataset's cells against the derived dataset's
cells simultaneously, side by side, rather than having to toggle between two states of the same
widget and rely on memory. :attr:`before_table` shows whatever :meth:`set_dataset` was last
called with (mirroring ``AnalyzePage.set_dataset``'s "display-only, no service reference" shape);
:attr:`after_table` shows the most recently produced derived dataset, populated by
:meth:`apply_operation` after a successful run.

**Emits, does not register, the derived dataset.** Like :class:`~src.ui.workbench.pages.
understand_page.UnderstandPage`'s ``run_requested``, this page holds no
:class:`~src.services.workspace_service.WorkspaceService` reference and cannot add the derived
dataset to the workspace, set it active, or push an undo command itself -- :attr:`operation_applied`
carries the new :class:`~src.services.workspace_service.Dataset` out to whichever controller
method ``main_window.py`` connects it to
(:meth:`~src.ui.controllers.pipeline_controller.PipelineController.register_clean_operation`),
which does exactly that. This keeps the "never mutate a Dataset in place" contract's *consumer*
(the command stack) entirely outside this display-only widget, matching this whole package's own
"structure here, behavior wired by the caller" rule.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.ai.tool_registry import get_tool_by_name
from src.cleaning.operation_registry import get_operation, list_operations
from src.core.exceptions import ApplicationError
from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import PipelineStage
from src.services.workspace_service import Dataset
from src.ui.a11y.accessible import describe
from src.ui.dialogs.analysis_parameter_dialog import AnalysisParameterDialog
from src.ui.widgets.data_table.data_table_view import DataTableView
from src.ui.widgets.lineage_view import LineageView
from src.ui.workbench.stage_page import StagePage

_logger = get_logger(__name__)

_DEFAULT_GUIDANCE = (
    "Clean the dataset before analyzing it -- drop or fill missing values, remove duplicate "
    "rows, normalize text, or convert a column's type. Each operation produces a new, derived "
    "dataset rather than changing this one, so nothing here is ever destructive."
)


class CleanPage(StagePage):
    """The CLEAN stage's workbench page: run an operation, compare before/after, see lineage."""

    stage: ClassVar[PipelineStage] = PipelineStage.CLEAN
    help_anchor: ClassVar[str] = "pipeline.clean"

    operation_applied = Signal(object)  # carries the new Dataset

    def __init__(self, parent: QWidget | None = None) -> None:
        self._dataset: Dataset | None = None
        super().__init__(parent)

    def _build_form(self, layout: QVBoxLayout) -> None:
        self._tool_combo = QComboBox(self)
        self._tool_combo.setObjectName("cleanToolCombo")
        for tool_name in sorted(list_operations()):
            self._tool_combo.addItem(tool_name.replace("_", " ").title(), tool_name)
        describe(
            self._tool_combo,
            name="Cleaning operation",
            description="Which cleaning operation to run against the active dataset.",
        )
        layout.addWidget(self._tool_combo)

        self.run_button = QPushButton("Configure && Run", self)
        self.run_button.setObjectName("cleanRunButton")
        describe(
            self.run_button,
            name="Configure and run cleaning operation",
            description=(
                "Opens a parameter form for the selected operation, then runs it, producing "
                "a new derived dataset."
            ),
            help_anchor=self.help_anchor,
        )
        self.run_button.clicked.connect(self._on_run_clicked)
        layout.addWidget(self.run_button)

        split_container = QWidget(self)
        split_layout = QHBoxLayout(split_container)
        split_layout.setContentsMargins(0, 0, 0, 0)

        self.before_table = DataTableView(split_container)
        describe(
            self.before_table,
            name="Before (parent dataset)",
            description="The active dataset's data before the selected operation runs.",
        )
        self.after_table = DataTableView(split_container)
        describe(
            self.after_table,
            name="After (derived dataset)",
            description="The derived dataset's data after the selected operation ran.",
        )
        split_layout.addWidget(self.before_table)
        split_layout.addWidget(self.after_table)
        layout.addWidget(split_container)

        self.lineage_view = LineageView(self)
        layout.addWidget(self.lineage_view)

        self.set_guidance(_DEFAULT_GUIDANCE)

    def set_dataset(self, dataset: Dataset | None) -> None:
        """Store the dataset this page's Run button acts on, and load it into :attr:`before_table`.

        See :meth:`~src.ui.workbench.pages.analyze_page.AnalyzePage.set_dataset`'s own docstring
        for why this page holds a plain ``Dataset`` rather than a service reference.
        """
        self._dataset = dataset
        if dataset is not None:
            self.before_table.load_dataset(dataset)

    def show_lineage(
        self,
        ancestors: list[Dataset],
        target: Dataset | None,
        descendants: list[Dataset],
    ) -> None:
        """Forward already-fetched lineage data to :attr:`lineage_view` -- see that widget's own
        docstring for why it takes plain data rather than a service reference."""
        self.lineage_view.show_lineage(ancestors, target, descendants)

    def _on_run_clicked(self) -> None:
        if self._dataset is None:
            QMessageBox.information(
                self,
                "No Active Dataset",
                "Open or select a dataset before cleaning it.",
            )
            return

        tool_name = self._tool_combo.currentData()
        tool = get_tool_by_name(tool_name)
        column_names = [str(c) for c in self._dataset.dataframe.columns]
        dialog = AnalysisParameterDialog(tool, column_names, self)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        self.apply_operation(self._dataset, tool_name, dialog.get_parameters())

    def apply_operation(
        self, dataset: Dataset, tool_name: str, parameters: dict
    ) -> Dataset | None:
        """Run ``tool_name`` against ``dataset``, render the before/after split, and emit the result.

        The method both the Run button and a test call directly -- see
        :meth:`~src.ui.workbench.pages.analyze_page.AnalyzePage.run_analysis`'s own docstring for
        why a test calls this rather than driving the parameter dialog through a full click
        sequence.

        Returns:
            The new, derived :class:`~src.services.workspace_service.Dataset` on success, or
            ``None`` if the operation name was unrecognized or it raised.
        """
        try:
            operation_class = get_operation(tool_name)
        except ApplicationError as exc:
            self.set_result_text(f"Unknown cleaning operation: {tool_name!r}.")
            _logger.warning("Unknown cleaning operation requested: %s", exc)
            return None

        try:
            derived = operation_class.apply(dataset, **parameters)
        except ApplicationError as exc:
            QMessageBox.critical(self, "Cleaning Operation Failed", str(exc))
            _logger.warning("Cleaning operation '%s' failed: %s", tool_name, exc)
            return None
        except (
            Exception
        ) as exc:  # noqa: BLE001 -- shown to the user, not swallowed silently
            QMessageBox.critical(
                self, "Cleaning Operation Failed", f"Unexpected error: {exc}"
            )
            _logger.error(
                "Cleaning operation '%s' failed unexpectedly: %s", tool_name, exc
            )
            return None

        self.after_table.load_dataset(derived)
        self.set_result_text(derived.derivation_description or f"Ran {tool_name}.")
        _logger.info(
            "Ran cleaning operation '%s' via Clean page: %s -> %s",
            tool_name,
            dataset.dataset_id,
            derived.dataset_id,
        )
        self.operation_applied.emit(derived)
        return derived
