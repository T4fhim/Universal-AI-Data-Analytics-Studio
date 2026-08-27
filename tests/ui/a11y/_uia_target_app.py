# File: tests/ui/a11y/_uia_target_app.py
"""Out-of-process launch target for ``test_uia_integration.py``.

This module is a runnable script, not a pytest test file (no ``test_``
prefix, so pytest's default collection never picks it up even though it
lives inside a `tests/` package). It exists because the real UIA
verification this milestone's Tier 1 task requires -- confirming Qt
actually exposes accessible information to the *real* Windows UI
Automation layer, not just in-process ``QAccessible`` -- needs a genuinely
visible, OS-level top-level window, and that is fundamentally incompatible
with running inside the same pytest process as the rest of the UI suite:

- ``tests/ui/conftest.py`` sets ``QT_QPA_PLATFORM=offscreen`` at import
  time, unconditionally, before any test module in ``tests/ui/`` (including
  a UIA test) gets a chance to run a single line of its own code -- conftest
  files are imported during collection, ahead of every test in their
  subtree, docstring point 1 there explains why this ordering cannot be
  worked around from within a test module.
- Even if that were not true, ``QApplication`` is a process-wide singleton
  and ``tests/ui/conftest.py``'s ``qapp`` fixture is session-scoped and
  never torn down (docstring point 2) -- once any earlier test in the same
  process has constructed an offscreen ``QApplication``, no later test in
  that same process can get a windowed one instead.

So this script runs the real application surface (a fully bootstrapped
:class:`~src.ui.main_window.MainWindow`, themed, with a dataset loaded --
the same "fully populated" fixture shape
``tests/ui/a11y/test_audit.py::themed_main_window`` uses) in its own,
separate OS process, with ``QT_QPA_PLATFORM`` never set to ``offscreen``,
so the window it creates is a real, visible, OS-level top-level window with
genuine UI Automation elements. ``test_uia_integration.py`` launches this
as a subprocess and drives it entirely from the outside via ``pywinauto``,
the same way a screen reader or any other out-of-process assistive
technology actually observes a running application -- never importing
anything from this module directly, so nothing here needs to satisfy the
in-process test conventions the rest of ``tests/ui/`` follows.

Communication with the parent test process is deliberately simple: a
single-line stdout protocol (``READY``, ``MAIN_NAMES <json>``, dialog
open/close markers) for the parent to synchronize on, and single-word
commands read from stdin (a background thread feeds a thread-safe queue;
a ``QTimer`` polls it on the Qt GUI thread, since only the GUI thread may
touch Qt widgets) to tell this process what to do next. A full RPC
framework would be substantial overkill for the handful of steps this
Tier 1 test actually needs to drive.
"""

from __future__ import annotations

import os

# Must be set before PySide6 is imported anywhere in *this* process -- see
# this module's own docstring and tests/ui/conftest.py's identical point 1
# for why. This script is its own process specifically so this line is safe
# to run unconditionally: no other test's offscreen QApplication has ever
# been constructed here.
os.environ["QT_QPA_PLATFORM"] = "windows"

import argparse
import json
import queue
import sys
import threading
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QAbstractButton,
    QAbstractSlider,
    QAbstractSpinBox,
    QComboBox,
    QLineEdit,
    QWidget,
)

from src.core.bootstrap import bootstrap
from src.services.workspace_service import Dataset
from src.ui.main_window import MainWindow
from src.ui.theme_manager import ThemeManager

# Mirrors src.ui.a11y.rules._BUTTON_LIKE / _FIELD_LIKE exactly (see that
# module's own _path() docstring for why this project accepts this kind of
# small, explained duplication rather than restructuring two modules around
# a shared third one for a few lines of logic): this script needs the same
# "does this widget count as needing a name" criterion the audit rules
# apply, so the set of names asserted against the real UIA tree in
# test_uia_integration.py is provably the same set audit.py's own rules
# already require -- not a second, silently-drifting definition of
# "interactive control".
_BUTTON_LIKE = (QAbstractButton,)
_FIELD_LIKE = (QLineEdit, QComboBox, QAbstractSpinBox, QAbstractSlider)


def _expected_names(
    root: QWidget, *, require_visible: bool = True
) -> list[dict[str, str]]:
    """Every interactive widget's Qt-side accessible name.

    Two cases, matching ``src.ui.a11y.rules``' own name criteria:

    - An explicit ``accessibleName()`` -- exact string Qt's accessibility
      bridge exposes as the UIA ``Name`` property verbatim.
    - A button-like widget with no explicit accessible name but visible
      ``text()`` -- Qt's built-in accessibility interface falls back to the
      widget's text automatically (this is *why*
      ``rules._check_button_names`` accepts ``text()`` as satisfying the
      rule without a separate ``describe()`` call). Mnemonic ``&`` markers
      are stripped before comparison since Qt's accessibility bridge strips
      them too.

    Buddy-label-derived field names (the third case ``rules.py`` accepts)
    are deliberately excluded from this exact-match list -- Qt normalizes a
    buddy label's text before exposing it as a field's accessible name
    (stripping both the mnemonic marker and a trailing ``:``), and
    reproducing that normalization here risks a second, silently-drifting
    definition of what Qt actually does. The broader "every interactive
    control has *some* non-empty UIA name" assertion in
    ``test_uia_integration.py`` still covers that case; only the precise
    "matches this exact string" claim is narrowed to the two cases above.

    Args:
        root: Widget to walk (inclusive).
        require_visible: Skip a widget whose ``isVisible()`` is ``False``.
            The default matches "what real UIA should show right now" for an
            already-shown window. ``False`` is for a dialog like
            :class:`~src.ui.command_palette.CommandPalette` that is
            constructed once at startup (so its accessible names are already
            set) but not shown yet at the moment this is called -- the
            caller computes its expected names immediately before making it
            visible, so ``isVisible()`` would otherwise incorrectly filter
            out every one of its widgets.
    """
    names: list[dict[str, str]] = []
    seen: set[str] = set()
    all_widgets = [root, *root.findChildren(QWidget)]
    for widget in all_widgets:
        if require_visible and not widget.isVisible():
            continue
        explicit = widget.accessibleName().strip()
        if explicit:
            key = f"{type(widget).__name__}:{explicit}"
            if key not in seen:
                seen.add(key)
                names.append({"name": explicit, "class": type(widget).__name__})
            continue
        if isinstance(widget, _BUTTON_LIKE):
            visible_text = widget.text().strip().replace("&", "")
            if visible_text:
                key = f"{type(widget).__name__}:{visible_text}"
                if key not in seen:
                    seen.add(key)
                    names.append({"name": visible_text, "class": type(widget).__name__})
    return names


def _read_stdin_commands(command_queue: queue.Queue[str]) -> None:
    for line in sys.stdin:
        command = line.strip()
        if command:
            command_queue.put(command)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config-path", required=True)
    parser.add_argument("--log-dir", required=True)
    args = parser.parse_args()

    # Local import: QApplication must exist before other PySide6 widget
    # imports are meaningfully usable, but the offscreen-safety ordering
    # concern above only applies to *this* module's own top-level imports.
    from PySide6.QtWidgets import QApplication

    context = bootstrap(config_path=Path(args.config_path), log_dir=Path(args.log_dir))
    # QApplication.instance() is typed to return the base QCoreApplication
    # (a PySide6 stub quirk, not a runtime concern -- this process never
    # constructs any other QCoreApplication subclass), so ThemeManager's
    # QApplication-typed constructor needs an explicit narrowing rather than
    # the shorter `QApplication.instance() or QApplication([])` idiom
    # tests/ui/conftest.py's own qapp fixture uses (that fixture's return
    # type annotation does the narrowing there instead).
    existing_app = QApplication.instance()
    app = existing_app if isinstance(existing_app, QApplication) else QApplication([])
    window = MainWindow(context)
    theme_manager = ThemeManager(app)
    theme_manager.apply_theme("dark")
    window.attach_theme_manager(theme_manager)

    # Same fixture shape as tests/ui/a11y/test_audit.py::themed_main_window:
    # a dataset loaded so the workbench's stage pages actually exist, not
    # just the welcome page.
    dataset = Dataset(
        name="uia-fixture",
        dataframe=pd.DataFrame({"category": ["a", "b", "a"], "value": [1.0, 2.0, 3.0]}),
        source_format="csv",
    )
    window._dataset_controller.load_dataset(dataset)

    window.show()
    window.raise_()
    window.activateWindow()

    command_queue: queue.Queue[str] = queue.Queue()
    reader_thread = threading.Thread(
        target=_read_stdin_commands, args=(command_queue,), daemon=True
    )
    reader_thread.start()

    def poll_commands() -> None:
        try:
            command = command_queue.get_nowait()
        except queue.Empty:
            return
        if command == "main_names":
            print(f"MAIN_NAMES {json.dumps(_expected_names(window))}", flush=True)
        elif command == "open_about":
            print("ABOUT_OPENING", flush=True)
            window._theme_controller.open_about()  # blocks GUI thread until closed
            print("ABOUT_CLOSED", flush=True)
        elif command == "open_command_palette":
            expected = _expected_names(window._command_palette, require_visible=False)
            print(f"PALETTE_EXPECTED_NAMES {json.dumps(expected)}", flush=True)
            print("PALETTE_OPENING", flush=True)
            window._command_palette.exec()  # blocks GUI thread until closed
            print("PALETTE_CLOSED", flush=True)
        elif command == "quit":
            app.quit()

    poll_timer = QTimer()
    poll_timer.timeout.connect(poll_commands)
    poll_timer.start(50)

    print(f"READY pid={os.getpid()}", flush=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
