# File: tests/ui/test_ui_state_bus.py
"""Tests for UiStateBus's coalesced, no-polling refresh mechanism.

This is the test the M17 acceptance criteria explicitly asks for: mutate
state, assert refresh fires via the bus's signal -- not a QTimer interval
tick. process_events() drives the QTimer.singleShot(0, ...) queued by
request_refresh() without a real event loop running.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QObject
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


def test_request_refresh_survives_the_bus_being_destroyed_before_it_fires(
    qapp: QApplication,
) -> None:
    """Regression test for a real, confirmed crash found during milestone 29.

    ``UiStateBus`` is a child of ``MainWindow`` (its ``parent`` argument);
    closing the window destroys the bus's C++ object. If a mutation calls
    ``request_refresh()`` and the window is closed before the queued
    ``QTimer.singleShot`` fires, the *old* implementation
    (``QTimer.singleShot(0, self._emit_state_changed)``, no context object)
    still invoked the bound method against a bus whose C++ object no
    longer existed, raising ``RuntimeError: Signal source has been
    deleted`` the next time anything called ``QApplication.
    processEvents()`` -- anywhere in the process, not just here, since the
    crash surfaces on whichever unrelated ``processEvents()`` call happens
    to run next. Reproduced directly with ``shiboken6.delete()`` (which
    destroys the C++ object the same way Qt destroying a parent window
    does) before applying the fix; this test fails the same way if the fix
    in ``request_refresh`` (passing ``self`` as the context argument) is
    ever reverted.

    Uses ``qapp.processEvents()`` directly rather than this file's own
    ``process_events()`` helper: that helper drives a nested
    ``QEventLoop.exec()``, and empirically (verified while writing this
    test) PySide6 only *prints* an exception raised inside a callback
    invoked through a nested event loop rather than propagating it back
    into the calling Python frame -- it would silently pass even against
    the unfixed code. A direct ``processEvents()`` call does propagate the
    exception, which is what makes this a real regression test rather
    than one that only looks like it exercises the bug.
    """
    parent = QObject()
    bus = UiStateBus(parent)
    bus.request_refresh()

    shiboken6.delete(parent)  # simulates the owning MainWindow closing
    assert not shiboken6.isValid(bus)

    qapp.processEvents()  # must not raise "Signal source has been deleted"
