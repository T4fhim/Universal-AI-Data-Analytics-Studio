# File: tests/ui/conftest.py
"""Qt fixtures for the UI test tier, which did not exist before milestone 15.

``tests/`` had no ``ui/`` directory through milestone 14 -- all 265 tests were
non-Qt, and no test imported ``src.ui``. The offscreen smoke checks that
verified earlier UI milestones were throwaway scripts in a scratch directory,
so nothing about the UI was covered by the committed suite. This module is
the harness that replaces them.

Three things here are load-bearing:

1. ``QT_QPA_PLATFORM`` is set **before PySide6 is imported anywhere**. Qt
   reads it when the platform plugin loads, which happens on first import,
   not on ``QApplication`` construction -- setting it inside a fixture is too
   late and Qt tries to open a real window.
2. The ``QApplication`` is session-scoped and never torn down. Calling
   ``quit()`` between tests crashes on Windows, because Qt destroys the
   platform integration while widgets from the previous test are still
   pending deletion.
3. ``block_modals`` is autouse. ``QMessageBox.information`` and friends open a
   real modal dialog with a nested event loop; offscreen there is nobody to
   dismiss it, so an unguarded test hangs forever instead of failing.

``block_modals`` records what it intercepted rather than silently swallowing
it. Asserting on the recorded calls is how a test proves the user was
actually told something -- which matters because the audit behind this
overhaul found the skipped-dataset warning from
``ProjectService.record_datasets`` being discarded with no user-visible
trace.
"""

from __future__ import annotations

import os

# Must precede every PySide6 import in the process. See point 1 above.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from collections.abc import Iterator  # noqa: E402
from typing import Any, NamedTuple  # noqa: E402

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402


class ModalCall(NamedTuple):
    """One intercepted modal dialog.

    Attributes:
        kind: Which static was called: information, warning, critical, or
            question.
        title: The dialog window title.
        text: The message body shown to the user.
    """

    kind: str
    title: str
    text: str


@pytest.fixture(scope="session")
def qapp() -> Iterator[QApplication]:
    """The one ``QApplication`` for the whole test session.

    Sets the same OpenGL attributes :meth:`src.core.app.Application.run` does.
    They matter less offscreen, but keeping them identical means the suite
    exercises the configuration that actually ships.
    """
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    application = QApplication.instance() or QApplication([])
    yield application  # never quit() -- see point 2 in the module docstring


@pytest.fixture(autouse=True)
def block_modals(monkeypatch: pytest.MonkeyPatch) -> list[ModalCall]:
    """Intercept every blocking dialog, recording it instead of showing it.

    Returns:
        A live list of :class:`ModalCall` entries, appended to as the test
        runs, so a test can assert the user was informed rather than only
        that nothing hung.
    """
    recorded: list[ModalCall] = []

    def _make(kind: str, default: Any) -> Any:
        def _intercept(_parent: Any, title: str, text: str, *_a: Any, **_k: Any) -> Any:
            recorded.append(ModalCall(kind, title, text))
            return default

        return staticmethod(_intercept)

    for kind, result in (
        ("information", QMessageBox.StandardButton.Ok),
        ("warning", QMessageBox.StandardButton.Ok),
        ("critical", QMessageBox.StandardButton.Ok),
        ("question", QMessageBox.StandardButton.Yes),
    ):
        monkeypatch.setattr(QMessageBox, kind, _make(kind, result))

    # File dialogs block identically. Returning empty means "user cancelled",
    # which every call site in src/ui already handles, so an un-stubbed file
    # dialog in a new test fails cleanly rather than hanging.
    monkeypatch.setattr(
        QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", ""))
    )
    monkeypatch.setattr(
        QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: "")
    )
    return recorded
