# File: src/ui/workbench/pages/reproduce_page.py
"""The REPRODUCE stage's page: a button that replays the active dataset's recorded log.

Wraps :meth:`~src.services.analysis_orchestrator_service.AnalysisOrchestratorService.reproduce`
-- see that method's own docstring for what "replay" means (re-running each logged tool call in
order, following the chain of derived datasets a CLEAN-stage entry may have produced). This page
only asks for it via :attr:`reproduce_requested`; the actual call is
:meth:`~src.ui.controllers.pipeline_controller.PipelineController.reproduce_active_dataset`'s.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QPushButton, QVBoxLayout

from src.services.analysis_orchestrator_service import AnalysisLog, PipelineStage
from src.ui.a11y.accessible import describe
from src.ui.workbench.stage_page import StagePage

_DEFAULT_GUIDANCE = (
    "Replay every stage recorded for this dataset, in order -- the Reproducible Analysis "
    "feature. Useful after re-importing the same source data to confirm the same pipeline "
    "produces the same results."
)


class ReproducePage(StagePage):
    """The REPRODUCE stage's workbench page.

    Signals:
        reproduce_requested: Emitted when :attr:`reproduce_button` is clicked.
    """

    stage: ClassVar[PipelineStage] = PipelineStage.REPRODUCE
    help_anchor: ClassVar[str] = "pipeline.reproduce"

    reproduce_requested = Signal()

    def _build_form(self, layout: QVBoxLayout) -> None:
        self.reproduce_button = QPushButton("Reproduce", self)
        self.reproduce_button.setObjectName("reproduceButton")
        describe(
            self.reproduce_button,
            name="Reproduce recorded analysis",
            description="Replays every stage recorded for the active dataset, in order.",
            help_anchor=self.help_anchor,
        )
        self.reproduce_button.clicked.connect(self.reproduce_requested.emit)
        layout.addWidget(self.reproduce_button)

        self.set_guidance(_DEFAULT_GUIDANCE)
        self.set_result_text("No stages recorded yet for the active dataset.")

    def update_log(self, log: AnalysisLog | None) -> None:
        """Refresh the result area from ``log`` -- ``None`` means no active dataset."""
        if log is None or not log.entries:
            self.set_result_text("No stages recorded yet for the active dataset.")
            return
        stage_names = ", ".join(entry.stage.value for entry in log.entries)
        self.set_result_text(
            f"{len(log.entries)} stage(s) available to reproduce: {stage_names}."
        )
