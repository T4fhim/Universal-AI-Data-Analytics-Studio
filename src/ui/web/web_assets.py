# File: src/ui/web/web_assets.py
"""Stages the static chart-hosting web assets into one process-lifetime dir.

:mod:`~src.ui.widgets.chart_view` used to write a fresh ~4.7 MB HTML file
(the full Plotly bundle inlined) per rendered chart via
``tempfile.NamedTemporaryFile(..., delete=False)`` and never deleted it --
opening ten charts in one session left ten dead files on disk. This module
is the fix's staging layer: ``resources/web/{chart_host.html,chart_bridge.js,
plotly.min.js}`` are copied *once* into a single :class:`QTemporaryDir` that
lives for the process's lifetime, and every :class:`~src.ui.widgets.
chart_view.ChartView` -- however many are opened -- points its
:class:`QUrl` at that same copy. Disk usage is flat regardless of how many
charts get opened, which is exactly the milestone-16 acceptance criterion
this module exists to satisfy.

**Why a temp-dir copy instead of loading ``resources/web/`` directly.** Two
reasons, not one:

1. A frozen/installed build may package ``resources/`` inside a read-only
   bundle (PyInstaller's ``_MEIPASS`` extraction dir, an installer's
   Program Files tree). ``QWebEngineView`` only needs read access to render
   from ``file://``, so this would still work either way -- but staging to a
   guaranteed-writable location removes that as a variable entirely rather
   than depending on an assumption about the deployment environment that
   nothing here can verify at import time.
2. It matches the plan's explicit R2 mitigation (``plans/ui-overhaul-
   pioneering-adaptive-workbench.md``): "one process-lifetime QTemporaryDir
   (module-level singleton with atexit cleanup -- it must outlive every
   ChartView)".

The copy is idempotent and lazy: nothing is written to disk until the first
:class:`~src.ui.widgets.chart_view.ChartView` is constructed, not at import
time -- this module must be importable without ever touching disk, matching
the Qt-free-until-used pattern the rest of ``src/ui/theme`` follows.
"""

from __future__ import annotations

import atexit
import shutil
from pathlib import Path

from PySide6.QtCore import QTemporaryDir, QUrl

from src.core.constants import PROJECT_ROOT
from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

# The checked-in source assets this module stages -- see resources/web/NOTICE.md
# for plotly.min.js's provenance and update procedure.
_SOURCE_WEB_ROOT = PROJECT_ROOT / "resources" / "web"
_ASSET_FILENAMES = ("chart_host.html", "chart_bridge.js", "plotly.min.js")

_HOST_FILENAME = "chart_host.html"

# Module-level singleton: constructed lazily by _ensure_staged_dir(), never
# reconstructed. A plain global (not a class) matches how theme_manager.py's
# _COMPILED_CACHE and icon_provider.py's icon cache are both already
# module-level dicts rather than a wrapper class -- there is exactly one of
# these per process and a class would only add an import-time-constructible
# singleton pattern this codebase does not otherwise use.
_temp_dir: QTemporaryDir | None = None
_staged_path: Path | None = None


def _ensure_staged_dir() -> Path:
    """Return the staged asset directory, creating and populating it once.

    Raises:
        ServiceError: If the temp directory cannot be created, or a source
            asset (``resources/web/*``) is missing -- both indicate a broken
            install rather than a recoverable runtime condition, so this
            fails loudly rather than silently falling back to per-chart
            temp files (which would silently reintroduce the exact leak
            this module exists to fix).
    """
    global _temp_dir, _staged_path
    if _staged_path is not None:
        return _staged_path

    temp_dir = QTemporaryDir()
    if not temp_dir.isValid():
        raise ServiceError(
            f"Could not create a temporary directory to stage chart web "
            f"assets: {temp_dir.errorString()}"
        )
    staged_path = Path(temp_dir.path())

    for filename in _ASSET_FILENAMES:
        source = _SOURCE_WEB_ROOT / filename
        if not source.is_file():
            raise ServiceError(
                f"Missing chart web asset '{filename}' at {source}. "
                f"Reinstall or restore resources/web/ from version control."
            )
        shutil.copyfile(source, staged_path / filename)

    # Held at module scope so the QTemporaryDir is not garbage-collected
    # (and its files removed) while ChartViews are still using it -- and
    # atexit.register() is a deliberate second line of defence per the
    # plan's own wording ("module-level singleton with atexit cleanup"),
    # since relying solely on interpreter-shutdown object finalization order
    # for a C++-backed Qt object is not guaranteed to run before exit.
    _temp_dir = temp_dir
    _staged_path = staged_path
    atexit.register(_temp_dir.remove)
    _logger.info("Staged chart web assets to %s", staged_path)
    return staged_path


def staged_chart_host_url() -> QUrl:
    """Return the ``file://`` URL of the staged ``chart_host.html``.

    Every :class:`~src.ui.widgets.chart_view.ChartView` calls this and
    ``setUrl()``s to the *same* URL -- staging happens once regardless of
    how many chart views request it.
    """
    return QUrl.fromLocalFile(str(_ensure_staged_dir() / _HOST_FILENAME))


def reset_staged_assets_for_tests() -> None:
    """Force the next :func:`staged_chart_host_url` call to re-stage.

    Test-only. Without this, the module-level singleton persists across
    tests in the same process (by design -- see the module docstring), which
    would hide a test that only passes because an *earlier* test happened to
    stage the directory first.
    """
    global _temp_dir, _staged_path
    if _temp_dir is not None:
        _temp_dir.remove()
    _temp_dir = None
    _staged_path = None
