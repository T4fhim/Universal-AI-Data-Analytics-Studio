# File: tests/reports/test_pdf_exporter.py
"""Tests for src.reports.pdf_exporter.PdfReportExporter.

figure_to_png_bytes is monkeypatched to a tiny real PNG rather than
calling kaleido — kaleido's headless-Chrome rendering takes several
seconds per call (see tests/reports/test_rasterize.py's own docstring
for the one test that exercises it for real), which would make this
otherwise-fast exporter test slow for no additional coverage: this
module tests PDF assembly, not kaleido itself.
"""

from __future__ import annotations

import base64
from pathlib import Path

import plotly.graph_objects as go
import pytest

from src.core.expertise_level import ExpertiseLevel
from src.reports.report_content import ReportContent, ReportSection

# A genuine, minimal 1x1 PNG — real image bytes are required since
# reportlab's Image flowable parses them (via Pillow) to determine
# dimensions, not just embeds an opaque blob.
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


def test_export_writes_a_pdf_file(
    tmp_path: Path, report_content: ReportContent, monkeypatch
) -> None:
    monkeypatch.setattr(
        "src.reports.pdf_exporter.figure_to_png_bytes", lambda *a, **k: _TINY_PNG_BYTES
    )
    output_path = tmp_path / "report.pdf"

    from src.reports.pdf_exporter import PdfReportExporter

    result = PdfReportExporter.export(report_content, output_path)

    assert result == output_path
    assert output_path.exists()
    assert output_path.read_bytes()[:5] == b"%PDF-"


def test_export_succeeds_when_rasterization_fails(
    tmp_path: Path, report_content: ReportContent, monkeypatch
) -> None:
    # A section whose figure can't rasterize (returns None) should not
    # abort the whole export — see rasterize.figure_to_png_bytes's own
    # docstring for why this is a swallow-and-continue, not a raise.
    monkeypatch.setattr(
        "src.reports.pdf_exporter.figure_to_png_bytes", lambda *a, **k: None
    )
    output_path = tmp_path / "report.pdf"

    from src.reports.pdf_exporter import PdfReportExporter

    result = PdfReportExporter.export(report_content, output_path)

    assert result.exists()
