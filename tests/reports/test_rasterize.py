# File: tests/reports/test_rasterize.py
"""Tests for src.reports.rasterize.figure_to_png_bytes.

One real kaleido call to confirm the happy path genuinely rasterizes a
figure (kaleido's headless-Chrome startup makes each call take a few
seconds — see this module's own single test rather than exercising it
repeatedly from every exporter test, which instead monkeypatch this
function; see tests/reports/test_pdf_exporter.py and neighbors).
"""

from __future__ import annotations

import plotly.graph_objects as go

from src.reports.rasterize import figure_to_png_bytes


def test_figure_to_png_bytes_returns_real_png_bytes() -> None:
    figure = go.Figure(data=[go.Bar(x=["a", "b"], y=[1, 2])])

    result = figure_to_png_bytes(figure, width=200, height=150)

    assert result is not None
    assert result[:8] == b"\x89PNG\r\n\x1a\n"  # PNG file signature


def test_figure_to_png_bytes_returns_none_on_failure() -> None:
    class _BrokenFigure:
        def to_image(self, **kwargs):
            raise RuntimeError("kaleido not available")

    result = figure_to_png_bytes(_BrokenFigure())

    assert result is None
