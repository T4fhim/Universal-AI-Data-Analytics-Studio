# File: src/reports/html_exporter.py
"""Interactive HTML report exporter — embeds live, zoomable/hoverable Plotly figures.

The only exporter in this package that keeps charts interactive
(matching :class:`~src.ui.widgets.chart_view.ChartView`'s in-app
rendering) rather than flattening them to a static image, since HTML
alone among this package's four formats has a notion of an interactive
widget at all. One Plotly.js build is referenced from the CDN exactly
once, in the document head; each section's own figure is rendered with
``include_plotlyjs=False`` so the ~4MB bundle is not re-embedded once
per chart the way :class:`~src.ui.widgets.chart_view.ChartView`
embeds it per single-figure temp file (that duplication is fine for
one figure at a time in a Qt view; it would bloat a multi-section
report badly).
"""

from __future__ import annotations

import html
from pathlib import Path

from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.reports.base_exporter import BaseReportExporter
from src.reports.report_content import ReportContent, ReportSection

_logger = get_logger(__name__)

_PLOTLY_CDN_URL = "https://cdn.plot.ly/plotly-2.35.2.min.js"

_CSS = (
    "body{font-family:sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;"
    "color:#222;}"
    "h1{border-bottom:2px solid #333;padding-bottom:.5rem;}"
    "h2{margin-top:0;}"
    "section{margin-bottom:2rem;border-top:1px solid #ddd;padding-top:1rem;}"
    ".meta{color:#666;font-size:.9rem;}"
    ".explanation{background:#f5f5f5;padding:.75rem;border-radius:4px;"
    "white-space:pre-wrap;}"
)


class HtmlReportExporter(BaseReportExporter):
    """Renders a :class:`ReportContent` as a single self-contained HTML file."""

    @classmethod
    def export(cls, report_content: ReportContent, output_path: Path, **kwargs) -> Path:
        document = (
            "<!doctype html><html><head>"
            "<meta charset='utf-8'>"
            f"<title>{html.escape(report_content.title)}</title>"
            f"<script src='{_PLOTLY_CDN_URL}'></script>"
            f"<style>{_CSS}</style>"
            "</head><body>"
            f"{cls._render_body(report_content)}"
            "</body></html>"
        )
        try:
            output_path.write_text(document, encoding="utf-8")
        except OSError as exc:
            raise ServiceError(
                f"Failed to write HTML report to {output_path}: {exc}"
            ) from exc
        _logger.info("Exported HTML report to %s", output_path)
        return output_path

    @classmethod
    def _render_body(cls, report_content: ReportContent) -> str:
        parts = [
            f"<h1>{html.escape(report_content.title)}</h1>",
            "<p class='meta'>"
            f"Dataset: {html.escape(report_content.dataset_name)} &middot; "
            f"Generated: {html.escape(report_content.generated_at)} &middot; "
            f"Expertise level: {html.escape(report_content.expertise_level.value)}"
            "</p>",
            "<h2>Dataset Summary</h2><ul>",
        ]
        for key, value in report_content.dataset_summary.items():
            parts.append(
                f"<li><strong>{html.escape(str(key))}:</strong> "
                f"{html.escape(str(value))}</li>"
            )
        parts.append("</ul>")

        for section in report_content.sections:
            parts.append(cls._render_section(section))
        return "".join(parts)

    @staticmethod
    def _render_section(section: ReportSection) -> str:
        parts = ["<section>", f"<h2>{html.escape(section.stage_label)}</h2>"]
        if section.tool_name:
            parts.append(
                f"<p class='meta'>Tool: {html.escape(section.tool_name)} &middot; "
                f"{html.escape(section.timestamp)}</p>"
            )
        if section.summary_lines:
            parts.append("<ul>")
            parts.extend(
                f"<li>{html.escape(line)}</li>" for line in section.summary_lines
            )
            parts.append("</ul>")
        if section.explanation_text:
            parts.append(
                f"<p class='explanation'>{html.escape(section.explanation_text)}</p>"
            )
        if section.figure is not None:
            # include_plotlyjs=False: the one Plotly.js build already
            # referenced in the document head (see export() above)
            # covers every figure fragment rendered this way.
            parts.append(
                section.figure.to_html(full_html=False, include_plotlyjs=False)
            )
        parts.append("</section>")
        return "".join(parts)
