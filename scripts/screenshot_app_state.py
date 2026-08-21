# File: scripts/screenshot_app_state.py
"""Boots the real application offscreen and saves a PNG of its current state.

Non-shipping infrastructure, alongside ``main.py`` at the repo root rather
than inside ``src/`` -- it is a verification tool for a human or an agent
to run *after* a milestone lands, not something the application itself
imports or depends on (matching the precedent this project's other
milestone-verification tooling under ``scripts/`` sets: small, standalone,
CLI-invoked, never imported by ``src/``).

Why this exists: prior milestones were verified by informally launching
``python main.py`` and looking at it, or by trusting the test suite alone
-- neither leaves an artifact a reviewer (or another agent, in a later
session, with no memory of what the screen looked like) can actually look
at. This script boots the *real* :class:`~src.core.app.Application`
composition path -- the same :func:`~src.core.bootstrap.bootstrap`,
:class:`~src.ui.theme_manager.ThemeManager`, and
:class:`~src.ui.main_window.MainWindow` construction ``src.core.app.
Application.run`` uses -- rather than a hand-rolled stand-in, so a
screenshot from this script is evidence about the real application, not
about some simplified double of it. It never calls ``QApplication.exec()``
(which would block forever): once the window is constructed and any
requested scenario has settled, it grabs a single frame and exits.

Requires ``QT_QPA_PLATFORM=offscreen`` (set here, before any PySide6
import, for the same reason ``tests/ui/conftest.py`` sets it at import
time rather than inside a fixture -- Qt reads it when the platform plugin
loads, which happens on first import).

Usage::

    python scripts/screenshot_app_state.py --output out.png
    python scripts/screenshot_app_state.py --output out.png --new-project
    python scripts/screenshot_app_state.py --output out.png --open-dataset path/to/file.csv
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Must precede every PySide6 import in the process -- see this module's
# own docstring. setdefault(), not assignment, so an operator who has
# already exported a different QT_QPA_PLATFORM (e.g. to test a real
# platform plugin) is not silently overridden.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_SCRIPTS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPTS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    # Run as `python scripts/screenshot_app_state.py`, not `python -m`, so
    # the project root is not automatically on sys.path the way it is for
    # `python main.py` (invoked from the project root itself). Prepending
    # it here is what lets `from src...` imports below resolve regardless
    # of the caller's own working directory.
    sys.path.insert(0, str(_PROJECT_ROOT))

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from src.core.bootstrap import bootstrap
from src.core.logger import get_logger
from src.ui.main_window import MainWindow
from src.ui.theme_manager import ThemeManager

_logger = get_logger(__name__)


class ScreenshotError(RuntimeError):
    """Raised when this script cannot produce a screenshot.

    A dedicated exception rather than letting whatever underlying
    exception escape unchanged, so a caller (a human, or the coordinator
    agent that runs this after a milestone) gets one clear failure class
    to catch, with the real cause chained via ``raise ... from exc``
    rather than lost.
    """


def _pump_events(app: QApplication, seconds: float) -> None:
    """Process the Qt event loop for ``seconds`` of wall-clock time.

    Neither a single ``processEvents()`` call (async work -- a worker
    thread's ``on_result`` callback, a ``QWebEngineView`` page load --
    would not have run yet) nor ``app.exec()`` (blocks forever, this
    script needs to exit) is enough on its own; this is the same bounded
    polling loop ``tests/ui/widgets/test_chart_view.py``'s ``_pump_until``
    and ``tests/ui/qt_helpers.py``'s ``wait_for_signal`` already use for
    exactly this reason.
    """
    deadline = time.time() + seconds
    while time.time() < deadline:
        app.processEvents()
        time.sleep(0.02)


def _drive_open_dataset(
    main_window: MainWindow, dataset_path: Path, app: QApplication
) -> None:
    """Load ``dataset_path`` through the real ``DatasetController.open_dataset`` flow.

    ``open_dataset()`` starts with a real, blocking ``QFileDialog`` --
    unusable unattended offscreen. Stubbing ``QFileDialog.getOpenFileName``
    to return ``dataset_path`` (the same technique
    ``tests/ui/conftest.py``'s ``block_modals`` fixture uses for every UI
    test in this suite) is what lets the rest of the method run
    unmodified: reader resolution, the worker-thread read, and the
    ``load_dataset`` callback that actually populates the workspace and
    refreshes the Dataset Explorer -- this drives the real production
    code path end to end, not a hand-rolled shortcut that only looks like
    it.
    """
    if not dataset_path.exists():
        raise ScreenshotError(f"--open-dataset path does not exist: {dataset_path}")

    original_get_open_file_name = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(  # type: ignore[method-assign]
        lambda *_a, **_k: (str(dataset_path), "")
    )
    try:
        main_window._dataset_controller.open_dataset()
        # The read itself runs on a QThreadPool worker (see
        # DatasetController.open_dataset's own docstring) -- give it real
        # wall-clock time to finish and its on_result callback to run,
        # rather than grabbing a frame of the "Loading…" busy state.
        _pump_events(app, seconds=5.0)
    finally:
        QFileDialog.getOpenFileName = original_get_open_file_name  # type: ignore[method-assign]


def _drive_new_project(main_window: MainWindow) -> None:
    """Create a new project through the real ``ProjectController.new_project`` flow.

    Unlike ``open_dataset``/``open_project``, ``new_project`` never opens a
    dialog -- see that method's own docstring -- so no stubbing is needed.
    """
    main_window._project_controller.new_project()


def run(output_path: Path, open_dataset: Path | None, new_project: bool) -> None:
    """Boot the real application offscreen, drive the requested scenario, and save a PNG.

    Args:
        output_path: Where to write the resulting screenshot. Parent
            directories are created if missing.
        open_dataset: If given, loaded via the real
            :meth:`~src.ui.controllers.dataset_controller.DatasetController.open_dataset`
            flow (see :func:`_drive_open_dataset`) before the screenshot
            is taken.
        new_project: If ``True``, a new project is created via the real
            :meth:`~src.ui.controllers.project_controller.ProjectController.new_project`
            flow (see :func:`_drive_new_project`) before the screenshot is
            taken.

    Raises:
        ScreenshotError: If ``QT_QPA_PLATFORM`` is not ``offscreen`` (a
            misconfigured environment would otherwise try to open a real
            window, which fails loudly and unhelpfully in a headless CI
            or agent sandbox), if bootstrap itself fails, or if
            ``open_dataset`` names a path that does not exist.
    """
    if os.environ.get("QT_QPA_PLATFORM") != "offscreen":
        # Only reachable if a caller explicitly exported a conflicting
        # value before invoking this script -- setdefault() above cannot
        # produce this state on its own. Checked explicitly rather than
        # trusting setdefault() silently, since a real GPU/window-system
        # attempt on a headless CI runner or agent sandbox fails with an
        # opaque Qt platform-plugin error far less actionable than this
        # message.
        raise ScreenshotError(
            "QT_QPA_PLATFORM must be 'offscreen' to run this script headlessly "
            f"(currently {os.environ.get('QT_QPA_PLATFORM')!r})."
        )

    try:
        context = bootstrap()
    except Exception as exc:
        raise ScreenshotError(f"bootstrap() failed: {exc}") from exc

    # Mirrors src.core.app.Application.run()'s own construction sequence
    # exactly (QApplication singleton, the same OpenGL attributes, theme
    # application, MainWindow construction/attach_theme_manager/show) --
    # see that method's docstring for why AA_UseSoftwareOpenGL/
    # AA_ShareOpenGLContexts are set before QApplication is constructed.
    # QApplication.instance() reused rather than constructed fresh: a
    # second QApplication in one process is a Qt fatal error, and a
    # caller driving multiple scenarios via repeated imports (or a test)
    # may already have one running.
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication.instance() or QApplication(sys.argv[:1])

    theme_manager = ThemeManager(app)
    theme_manager.apply_theme(context.config.theme)

    main_window = MainWindow(context)
    main_window.attach_theme_manager(theme_manager)
    main_window.show()

    # Let the initial show()/layout/paint settle before driving a
    # scenario or grabbing a frame -- an offscreen QWidget still goes
    # through Qt's normal event-driven layout and paint pipeline, it just
    # never reaches a real display surface.
    _pump_events(app, seconds=0.5)

    if new_project:
        _drive_new_project(main_window)
        _pump_events(app, seconds=0.2)

    if open_dataset is not None:
        _drive_open_dataset(main_window, open_dataset, app)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    pixmap = main_window.grab()
    if not pixmap.save(str(output_path), "PNG"):
        raise ScreenshotError(f"QPixmap.save() reported failure for {output_path}")

    _logger.info("Saved application screenshot to %s", output_path)

    # No app.quit()/app.exec() needed -- this process is about to exit
    # regardless, and (per tests/ui/conftest.py's own module docstring,
    # point 2) explicitly quitting a QApplication that still has
    # pending-deletion widgets is the confirmed-crash path on Windows,
    # not a safety measure. Closing the window explicitly is enough to
    # run ordinary Qt/QWebEngine teardown (ChartView.closeEvent, if any
    # chart tab is open) before the interpreter exits.
    main_window.close()
    _pump_events(app, seconds=0.5)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Boot the real application offscreen and save a PNG of its current state -- "
            "for post-milestone visual verification. See docs/VISUAL_VERIFICATION.md."
        )
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Path to write the PNG screenshot to (parent directories are created).",
    )
    parser.add_argument(
        "--open-dataset",
        type=Path,
        default=None,
        help="Load this file through the real open-dataset flow before the screenshot.",
    )
    parser.add_argument(
        "--new-project",
        action="store_true",
        help="Create a new project through the real new-project flow before the screenshot.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    try:
        run(args.output, args.open_dataset, args.new_project)
    except ScreenshotError as exc:
        print(f"screenshot_app_state.py: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
