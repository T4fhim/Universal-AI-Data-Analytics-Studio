# File: tests/reports/test_html_exporter.py
"""Tests for src.reports.html_exporter.HtmlReportExporter.

Uses a real Plotly figure (no kaleido/rasterization involved — HTML
export keeps figures interactive via Figure.to_html, so this is fast
and does not need the monkeypatching the PDF/Word/Excel exporter tests
use).
"""

from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import pytest

from src.core.expertise_level import ExpertiseLevel
from src.reports.html_exporter import HtmlReportExporter
from src.reports.report_content import ReportContent, ReportSection


@pytest.fixture()
def report_content() -> ReportContent:
    figure = go.Figure(data=[go.Bar(x=["a", "b"], y=[1, 2])])
    return ReportContent(
        title="Sales Report",
        dataset_name="sales",
        dataset_summary={"Rows": 10, "Columns": 3},
        expertise_level=ExpertiseLevel.ANALYST,
        sections=[
            ReportSection(
                stage_label="Analyze",
                tool_name="compute_correlation",
                timestamp="2026-01-01T00:00:00+00:00",
                summary_lines=["correlation: 0.82"],
                figure=figure,
                explanation_text="Revenue and marketing spend are strongly correlated.",
            ),
            ReportSection(
                stage_label="Explain",
                tool_name=None,
                timestamp="2026-01-01T00:01:00+00:00",
                explanation_text="This is a strong positive relationship.",
            ),
        ],
    )


def test_export_writes_a_file(tmp_path: Path, report_content: ReportContent) -> None:
    output_path = tmp_path / "report.html"

    result = HtmlReportExporter.export(report_content, output_path)

    assert result == output_path
    assert output_path.exists()


def test_export_embeds_title_dataset_and_explanations(
    tmp_path: Path, report_content: ReportContent
) -> None:
    output_path = tmp_path / "report.html"

    HtmlReportExporter.export(report_content, output_path)
    html_text = output_path.read_text(encoding="utf-8")

    assert "Sales Report" in html_text
    assert "sales" in html_text
    assert "correlation: 0.82" in html_text
    assert "Revenue and marketing spend are strongly correlated." in html_text


def test_export_includes_plotlyjs_reference_once(
    tmp_path: Path, report_content: ReportContent
) -> None:
    output_path = tmp_path / "report.html"

    HtmlReportExporter.export(report_content, output_path)
    html_text = output_path.read_text(encoding="utf-8")

    assert html_text.count("cdn.plot.ly") == 1
