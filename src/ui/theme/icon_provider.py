# File: src/ui/theme/icon_provider.py
"""Loads SVG icons and recolours them to match the active theme.

The application shipped through milestone 14 with **no icons at all** -- the
toolbar rendered as bare text labels because there was nothing to show. This
module supplies them, and supplies them theme-aware, which a plain
``QIcon(path)`` cannot: a single monochrome SVG drawn in dark-theme grey is
invisible on the light theme's white ground.

The recolouring works because every icon in ``resources/icons/`` is authored
with ``stroke="currentColor"``. ``currentColor`` is a CSS cascade keyword
with no meaning to Qt's SVG renderer -- Qt has no cascade to inherit from --
so this class substitutes the literal token colour into the markup before
handing it to ``QSvgRenderer``. That string substitution is the whole trick,
and it is why icons must use ``currentColor`` rather than a hard-coded hex.

Rendering to ``QPixmap`` rather than using ``QIcon``'s own SVG support is
deliberate: ``QIcon(svg_path)`` would render the file as it is on disk, with
no opportunity to inject a colour, so the theme would be ignored.

Requires a live ``QApplication`` -- ``QPixmap`` cannot be constructed before
one exists -- so this must be built after :meth:`src.core.app.Application.run`
has created it, not at import time.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from src.core.constants import PROJECT_ROOT
from src.core.logger import get_logger
from src.ui.theme.tokens import ThemeTokens

_logger = get_logger(__name__)

ICONS_DIR: Path = PROJECT_ROOT / "resources" / "icons"

# Rendered at 2x and tagged with a device pixel ratio so the same QIcon stays
# sharp on a HiDPI display without asking every call site to know the scale.
_RENDER_SCALE = 2
_DEFAULT_SIZE = 20

# The placeholder every icon file uses for its stroke. See the module
# docstring for why this is a string substitution rather than a Qt feature.
_COLOR_PLACEHOLDER = "currentColor"


class IconProvider(QObject):
    """Caches theme-coloured :class:`QIcon` objects by name.

    Args:
        tokens: The active theme. Replaced wholesale on
            :meth:`set_tokens`, never mutated -- ``ThemeTokens`` is frozen.
        icons_dir: Overridable so tests can point at a fixture directory
            instead of the real icon set.
        parent: Optional ``QObject`` parent.

    Signals:
        icons_changed: Emitted after the cache is cleared for a new theme.
            :class:`~src.ui.actions.action_binder.ActionBinder` connects to
            this to re-``setIcon`` every bound ``QAction``; a ``QIcon``
            already handed to a ``QAction`` is a value copy, so replacing the
            cache does not update widgets on its own.
    """

    icons_changed = Signal()

    def __init__(
        self,
        tokens: ThemeTokens,
        icons_dir: Path = ICONS_DIR,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._tokens = tokens
        self._icons_dir = icons_dir
        self._cache: dict[tuple[str, str, int], QIcon] = {}
        self._missing_warned: set[str] = set()

    def set_tokens(self, tokens: ThemeTokens) -> None:
        """Switch to a new theme, dropping every cached icon.

        A no-op when the theme name is unchanged, so this can be wired
        directly to :attr:`~src.ui.theme_manager.ThemeManager.theme_changed`
        without guarding at the call site.
        """
        if tokens.name == self._tokens.name:
            return
        self._tokens = tokens
        self._cache.clear()
        _logger.debug("Icon cache cleared for theme '%s'.", tokens.name)
        self.icons_changed.emit()

    def icon(
        self, name: str, size: int = _DEFAULT_SIZE, color: str | None = None
    ) -> QIcon:
        """Return the named icon, recoloured for the active theme.

        Args:
            name: Filename stem under ``resources/icons`` -- ``"folder-open"``
                for ``folder-open.svg``.
            size: Logical pixel size. Rendered at twice this internally.
            color: Overrides the theme's ``text_primary``. Used for
                semantic icons -- a danger action's icon passes
                ``tokens.danger`` -- so that colour is not the *only* signal
                (WCAG 1.4.1), merely a reinforcing one.

        Returns:
            The icon, or an empty :class:`QIcon` if the file is absent. A
            missing icon must not crash the UI: the action it belongs to
            still has a text label and remains fully operable, so degrading
            to no icon is strictly better than refusing to build the window.
            The absence is logged once per name.
        """
        resolved_color = color or self._tokens.text_primary
        cache_key = (name, resolved_color, size)
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        svg_path = self._icons_dir / f"{name}.svg"
        if not svg_path.exists():
            if name not in self._missing_warned:
                self._missing_warned.add(name)
                _logger.warning(
                    "Icon '%s' not found in %s; falling back to no icon.",
                    name,
                    self._icons_dir,
                )
            return QIcon()

        icon = QIcon(self._render(svg_path, resolved_color, size))
        self._cache[cache_key] = icon
        return icon

    def available_icons(self) -> list[str]:
        """Return every icon name on disk, sorted.

        Backs a test asserting that every ``icon_name`` referenced by an
        :class:`~src.ui.actions.action_registry.ActionSpec` actually exists,
        so a typo surfaces in the suite rather than as a silently blank
        toolbar button.
        """
        if not self._icons_dir.exists():
            return []
        return sorted(path.stem for path in self._icons_dir.glob("*.svg"))

    def _render(self, svg_path: Path, color: str, size: int) -> QPixmap:
        """Rasterise ``svg_path`` at ``size``, with strokes set to ``color``."""
        markup = svg_path.read_text(encoding="utf-8").replace(
            _COLOR_PLACEHOLDER, color
        )
        renderer = QSvgRenderer(markup.encode("utf-8"))

        pixmap = QPixmap(QSize(size * _RENDER_SCALE, size * _RENDER_SCALE))
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            renderer.render(painter)
        finally:
            # Without this the QPainter may outlive the QPixmap it targets,
            # which Qt reports as "QPaintDevice: Cannot destroy paint device
            # that is being painted" and can crash on some platforms.
            painter.end()
        pixmap.setDevicePixelRatio(float(_RENDER_SCALE))
        return pixmap
