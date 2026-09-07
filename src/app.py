# File: src/app.py
"""Application entry class.

:class:`Application` wraps a :class:`~uadas_core.core.bootstrap.BootstrapContext`
and exposes a single :meth:`run` method as the application's actual
behavior after startup. As of milestone 1b-ii, ``run`` constructs the
``QApplication``, applies the configured theme via
:class:`~src.ui.theme_manager.ThemeManager`, builds and shows
:class:`~src.ui.main_window.MainWindow`, and enters the Qt event loop —
this replaced the milestone-1a placeholder body (which only logged
that startup succeeded) exactly as that placeholder's own docstring
said it would, rather than restructuring this class or changing how
``main.py`` calls it.
"""

from __future__ import annotations

import sys
from typing import cast

from PySide6.QtWidgets import QApplication

from src.ui.autosave_timer import AutosaveTimer
from src.ui.dialogs.first_run_tour_dialog import FirstRunTourDialog
from src.ui.main_window import MainWindow
from src.ui.theme_manager import ThemeManager
from uadas_core.core.bootstrap import BootstrapContext, bootstrap
from uadas_core.core.constants import APP_NAME, APP_VERSION
from uadas_core.core.logger import get_logger
from uadas_core.services.project_service import ProjectService
from uadas_core.services.settings_service import SettingsService
from uadas_core.services.workspace_service import WorkspaceService

_logger = get_logger(__name__)


class Application:
    """Top-level application object, constructed from a bootstrap context.

    Args:
        context: The result of a successful
            :func:`~uadas_core.core.bootstrap.bootstrap` call. ``Application``
            does not call ``bootstrap`` itself — see
            :meth:`create`, which is the convenience path most callers
            (including ``main.py``) should use instead of constructing
            this class directly from a context they assembled by hand.
    """

    def __init__(self, context: BootstrapContext) -> None:
        self._context = context

    @classmethod
    def create(cls) -> Application:
        """Run bootstrap and construct an :class:`Application` from the result.

        This is the entry point ``main.py`` calls. It exists as a
        separate constructor path (rather than folding
        :func:`~uadas_core.core.bootstrap.bootstrap` into ``__init__``) so
        that tests can construct an ``Application`` from a
        hand-built ``BootstrapContext`` — pointed at a temporary
        config file and log directory — without needing to run the
        real bootstrap sequence against the project's actual
        ``config/config.yaml``.
        """
        context = bootstrap()
        return cls(context)

    @property
    def config(self):
        """Return the application's loaded configuration.

        Typed as a property rather than a plain attribute so that
        milestone 1b's ``MainWindow`` (and later, other components)
        can be constructed with ``application.config`` without every
        caller needing to reach into ``self._context.config``
        directly. Return type is intentionally left to inference here
        rather than imported and annotated explicitly, to avoid this
        file importing ``AppConfig`` for a type-hint-only purpose it
        does not otherwise need; this can be tightened once mypy or a
        similar checker is wired into the project's tooling.
        """
        return self._context.config

    def run(self) -> int:
        """Run the application and return a process exit code.

        Constructs the ``QApplication`` (exactly one per process —
        this is the only place in the codebase that does so), applies
        the theme currently in ``config.yaml`` via
        :class:`~src.ui.theme_manager.ThemeManager`, builds and shows
        :class:`~src.ui.main_window.MainWindow`, and enters the Qt
        event loop. The event loop's own return value (Qt's
        convention: ``0`` for a normal exit) becomes this method's
        return value in turn.

        Returns:
            Process exit code, as returned by ``QApplication.exec()``.
        """
        _logger.info(
            "%s starting (version %s).",
            APP_NAME,
            APP_VERSION,
        )

        # Force software OpenGL rendering for QtWebEngine before QApplication
        # is constructed. Fixes a real, observed bug: QWebEngineView renders
        # as a persistently blank white pane on some Windows GPU/driver
        # combinations when hardware compositing silently fails to initialize
        # — confirmed on a real machine where the identical HTML rendered
        # correctly in a normal browser but stayed blank inside the app,
        # isolating the failure to Qt's GPU compositing path specifically.
        from PySide6.QtCore import QCoreApplication, Qt

        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_UseSoftwareOpenGL)
        QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)

        qt_application = QApplication(sys.argv)

        theme_manager = ThemeManager(qt_application)
        # Milestone 28: seed the accessibility settings before the first
        # apply_theme() call below, not after -- both setters only
        # re-apply the theme if one is already current (see their own
        # docstrings), and setting them first means the very first
        # stylesheet compiled is already correct instead of compiling once
        # with theme-default sizes and immediately recompiling.
        theme_manager.set_base_font_size(
            self._context.config.accessibility_base_font_size
        )
        theme_manager.set_reduced_motion(
            self._context.config.accessibility_reduced_motion
        )
        theme_manager.apply_theme(self._context.config.theme)

        main_window = MainWindow(self._context)
        main_window.attach_theme_manager(theme_manager)

        # Milestone 29: window.width/height, described in config since milestone 1a and never
        # read anywhere before this -- MainWindow.__init__ already resized itself to the
        # hard-coded DEFAULT_WINDOW_WIDTH/HEIGHT constants by this point; this simply resizes
        # again to whatever config.yaml actually says, which is a real, if inelegant, way to
        # wire it without adding to MainWindow's own tests.ui.test_module_size budget (it was
        # already at that budget's ceiling before this milestone touched it at all). The
        # window is not visible yet (show() is still below), so the intermediate default size
        # is never actually seen on screen.
        main_window.resize(
            self._context.config.window_width, self._context.config.window_height
        )
        main_window.show()

        # Milestone 29: autosave.enabled/interval_minutes, described in config since
        # milestone 1a and never implemented before this -- see src/ui/autosave_timer.py's own
        # docstring for the full reasoning. Parented to main_window so it is torn down with the
        # window rather than needing an explicit stop() call in closeEvent.
        #
        # cast(), not a bare resolve() call: DependencyContainer.resolve() returns `object`
        # (the same "resolve() -> object gap" src/ui/main_window.py's own construction lives
        # with -- see .github/workflows/ci.yml's mypy-scope comment) -- every resolve() call
        # here is registered with exactly this type in uadas_core/core/bootstrap.py, so a cast is a
        # documented, narrow correction, not a blind type: ignore.
        settings_service = cast(
            SettingsService, self._context.container.resolve(SettingsService)
        )
        AutosaveTimer(
            cast(ProjectService, self._context.container.resolve(ProjectService)),
            cast(WorkspaceService, self._context.container.resolve(WorkspaceService)),
            settings_service,
            parent=main_window,
        )

        # Milestone 29: the first-run tour -- appears once, backed by the real
        # ui.first_run_completed config key (see src/ui/dialogs/first_run_tour_dialog.py's own
        # docstring for why the dialog itself holds no notion of "have I been shown before").
        # Marked completed and saved to disk regardless of how the dialog was dismissed
        # (exec() returns for any close path, not only its own "Get Started" button), so it
        # genuinely never reappears once shown.
        if not self._context.config.ui_first_run_completed:
            FirstRunTourDialog(main_window).exec()
            settings_service.set("ui", "first_run_completed", value=True)
            settings_service.save()

        _logger.info("Main window shown; entering Qt event loop.")
        return qt_application.exec()
