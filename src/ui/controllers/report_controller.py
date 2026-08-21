# File: src/ui/controllers/report_controller.py
"""Owns report generation.

Moved out of ``main_window.py`` in milestone 19 -- see
:mod:`src.ui.controllers`'s own docstring for why this package exists.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from src.core.logger import get_logger
from src.services.analysis_orchestrator_service import (
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.report_service import ReportService
from src.services.workspace_service import WorkspaceService
from src.ui.dialogs.generate_report_dialog import GenerateReportDialog
from src.ui.dock_manager import DockManager
from src.ui.status_bar import ApplicationStatusBar
from src.ui.worker_runner import WorkerRunner

_logger = get_logger(__name__)


class ReportController:
    """Handles the Generate Report dialog and offloading report generation itself.

    Args:
        parent: The window dialogs should be parented to.
        workspace_service: The active dataset is read from here.
        orchestrator_service: Used to look up which pipeline stages have
            actually run for the active dataset, so the dialog only offers
            stages that have real content to include.
        report_service: Does the actual report generation.
        dock_manager: For appending console messages.
        status_bar: For busy/progress/message feedback.
        worker_runner: Runs report generation (rasterizes every chart via
            kaleido and writes a real file) off the UI thread.
    """

    def __init__(
        self,
        parent: QWidget,
        workspace_service: WorkspaceService,
        orchestrator_service: AnalysisOrchestratorService,
        report_service: ReportService,
        dock_manager: DockManager,
        status_bar: ApplicationStatusBar,
        worker_runner: WorkerRunner,
    ) -> None:
        self._parent = parent
        self._workspace_service = workspace_service
        self._orchestrator_service = orchestrator_service
        self._report_service = report_service
        self._dock_manager = dock_manager
        self._status_bar = status_bar
        self._worker_runner = worker_runner

    def generate_report(self) -> None:
        active_dataset = self._workspace_service.get_active_dataset()
        if active_dataset is None:
            QMessageBox.information(
                self._parent,
                "No Active Dataset",
                "Open or select a dataset before generating a report.",
            )
            return

        completed_stages = self._orchestrator_service.get_log(
            active_dataset.dataset_id
        ).completed_stages()
        available_stages = [
            stage for stage in PipelineStage if stage in completed_stages
        ]

        dialog = GenerateReportDialog(
            active_dataset.name, available_stages, self._parent
        )
        if dialog.exec() != GenerateReportDialog.DialogCode.Accepted:
            return

        options = dialog.get_result()

        # Milestone 6: report generation rasterizes every chart via
        # kaleido and writes a real file -- exactly the kind of operation
        # that must not block the UI thread, matching how
        # VisualizationController.create_dashboard offloads
        # render_dashboard.
        self._status_bar.show_busy("Generating report…")
        self._worker_runner.run(
            self._report_service.generate_report,
            active_dataset.dataset_id,
            options["output_path"],
            options["report_format"],
            options["expertise_level"],
            title=options["title"],
            included_stages=options["included_stages"],
            on_result=self._on_report_generated,
            on_error=self._on_report_generation_error,
            on_progress=self._status_bar.show_progress,
            on_finished=self._status_bar.hide_busy,
        )

    def _on_report_generated(self, output_path: Path) -> None:
        self._status_bar.show_message(f"Report saved to {output_path}")
        self._dock_manager.append_console_message(f"Generated report: {output_path}")
        _logger.info("Report generated via UI: %s", output_path)

    def _on_report_generation_error(self, exc: Exception, traceback_text: str) -> None:
        _logger.error("Report generation failed: %s\n%s", exc, traceback_text)
        self._dock_manager.append_console_message(f"⚠ Report generation failed: {exc}")
        QMessageBox.critical(self._parent, "Failed to Generate Report", str(exc))
