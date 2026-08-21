# File: src/ui/workbench/pages/report_page.py
"""The REPORT stage's page: a read-only view of the recorded analysis log plus a Generate button.

Report generation itself is already fully built (milestone 13's
:class:`~src.services.report_service.ReportService`, wired through
:class:`~src.ui.controllers.report_controller.ReportController` and its
:class:`~src.ui.dialogs.generate_report_dialog.GenerateReportDialog`) -- this page does not
duplicate that dialog or its options. It only surfaces "what has this dataset's pipeline
actually recorded so far" (the thing a user deciding whether they're ready to report would
want to see) and re-emits a request to open that existing dialog, via
:attr:`generate_report_requested`, rather than reimplementing report generation here.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout

from src.services.analysis_orchestrator_service import AnalysisLog, PipelineStage
from src.ui.a11y.accessible import describe
from src.ui.workbench.stage_page import StagePage

_DEFAULT_GUIDANCE = (
    "Every prior stage's result can be included in a report. Generate one once the stages "
    "you care about have run -- reporting does not require every stage to be complete."
)


class ReportPage(StagePage):
    """The REPORT stage's workbench page.

    Signals:
        generate_report_requested: Emitted when :attr:`generate_button` is clicked --
            connected by ``main_window.py`` to
            :meth:`~src.ui.controllers.report_controller.ReportController.generate_report`,
            which already owns the whole dialog-and-worker flow.
    """

    stage: ClassVar[PipelineStage] = PipelineStage.REPORT
    help_anchor: ClassVar[str] = "pipeline.report"

    generate_report_requested = Signal()

    def _build_form(self, layout: QVBoxLayout) -> None:
        self.generate_button = QPushButton("Generate Report...", self)
        self.generate_button.setObjectName("reportGenerateButton")
        describe(
            self.generate_button,
            name="Generate report",
            description="Opens the report options dialog for the active dataset.",
            help_anchor=self.help_anchor,
        )
        self.generate_button.clicked.connect(self.generate_report_requested.emit)
        layout.addWidget(self.generate_button)

        self.set_guidance(_DEFAULT_GUIDANCE)
        self.set_result_text("No stages recorded yet for the active dataset.")

    def update_log(self, log: AnalysisLog | None) -> None:
        """Refresh the result area from ``log`` -- ``None`` means no active dataset."""
        if log is None or not log.entries:
            self.set_result_text("No stages recorded yet for the active dataset.")
            return
        stage_names = ", ".join(entry.stage.value for entry in log.entries)
        self.set_result_text(
            f"{len(log.entries)} stage(s) recorded for this dataset: {stage_names}."
        )
