# File: src/ui/widgets/chart_view.py
"""Displays a Plotly figure inside the Qt application via QWebEngineView.

Renders by writing the figure's HTML to a temporary file and loading
it via setUrl() rather than setHtml(). Found necessary by testing: a
fully inlined Plotly bundle (include_plotlyjs=True) can produce an
HTML string large enough that QWebEngineView.setHtml() silently fails
to load it correctly. Loading from a file via setUrl() does not have
the same practical size constraint.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from src.core.logger import get_logger

if TYPE_CHECKING:
    import plotly.graph_objects as go

_logger = get_logger(__name__)


class ChartView(QWebEngineView):
    """A widget that displays one Plotly figure."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._temp_html_path: Path | None = None
        self.loadFinished.connect(self._on_load_finished)

    def display_figure(self, figure: "go.Figure") -> None:
        """Render ``figure`` into this view via a temporary HTML file."""
        html = figure.to_html(full_html=True, include_plotlyjs=True)

        if self._temp_html_path is None:
            temp_file = tempfile.NamedTemporaryFile(
                mode="w", suffix=".html", delete=False, encoding="utf-8"
            )
            self._temp_html_path = Path(temp_file.name)
        else:
            temp_file = open(self._temp_html_path, "w", encoding="utf-8")

        temp_file.write(html)
        temp_file.close()

        url = QUrl.fromLocalFile(str(self._temp_html_path.resolve()))
        _logger.info("Loading chart URL: %s", url.toString())
        self.setUrl(url)

    def _on_load_finished(self, success: bool) -> None:
        if not success:
            _logger.error("ChartView failed to load rendered HTML — chart will not display.")
        else:
            _logger.debug("ChartView successfully loaded chart HTML.")