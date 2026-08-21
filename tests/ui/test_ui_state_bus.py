# File: tests/ui/test_ui_state_bus.py
"""Tests for UiStateBus's coalesced, no-polling refresh mechanism.

This is the test the M17 acceptance criteria explicitly asks for: mutate
state, assert refresh fires via the bus's signal -- not a QTimer interval
tick. process_events() drives the QTimer.singleShot(0, ...) queued by
request_refresh() without a real event loop running.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication

from src.ui.ui_state_bus import UiStateBus
from tests.ui.qt_helpers import process_events


def test_request_refresh_emits_state_changed(qapp: QApplication) -> None:
    bus = UiStateBus()
    received = []
    bus.state_changed.connect(lambda: received.append(1))

    bus.request_refresh()
    assert received == []  # not synchronous -- queued for the next event-loop turn

    process_events()
    assert received == [1]


def test_a_burst_of_requests_coalesces_into_one_emission(qapp: QApplication) -> None:
    """Ten mutations in a row (e.g. reloading a project's ten recorded
    datasets) must produce one recompute, not ten -- the entire reason
    this class exists instead of connecting every mutation point directly
    to refresh_enablement.
    """
    bus = UiStateBus()
    received = []
    bus.state_changed.connect(lambda: received.append(1))

    for _ in range(10):
        bus.request_refresh()

    process_events()
    assert received == [1]  # exactly one emission, not ten


def test_a_second_burst_after_the_first_fires_again(qapp: QApplication) -> None:
    bus = UiStateBus()
    received = []
    bus.state_changed.connect(lambda: received.append(1))

    bus.request_refresh()
    process_events()
    bus.request_refresh()
    process_events()

    assert received == [1, 1]
