# File: src/services/report_service.py
"""Assembles a ReportContent from a dataset's AnalysisLog and dispatches to a format exporter.

Milestone 13's own framing (see
plans/defining-features-what-stateless-zebra.md) is "replay the log
and render it" — this service does not compute anything new. Every
number in a generated report already exists, either as a
:class:`~src.services.workspace_service.WorkspaceService`-tracked
:class:`~src.services.workspace_service.Dataset`/
:class:`~src.services.workspace_service.Visualization` or as an
:class:`~src.services.analysis_orchestrator_service.
AnalysisOrchestratorService`'s recorded
:class:`~src.services.analysis_orchestrator_service.AnalysisLogEntry`
outputs/explanation. This service's only job is walking that log and
shaping it into the :class:`~src.reports.report_content.ReportContent`
the exporters understand — keeping Reproducible Analysis (milestone 9)
and Reporting the same underlying data rather than two parallel
systems that could drift apart.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.core.exceptions import ServiceError
from src.core.expertise_level import ExpertiseLevel
from src.core.logger import get_logger
from src.reports.base_exporter import BaseReportExporter
from src.reports.excel_exporter import ExcelReportExporter
from src.reports.html_exporter import HtmlReportExporter
from src.reports.pdf_exporter import PdfReportExporter
from src.reports.report_content import ReportContent, ReportSection
from src.reports.word_exporter import WordReportExporter
from src.services.analysis_orchestrator_service import (
    AnalysisLogEntry,
    AnalysisOrchestratorService,
    PipelineStage,
)
from src.services.workspace_service import WorkspaceService

_logger = get_logger(__name__)

# Fixed, not plugin-extensible the way src.visualization.chart_registry
# / src.cleaning.operation_registry are (milestone 12): a report format
# is a whole document-assembly strategy (see each BaseReportExporter
# subclass's own module), not a single classmethod a third party could
# plausibly drop in alongside this project's four already-fixed office
# formats — src.plugins.plugin_manifest.SUPPORTED_CATEGORIES
# deliberately excludes a "report_exporters" category for the same
# reason it excludes "forecast_models".
_EXPORTERS: dict[str, type[BaseReportExporter]] = {
    "pdf": PdfReportExporter,
    "html": HtmlReportExporter,
    "docx": WordReportExporter,
    "xlsx": ExcelReportExporter,
}

_STAGE_DISPLAY_NAMES: dict[PipelineStage, str] = {
    PipelineStage.UPLOAD: "Upload",
    PipelineStage.UNDERSTAND: "Understand",
    PipelineStage.CLEAN: "Clean",
    PipelineStage.EXPLORE: "Explore",
    PipelineStage.ANALYZE: "Analyze",
    PipelineStage.VISUALIZE: "Visualize",
    PipelineStage.PREDICT: "Predict",
    PipelineStage.EXPLAIN: "Explain",
    PipelineStage.REPORT: "Report",
    PipelineStage.REPRODUCE: "Reproduce",
}


def available_formats() -> list[str]:
    """Return the format keys :meth:`ReportService.generate_report` accepts, e.g. ``['pdf', 'html', 'docx', 'xlsx']``."""
    return list(_EXPORTERS.keys())


class ReportService:
    """Builds a :class:`ReportContent` from a dataset's analysis log and exports it to a file.

    Args:
        workspace_service: Resolves the dataset (for its summary) and
            any visualization a logged stage produced.
        orchestrator_service: Supplies the
            :class:`~src.services.analysis_orchestrator_service.
            AnalysisLog` this service replays into report sections.
    """

    def __init__(
        self,
        workspace_service: WorkspaceService,
        orchestrator_service: AnalysisOrchestratorService,
    ) -> None:
        self._workspace_service = workspace_service
        self._orchestrator_service = orchestrator_service

    def build_report_content(
        self,
        dataset_id: str,
        expertise_level: ExpertiseLevel,
        title: str | None = None,
        included_stages: set[PipelineStage] | None = None,
    ) -> ReportContent:
        """Assemble a :class:`ReportContent` for ``dataset_id`` from its analysis log.

        Args:
            dataset_id: Which dataset's log to replay into a report.
            expertise_level: Recorded on the resulting
                :class:`ReportContent` as display metadata only — the
                narrative text itself is whatever was already generated
                at EXPLAIN time
                (:class:`~src.analysis.explanation.Explanation`); this
                does not re-run the AI to regenerate explanations at a
                different register, since doing so would mean a report
                always needs a live, configured AI provider (milestone
                7) even when every stage the user cares about already
                has recorded explanations from earlier in the session.
            title: Report title. Defaults to ``"<dataset name> Report"``.
            included_stages: If given, only these stages' log entries
                become sections — lets the "Generate Report" wizard's
                section checklist (see
                :mod:`src.ui.dialogs.generate_report_dialog`) skip
                stages the user doesn't want in the document. ``None``
                (the default) includes every stage the log has an
                entry for.

        Raises:
            ServiceError: If ``dataset_id`` is not currently loaded
                (propagated from
                :meth:`~src.services.workspace_service.
                WorkspaceService.get_dataset`).
        """
        dataset = self._workspace_service.get_dataset(dataset_id)
        log = self._orchestrator_service.get_log(dataset_id)

        sections: list[ReportSection] = [
            self._build_section(entry)
            for entry in log.entries
            if included_stages is None or entry.stage in included_stages
        ]

        dataset_summary: dict[str, Any] = {
            "Rows": dataset.row_count,
            "Columns": dataset.column_count,
            "Source format": dataset.source_format,
            "Column names": ", ".join(str(c) for c in dataset.dataframe.columns),
        }

        return ReportContent(
            title=title or f"{dataset.name} Report",
            dataset_name=dataset.name,
            dataset_summary=dataset_summary,
            expertise_level=expertise_level,
            sections=sections,
        )

    def _build_section(self, entry: AnalysisLogEntry) -> ReportSection:
        summary_lines = [
            f"{key}: {value}"
            for key, value in entry.outputs.items()
            if key != "visualization_id"
        ]

        figure = None
        visualization_id = entry.outputs.get("visualization_id")
        if visualization_id:
            try:
                figure = self._workspace_service.get_visualization(
                    visualization_id
                ).figure
            except ServiceError:
                # The visualization was closed since this stage ran
                # (WorkspaceService's non-cascading close — see that
                # class's own docstring) — the section still reports
                # its other outputs, just without the now-gone chart.
                _logger.debug(
                    "Report section references a closed visualization "
                    "(%s); omitting its figure.",
                    visualization_id,
                )

        return ReportSection(
            stage_label=_STAGE_DISPLAY_NAMES.get(
                entry.stage, entry.stage.value.title()
            ),
            tool_name=entry.tool_name,
            timestamp=entry.timestamp,
            summary_lines=summary_lines,
            figure=figure,
            explanation_text=_format_explanation(entry.explanation),
        )

    def generate_report(
        self,
        dataset_id: str,
        output_path: Path,
        report_format: str,
        expertise_level: ExpertiseLevel,
        title: str | None = None,
        included_stages: set[PipelineStage] | None = None,
    ) -> Path:
        """Build a :class:`ReportContent` for ``dataset_id`` and export it to ``output_path``.

        The one call the "Generate Report" UI wizard needs — combines
        :meth:`build_report_content` and an exporter dispatch so
        callers (the UI's ``BaseWorker``-wrapped handler; a future
        orchestrator REPORT-stage UI) don't need to know both steps
        exist.

        Raises:
            ServiceError: If ``report_format`` is not one of
                :func:`available_formats`, or if
                :meth:`build_report_content`/the chosen exporter raises.
        """
        exporter_class = _EXPORTERS.get(report_format)
        if exporter_class is None:
            raise ServiceError(
                f"Unknown report format {report_format!r}. "
                f"Available formats: {', '.join(available_formats())}"
            )

        content = self.build_report_content(
            dataset_id, expertise_level, title=title, included_stages=included_stages
        )
        result_path = exporter_class.export(content, output_path)
        _logger.info(
            "Generated %s report for dataset %s at %s.",
            report_format,
            dataset_id,
            result_path,
        )
        return result_path


def _format_explanation(explanation: dict[str, Any] | None) -> str:
    """Turn a stored :meth:`Explanation.to_dict` back into short, readable report text.

    Not every :class:`~src.analysis.explanation.Explanation` field is
    surfaced — only ``what`` and ``why_it_matters`` (the two fields
    meaningful to read as prose in a report body); ``assumptions``/
    ``limitations``/``alternative_approaches`` are lists meant for a
    more structured UI panel (milestone 10's result rendering), not a
    paragraph of report narrative, and are left for a future report
    section rather than force-joined into unreadable text here.
    """
    if not explanation:
        return ""
    parts = []
    if explanation.get("what"):
        parts.append(explanation["what"])
    if explanation.get("why_it_matters"):
        parts.append(f"Why it matters: {explanation['why_it_matters']}")
    return "\n\n".join(parts)
