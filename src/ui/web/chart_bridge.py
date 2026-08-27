# File: src/ui/web/chart_bridge.py
"""The Python half of the ``chart_host.html`` <-> Qt event channel.

Two directions, and only one needs this class:

- **Python -> JS** (pushing a new figure, or a theme's relayout patch) goes
  straight through ``QWebEnginePage.runJavaScript()`` from
  :class:`~src.ui.widgets.chart_view.ChartView` -- a one-way call needs no
  registered object on the other end.
- **JS -> Python** (a Plotly click or box/lasso selection) needs a
  :class:`QObject` :class:`QWebChannel` can expose to the page, which is
  what :class:`ChartBridge` is. ``resources/web/chart_bridge.js`` looks it
  up as ``channel.objects.chartBridge`` and calls its ``@Slot`` methods.

:attr:`ChartBridge.point_clicked` and :attr:`ChartBridge.selection_changed`
have no consumer yet -- milestone 24 uses them to filter a paired
``DataTableView`` from a chart click/selection. Defining the channel
contract now, even though nothing reads it yet, means
``resources/web/chart_bridge.js`` and ``chart_host.html`` do not need to
change again when M24 lands, matching how milestone 15 built
:mod:`src.ui.theme.plotly_theme` unused until this very milestone wired it
into chart rendering.
"""

from __future__ import annotations

import json

from PySide6.QtCore import QObject, Signal, Slot

from src.core.logger import get_logger

_logger = get_logger(__name__)


class ChartBridge(QObject):
    """Registered as ``"chartBridge"`` on a chart view's :class:`QWebChannel`.

    Args:
        parent: Optional owning :class:`QObject` -- typically the
            :class:`~src.ui.widgets.chart_view.ChartView` that constructs
            it, so the bridge's lifetime matches the view's.

    Signals:
        point_clicked: Emitted with a ``dict`` (``curveNumber``,
            ``pointIndex``, ``x``, ``y``) when a single Plotly marker is
            clicked.
        selection_changed: Emitted with a ``list[int]`` of point indices
            when a box/lasso selection completes.
    """

    point_clicked = Signal(dict)
    selection_changed = Signal(list)

    @Slot(str)
    def notify_point_clicked(self, payload_json: str) -> None:
        """Invoked from JS (``forwardClick`` in ``chart_bridge.js``).

        Args:
            payload_json: A JSON object string, e.g.
                ``'{"curveNumber": 0, "pointIndex": 3, "x": 1.5, "y": 22.0}'``.
                Malformed input is logged and dropped rather than raised --
                this method executes inside a Qt slot invoked from the
                WebEngine render process, where an uncaught exception has no
                well-defined place to surface to the user.
        """
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            _logger.warning(
                "ChartBridge received a malformed point-click payload: %r",
                payload_json,
            )
            return
        if not isinstance(payload, dict):
            _logger.warning(
                "ChartBridge point-click payload was not a JSON object: %r",
                payload,
            )
            return
        self.point_clicked.emit(payload)

    @Slot(str)
    def notify_selection_changed(self, payload_json: str) -> None:
        """Invoked from JS (``forwardSelection`` in ``chart_bridge.js``).

        Args:
            payload_json: A JSON array-of-integers string, e.g. ``"[3, 4, 5]"``.
        """
        try:
            payload = json.loads(payload_json)
        except (TypeError, ValueError):
            _logger.warning(
                "ChartBridge received a malformed selection payload: %r",
                payload_json,
            )
            return
        if not isinstance(payload, list):
            _logger.warning(
                "ChartBridge selection payload was not a JSON array: %r",
                payload,
            )
            return
        self.selection_changed.emit(payload)
