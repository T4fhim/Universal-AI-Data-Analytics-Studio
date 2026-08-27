# File: src/ui/widgets/chart_view.py
"""Displays a Plotly figure inside the Qt application via QWebEngineView.

Milestone 16 rewrite. The milestone-1-through-15 implementation wrote a
fresh ~4.7 MB HTML file (the full Plotly bundle inlined via
``figure.to_html(include_plotlyjs=True)``) per rendered chart, via
``tempfile.NamedTemporaryFile(..., delete=False)``, and never deleted it --
opening ten charts in one session left ten dead files on disk (the plan's
R2 risk). This version instead:

1. Loads a single static ``chart_host.html`` (staged once for the whole
   process by :mod:`src.ui.web.web_assets` -- see that module for why a
   temp-dir *copy* rather than loading ``resources/web/`` directly) exactly
   once per :class:`ChartView`, via :meth:`setUrl`.
2. Pushes each figure's data/layout/config into the already-loaded page as
   JSON, through ``QWebEnginePage.runJavaScript()`` calling the
   ``renderFigure``/``relayout`` functions ``resources/web/chart_bridge.js``
   defines. Re-renders use ``Plotly.react`` (diffs against the existing
   plot) rather than reloading the page, and a theme toggle uses
   ``Plotly.relayout`` (patches colours/fonts only) rather than
   re-rendering the data traces at all.

No new file is written per chart and no page ever reloads after the first
``chart_host.html`` load -- both a correctness fix (R2) and the mechanism
behind ":class:`ChartView` re-themes live, no flicker" (A1 in the plan).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from PySide6.QtGui import QCloseEvent
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QWidget

from src.core.logger import get_logger
from src.ui.theme.plotly_theme import plotly_config, plotly_layout
from src.ui.theme.tokens import DARK_TOKENS, ThemeTokens
from src.ui.web.chart_bridge import ChartBridge
from src.ui.web.web_assets import staged_chart_host_url

if TYPE_CHECKING:
    import plotly.graph_objects as go

_logger = get_logger(__name__)


def _merge_layout(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` onto ``base``, keyed dict by keyed dict.

    A plain ``{**base, **override}`` would silently destroy nested
    structure: ``plotly_layout(tokens)["title"]`` is only ``{"font":
    {...}}`` (no ``text``), so a shallow merge with a figure whose own
    layout sets ``title = {"text": "Revenue by Region"}`` would let
    whichever dict is spread *last* win the entire ``title`` key outright --
    either losing the figure's title text or losing the theme's font
    colour, instead of combining them. Recursing one level at a time keeps
    sibling keys (``text`` vs. ``font``) from each side.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(value, dict) and isinstance(existing, dict):
            merged[key] = _merge_layout(existing, value)
        else:
            merged[key] = value
    return merged


def _flatten_layout(d: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Flatten a nested layout dict into Plotly.js's dot-path attribute form.

    ``Plotly.newPlot``/``Plotly.react`` accept a full nested ``layout``
    object, but ``Plotly.relayout`` -- used for the theme-toggle recolour
    path specifically, so it patches in place instead of re-rendering data
    traces -- expects flat ``"xaxis.tickfont.color"``-style keys rather than
    nested objects. This is used only for the relayout push; the initial
    render sends the nested form.
    """
    flat: dict[str, Any] = {}
    for key, value in d.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_flatten_layout(value, path))
        else:
            flat[path] = value
    return flat


class ChartView(QWebEngineView):
    """A widget that displays one Plotly figure, themed and re-themeable.

    Args:
        parent: Optional owning widget.

    Attributes:
        bridge: The :class:`~src.ui.web.chart_bridge.ChartBridge` this
            view's page exposes over :class:`QWebChannel`. Public so a
            caller can connect to ``bridge.point_clicked`` /
            ``bridge.selection_changed`` -- unused until milestone 24, but
            already reachable so that milestone does not need to reach into
            this class's internals to get at it.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bridge = ChartBridge(self)
        self._channel = QWebChannel(self)
        self._channel.registerObject("chartBridge", self.bridge)
        self.page().setWebChannel(self._channel)

        self._tokens: ThemeTokens = DARK_TOKENS
        self._host_ready = False
        self._rendered = False
        # A figure requested via display_figure() before the host page has
        # finished loading is queued here and flushed in _on_load_finished
        # -- constructing a ChartView and immediately calling
        # display_figure() (the common call pattern -- see
        # dock_manager.py::display_chart) would otherwise race the
        # asynchronous page load.
        self._pending_render: tuple[str, str, str] | None = None

        self.loadFinished.connect(self._on_load_finished)
        self.setUrl(staged_chart_host_url())

    def display_figure(
        self, figure: go.Figure, tokens: ThemeTokens | None = None
    ) -> None:
        """Render ``figure``, themed with ``tokens`` (defaults to the last-applied theme).

        Args:
            figure: The Plotly figure to display.
            tokens: The design tokens to theme it with. Defaults to whatever
                :meth:`apply_theme` last set (or :data:`DARK_TOKENS` if
                :meth:`apply_theme` was never called) -- a caller that has
                no :class:`~src.ui.theme_manager.ThemeManager` reference at
                hand, e.g. a unit test, still gets a themed, not
                Plotly-default-white, chart.
        """
        if tokens is not None:
            self._tokens = tokens

        fig_dict = json.loads(figure.to_json())
        layout = _merge_layout(fig_dict.get("layout", {}), plotly_layout(self._tokens))
        data_json = json.dumps(fig_dict.get("data", []))
        layout_json = json.dumps(layout)
        config_json = json.dumps(plotly_config(self._tokens))

        if not self._host_ready:
            self._pending_render = (data_json, layout_json, config_json)
            return
        self._push_render(data_json, layout_json, config_json)

    def apply_theme(self, tokens: ThemeTokens) -> None:
        """Recolour the currently displayed chart in place, no page reload.

        Called from :class:`~src.ui.dock_manager.DockManager` on every
        :attr:`~src.ui.theme_manager.ThemeManager.theme_changed` emission,
        for every open :class:`ChartView`. If nothing has been rendered
        yet, this only remembers ``tokens`` for the eventual first
        :meth:`display_figure` call.
        """
        self._tokens = tokens
        if not self._rendered or not self._host_ready:
            return
        layout_json = json.dumps(_flatten_layout(plotly_layout(tokens)))
        self.page().runJavaScript(f"relayout({layout_json!r});")

    def _push_render(self, data_json: str, layout_json: str, config_json: str) -> None:
        js = f"renderFigure({data_json!r}, {layout_json!r}, {config_json!r});"
        self.page().runJavaScript(js)
        self._rendered = True

    def _on_load_finished(self, success: bool) -> None:
        if not success:
            _logger.error(
                "ChartView failed to load chart_host.html — chart will not display."
            )
            return
        _logger.debug("ChartView successfully loaded chart_host.html.")
        self._host_ready = True
        if self._pending_render is not None:
            data_json, layout_json, config_json = self._pending_render
            self._pending_render = None
            self._push_render(data_json, layout_json, config_json)

    def closeEvent(self, event: QCloseEvent) -> None:
        """Explicitly tear down the page before the widget itself is destroyed.

        Without this, ``QWebEngineView`` destruction ordering has produced
        a confirmed shutdown crash on Windows in this application when the
        underlying profile outlives its page (see the
        ``pyside6-development`` skill and the plan's R2 risk note).
        ``deleteLater()`` rather than an immediate delete, since Qt's
        event-driven page teardown must not be forced synchronously inside
        an event handler that Qt itself is still dispatching.
        """
        self.stop()
        self.page().deleteLater()
        super().closeEvent(event)
