# File: src/reports/pdf_exporter.py
"""Static PDF report exporter via reportlab.

reportlab (already a project dependency) builds the document as a
``platypus`` flowable story — the same declarative layout approach
reportlab's own docs recommend over manually positioning text on a
canvas, since a report's section count varies with how many pipeline
stages a dataset's log has, and platypus handles page-breaking that
content automatically. Every figure is flattened to a PNG via
:func:`~src.reports.rasterize.figure_to_png_bytes`, since a PDF page
has no notion of an interactive widget.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Image as RLImage
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.reports.base_exporter import BaseReportExporter
from src.reports.rasterize import figure_to_png_bytes
from src.reports.report_content import ReportContent

_logger = get_logger(__name__)

_CHART_WIDTH_INCHES = 6.0
_CHART_HEIGHT_INCHES = 3.3


class PdfReportExporter(BaseReportExporter):
    """Renders a :class:`ReportContent` as a static PDF document."""

    @classmethod
    def export(cls, report_content: ReportContent, output_path: Path, **kwargs) -> Path:
        styles = getSampleStyleSheet()
        story = [
            Paragraph(report_content.title, styles["Title"]),
            Paragraph(
                f"Dataset: {report_content.dataset_name} &mdash; "
                f"Generated: {report_content.generated_at} &mdash; "
                f"Expertise level: {report_content.expertise_level.value}",
                styles["Normal"],
            ),
            Spacer(1, 0.25 * inch),
            Paragraph("Dataset Summary", styles["Heading2"]),
        ]
        for key, value in report_content.dataset_summary.items():
            story.append(Paragraph(f"<b>{key}:</b> {value}", styles["Normal"]))
        story.append(Spacer(1, 0.2 * inch))

        for section in report_content.sections:
            story.extend(cls._render_section_flowables(section, styles))

        try:
            document = SimpleDocTemplate(str(output_path), pagesize=LETTER)
            document.build(story)
        except Exception as exc:
            # reportlab's build() can raise a variety of its own exception
            # types (layout errors, an unrenderable flowable) depending on
            # content — not worth naming exhaustively; every case means the
            # report failed to write and the caller needs to know.
            raise ServiceError(
                f"Failed to write PDF report to {output_path}: {exc}"
            ) from exc
        _logger.info("Exported PDF report to %s", output_path)
        return output_path

    @staticmethod
    def _render_section_flowables(section, styles) -> list:
        flowables = [Paragraph(section.stage_label, styles["Heading2"])]
        if section.tool_name:
            flowables.append(
                Paragraph(
                    f"Tool: {section.tool_name} &mdash; {section.timestamp}",
                    styles["Normal"],
                )
            )
        for line in section.summary_lines:
            flowables.append(Paragraph(line, styles["Normal"]))
        if section.explanation_text:
            flowables.append(Paragraph(section.explanation_text, styles["Italic"]))
        if section.figure is not None:
            image_bytes = figure_to_png_bytes(section.figure)
            if image_bytes is not None:
                flowables.append(Spacer(1, 0.1 * inch))
                flowables.append(
                    RLImage(
                        BytesIO(image_bytes),
                        width=_CHART_WIDTH_INCHES * inch,
                        height=_CHART_HEIGHT_INCHES * inch,
                    )
                )
        flowables.append(Spacer(1, 0.2 * inch))
        return flowables
