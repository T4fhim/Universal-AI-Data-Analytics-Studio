# File: src/core/app.py
"""Application entry class.

:class:`Application` wraps a :class:`~src.core.bootstrap.BootstrapContext`
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

from PySide6.QtWidgets import QApplication

from src.core.bootstrap import BootstrapContext, bootstrap
from src.core.constants import APP_NAME, APP_VERSION
from src.core.logger import get_logger
from src.ui.main_window import MainWindow
from src.ui.theme_manager import ThemeManager

_logger = get_logger(__name__)


class Application:
    """Top-level application object, constructed from a bootstrap context.

    Args:
        context: The result of a successful
            :func:`~src.core.bootstrap.bootstrap` call. ``Application``
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
        :func:`~src.core.bootstrap.bootstrap` into ``__init__``) so
        that tests can construct an ``Application`` from a
        hand-built ``BootstrapContext`` — pointed at a temporary
        config file and log directory — without needing to run the
        real bootstrap sequence against the project's actual
        ``config/config.yaml``.
        """
        context = bootstrap()
        return cls(context)

    @property
    def config(self):  # noqa: ANN201 — return type is AppConfig; see note below
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
        theme_manager.apply_theme(self._context.config.theme)

        main_window = MainWindow(self._context)
        main_window.attach_theme_manager(theme_manager)
        main_window.show()

        _logger.info("Main window shown; entering Qt event loop.")
        return qt_application.exec()
