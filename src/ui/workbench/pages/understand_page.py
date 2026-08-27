# File: src/ui/workbench/pages/understand_page.py
"""The UNDERSTAND stage's page: a Run button that profiles the active dataset.

This is the page acceptance-tested by milestone 20 -- clicking :attr:`run_button` is meant to
be the very first UI-driven call to
:meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.run_stage` this
application has ever made (see that service's own module docstring: before this milestone, the
whole class was orphaned except ``get_log()``). This page itself makes no such call -- it only
emits :attr:`run_requested`, which :mod:`src.ui.main_window` connects to
:meth:`~src.ui.controllers.pipeline_controller.PipelineController.run_understand_stage`, per
this package's "display-only, no service calls" rule (see ``src/ui/workbench/__init__.py``).
"""

from __future__ import annotations

from typing import Any, ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout

from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.a11y.accessible import describe
from src.ui.workbench.stage_page import StagePage

_DEFAULT_GUIDANCE = (
    "Profile the dataset first -- row/column counts, missing values, and types -- before "
    "deciding what cleaning or analysis makes sense."
)


class UnderstandPage(StagePage):
    """The UNDERSTAND stage's workbench page.

    Signals:
        run_requested: Emitted when :attr:`run_button` is clicked. Carries no arguments --
            which dataset to profile is the active dataset, which this page has no reference
            to (see this module's own docstring on why); the connected controller method
            resolves it itself.
    """

    stage: ClassVar[PipelineStage] = PipelineStage.UNDERSTAND
    help_anchor: ClassVar[str] = "pipeline.understand"

    run_requested = Signal()

    def _build_form(self, layout: QVBoxLayout) -> None:
        self.run_button = QPushButton("Run", self)
        self.run_button.setObjectName("understandRunButton")
        describe(
            self.run_button,
            name="Run Understand stage",
            description=(
                "Profiles the active dataset: row and column counts, missing "
                "values, duplicate rows, and per-column types."
            ),
            help_anchor=self.help_anchor,
        )
        self.run_button.clicked.connect(self.run_requested.emit)
        layout.addWidget(self.run_button)

        self.set_guidance(_DEFAULT_GUIDANCE)

    def show_profile_summary(self, outputs: dict[str, Any]) -> None:
        """Render a `profile_dataset` tool's ``outputs`` dict (see
        :meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.
        _summarize_result`) as the result area's text.

        Args:
            outputs: The exact dict recorded on the resulting
                :class:`~src.services.analysis_orchestrator_service.AnalysisLogEntry.outputs`
                -- this method does not reshape it, only formats the specific keys
                ``_profile_dataset`` (:mod:`src.ai.tool_registry`) always includes.
        """
        row_count = outputs.get("row_count")
        column_count = outputs.get("column_count")
        duplicate_row_count = outputs.get("duplicate_row_count")
        ambiguous_columns = outputs.get("ambiguous_type_columns") or []

        if row_count is None or column_count is None:
            # Defensive, not expected in practice: outputs always has these
            # keys for a genuine profile_dataset result. Falling back to a
            # raw dump rather than raising keeps a malformed/unexpected
            # outputs dict from crashing the UI over a display concern.
            self.set_result_text(str(outputs))
            return

        text = (
            f"Profiled: {row_count:,} rows x {column_count} columns, "
            f"{duplicate_row_count:,} duplicate row(s)."
        )
        if ambiguous_columns:
            text += f" Ambiguous-type columns: {', '.join(ambiguous_columns)}."
        self.set_result_text(text)
