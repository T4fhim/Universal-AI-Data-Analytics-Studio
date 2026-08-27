# File: tests/ui/qt_helpers.py
"""Small Qt test utilities, in place of a ``pytest-qt`` dependency.

``pytest-qt`` is not installed, and adding it would buy little: its main
value is ``qtbot.waitSignal``, which :func:`wait_for_signal` covers in a
dozen lines, and its widget interactions are built on ``QTest`` synthetic
input, which is unreliable under the offscreen platform where there is no
real window system to deliver events to.

The convention in this suite is therefore to drive widgets through their own
API (``button.click()``, ``combo.setCurrentIndex(...)``) and to call handler
methods directly.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from PySide6.QtCore import QEventLoop, Qt, QTimer, SignalInstance
from PySide6.QtWidgets import QAbstractButton, QApplication, QWidget

_DIRECT_CHILDREN = Qt.FindChildOption.FindDirectChildrenOnly


def process_events(milliseconds: int = 50) -> None:
    """Let queued signals, timers, and ``deleteLater`` calls run.

    Needed after anything that defers work with ``QTimer.singleShot(0, ...)``
    or ``deleteLater()``. Neither has happened yet when the calling line
    returns, and both are common in this codebase.
    """
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def wait_for_signal(signal: SignalInstance, timeout_ms: int = 15000) -> tuple[Any, ...]:
    """Block until ``signal`` fires and return the arguments it carried.

    Raises:
        TimeoutError: If the signal does not fire in time. Raised rather than
            returning a sentinel, so a test that has silently stopped
            exercising its subject fails loudly instead of passing vacuously.

    Default raised twice, 2000ms -> 5000ms -> 15000ms, both times for the
    same real CI-only flake (never seen locally): test_worker_runner.py's
    real-QThreadPool tests timed out waiting for ``finished``, but the
    [diag] logging BaseWorker/WorkerRunner still carry (see their own
    docstrings) proved the worker actually emitted ``finished``
    successfully both times -- 5000ms was not a large enough margin either,
    confirmed by the exact same failure recurring, with a second test
    (test_a_raising_on_result_is_never_silently_lost) newly affected too.
    This points at real event-loop backpressure this deep into a single
    long-lived-QApplication process running 1470+ tests (many of them
    posting their own queued signals/timers into the same main-thread event
    loop across the whole session) on CI's more resource-constrained
    hardware than this project's local dev machine, not a defect in any
    one test. No test using this helper asserts on delivery speed -- only
    "eventually, or fail loudly" per the Raises note above -- so widening
    the margin again fixes the flake without weakening any test's actual
    claim. If this recurs even at 15000ms, the right fix is no longer a
    bigger number: it's isolating these tests' event-loop state from the
    rest of the session (per-test QApplication processEvents() flush, or
    running test_worker_runner.py in its own pytest invocation) --
    documented here for whoever hits that next.
    """
    received: list[tuple[Any, ...]] = []
    loop = QEventLoop()

    def _on_signal(*args: Any) -> None:
        received.append(args)
        loop.quit()

    signal.connect(_on_signal)
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    timer.start(timeout_ms)
    try:
        loop.exec()
    finally:
        signal.disconnect(_on_signal)

    if not received:
        raise TimeoutError(f"Signal did not fire within {timeout_ms} ms.")
    return received[0]


def click(button: QAbstractButton) -> None:
    """Activate ``button`` and let the resulting slots run."""
    button.click()
    process_events()


def widget_tree(root: QWidget) -> Iterator[tuple[str, QWidget]]:
    """Yield ``(path, widget)`` for ``root`` and every descendant.

    ``path`` is a slash-separated trail of class and object names, such as
    ``MainWindow/Workbench/QPushButton#runButton``, so a failing
    accessibility assertion can name a specific widget instead of printing a
    memory address. Milestone 26's ``src.ui.a11y.audit`` reuses this exact
    traversal, which is why it is a shared helper rather than being
    reimplemented per test.
    """

    def _label(widget: QWidget) -> str:
        name = widget.objectName()
        return f"{type(widget).__name__}#{name}" if name else type(widget).__name__

    def _walk(widget: QWidget, prefix: str) -> Iterator[tuple[str, QWidget]]:
        path = f"{prefix}/{_label(widget)}" if prefix else _label(widget)
        yield path, widget
        for child in widget.findChildren(QWidget, options=_DIRECT_CHILDREN):
            yield from _walk(child, path)

    yield from _walk(root, "")


def top_level_widgets() -> list[QWidget]:
    """Return every currently-open top-level widget.

    Lets a test assert no dialog was left open. A leaked modal is invisible
    offscreen but will hang a later test, so catching it at the source beats
    debugging the hang.
    """
    return list(QApplication.topLevelWidgets())
