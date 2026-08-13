# File: src/ui/theme_manager.py
"""Loads and applies QSS theme stylesheets to the running application.

:class:`ThemeManager` reads a theme's ``.qss`` file from
``resources/styles/`` and applies it via ``QApplication.setStyleSheet``,
which cascades to every widget in the application rather than requiring
each widget to apply its own styling. Switching themes at runtime is
supported: calling :meth:`apply_theme` again with a different theme
name re-reads that theme's file and re-applies it, and every widget
already on screen picks up the new stylesheet immediately — this is
standard Qt behavior for ``setStyleSheet`` on the application object,
not something this class needs to implement itself.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication

from src.core.constants import AVAILABLE_THEMES, PROJECT_ROOT
from src.core.exceptions import ServiceError
from src.core.logger import get_logger

_logger = get_logger(__name__)

_STYLES_DIR = PROJECT_ROOT / "resources" / "styles"


class ThemeManager:
    """Applies named QSS themes to a running :class:`QApplication`.

    Args:
        application: The ``QApplication`` instance themes are applied
            to. Stored by reference — this class does not construct
            its own ``QApplication``, since exactly one must exist per
            process and :mod:`src.core.app` (extended in this
            milestone) is responsible for constructing it.
        styles_dir: Directory containing ``<theme_name>.qss`` files.
            Defaults to the project's standard styles location;
            overridable primarily for tests that want to supply a
            temporary directory with fake theme files.
    """

    def __init__(
        self,
        application: QApplication,
        styles_dir: Path = _STYLES_DIR,
    ) -> None:
        self._application = application
        self._styles_dir = styles_dir
        self._current_theme: str | None = None

    def apply_theme(self, theme_name: str) -> None:
        """Load ``theme_name``'s QSS file and apply it to the application.

        Args:
            theme_name: One of :data:`~src.core.constants.AVAILABLE_THEMES`
                (currently ``"dark"`` or ``"light"``).

        Raises:
            ServiceError: If ``theme_name`` is not a recognized theme,
                or if its QSS file cannot be read.
        """
        if theme_name not in AVAILABLE_THEMES:
            raise ServiceError(
                f"Unknown theme: '{theme_name}'. Available themes: "
                f"{AVAILABLE_THEMES}."
            )

        qss_path = self._styles_dir / f"{theme_name}.qss"
        if not qss_path.exists():
            raise ServiceError(f"Theme file not found: {qss_path}")

        try:
            stylesheet = qss_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ServiceError(f"Failed to read theme file {qss_path}: {exc}") from exc

        self._application.setStyleSheet(stylesheet)
        self._current_theme = theme_name
        _logger.info("Applied theme: %s", theme_name)

    def current_theme(self) -> str | None:
        """Return the name of the currently applied theme, or ``None``.

        ``None`` only if :meth:`apply_theme` has never been called on
        this instance — there is no meaningful Qt-level default this
        class should assume, so it takes no theme at construction time
        and requires an explicit first call.
        """
        return self._current_theme
