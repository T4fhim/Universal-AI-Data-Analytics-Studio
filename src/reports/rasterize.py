# File: src/reports/rasterize.py
"""Shared Plotly-figure-to-PNG-bytes helper for every non-HTML report exporter.

:class:`~src.reports.pdf_exporter.PdfReportExporter`,
:class:`~src.reports.word_exporter.WordReportExporter`, and
:class:`~src.reports.excel_exporter.ExcelReportExporter` have no notion
of an interactive widget the way :class:`~src.reports.html_exporter.
HtmlReportExporter` does (see that module) — each must flatten a
figure to a static image before it can appear in the document. Kaleido
(already a project dependency — the same backend
``plotly.graph_objects.Figure.to_image`` uses anywhere else in this
codebase a static export is needed) does the actual rendering; this
one helper is shared rather than duplicated across the three exporters
that need it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.core.logger import get_logger

if TYPE_CHECKING:
    import plotly.graph_objects as go

_logger = get_logger(__name__)


def figure_to_png_bytes(
    figure: go.Figure, width: int = 900, height: int = 500
) -> bytes | None:
    """Rasterize ``figure`` to PNG bytes, or ``None`` if rendering fails.

    Failures are logged and swallowed rather than raised: kaleido's
    headless-Chrome rendering path can fail for reasons specific to one
    figure or one machine (a missing system dependency, a malformed
    trace) that should not abort an entire multi-section report over
    one chart that won't rasterize — the exporter that calls this
    simply omits that section's image and keeps its text.
    """
    try:
        return figure.to_image(format="png", width=width, height=height)
    except Exception as exc:  # noqa: BLE001 — deliberately broad: kaleido can
        # raise several different exception types depending on platform and
        # failure mode (missing Chrome, a bad trace spec, a timeout), none of
        # which is safe to name exhaustively here, and every one of them
        # should be treated identically (skip this image, keep going).
        _logger.warning("Could not rasterize a figure for the report: %s", exc)
        return None
