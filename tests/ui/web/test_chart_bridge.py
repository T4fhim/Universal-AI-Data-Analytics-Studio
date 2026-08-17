# File: tests/ui/web/test_chart_bridge.py
"""Tests for ChartBridge's JS -> Python payload handling.

Constructs the QObject directly and calls its @Slot methods as plain
methods -- this exercises exactly what QWebChannel would dispatch to,
without needing an actual WebChannel/WebEngineView round trip.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui.web.chart_bridge import ChartBridge


def test_notify_point_clicked_emits_parsed_payload(qapp: QApplication) -> None:
    bridge = ChartBridge()
    received: list[dict] = []
    bridge.point_clicked.connect(received.append)

    bridge.notify_point_clicked(
        '{"curveNumber": 0, "pointIndex": 3, "x": 1.5, "y": 22.0}'
    )

    assert received == [{"curveNumber": 0, "pointIndex": 3, "x": 1.5, "y": 22.0}]


def test_notify_point_clicked_drops_malformed_json_without_raising(
    qapp: QApplication,
) -> None:
    bridge = ChartBridge()
    received: list[dict] = []
    bridge.point_clicked.connect(received.append)

    bridge.notify_point_clicked("not json")

    assert received == []


def test_notify_point_clicked_drops_non_object_payload(qapp: QApplication) -> None:
    bridge = ChartBridge()
    received: list[dict] = []
    bridge.point_clicked.connect(received.append)

    bridge.notify_point_clicked("[1, 2, 3]")

    assert received == []


def test_notify_selection_changed_emits_parsed_indices(qapp: QApplication) -> None:
    bridge = ChartBridge()
    received: list[list] = []
    bridge.selection_changed.connect(received.append)

    bridge.notify_selection_changed("[3, 4, 5]")

    assert received == [[3, 4, 5]]


def test_notify_selection_changed_drops_malformed_json_without_raising(
    qapp: QApplication,
) -> None:
    bridge = ChartBridge()
    received: list[list] = []
    bridge.selection_changed.connect(received.append)

    bridge.notify_selection_changed("{not json")

    assert received == []


def test_notify_selection_changed_drops_non_array_payload(qapp: QApplication) -> None:
    bridge = ChartBridge()
    received: list[list] = []
    bridge.selection_changed.connect(received.append)

    bridge.notify_selection_changed('{"not": "an array"}')

    assert received == []
