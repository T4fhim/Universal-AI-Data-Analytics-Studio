# File: tests/reports/test_word_exporter.py
"""Tests for src.reports.word_exporter.WordReportExporter.

Same figure_to_png_bytes-monkeypatching approach as
tests/reports/test_pdf_exporter.py, for the same reason (kaleido is
slow; this module tests document assembly, not rasterization).
"""

from __future__ import annotations

import base64
from pathlib import Path

import plotly.graph_objects as go
import pytest

from src.core.expertise_level import ExpertiseLevel
from src.reports.report_content import ReportContent, ReportSection

_TINY_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


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
                explanation_text="Strongly correlated.",
            )
        ],
    )


def test_export_writes_a_docx_file(
    tmp_path: Path, report_content: ReportContent, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.reports.word_exporter.figure_to_png_bytes", lambda *a, **k: _TINY_PNG_BYTES
    )
    output_path = tmp_path / "report.docx"

    from src.reports.word_exporter import WordReportExporter

    result = WordReportExporter.export(report_content, output_path)

    assert result == output_path
    assert output_path.exists()
    assert output_path.read_bytes()[:2] == b"PK"  # docx is a zip archive


def test_export_contains_section_text(
    tmp_path: Path, report_content: ReportContent, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.reports.word_exporter.figure_to_png_bytes", lambda *a, **k: _TINY_PNG_BYTES
    )
    output_path = tmp_path / "report.docx"

    from docx import Document

    from src.reports.word_exporter import WordReportExporter

    WordReportExporter.export(report_content, output_path)
    document = Document(str(output_path))
    all_text = "\n".join(p.text for p in document.paragraphs)

    assert "Sales Report" in all_text
    assert "Strongly correlated." in all_text
