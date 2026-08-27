# File: src/ui/theme_manager.py
"""Compiles design tokens into QSS and applies the result to the application.

:class:`ThemeManager` no longer reads a per-theme ``.qss`` file. Milestone 15
replaced ``resources/styles/dark.qss`` and ``light.qss`` -- two independently
hand-maintained files with no shared colour vocabulary -- with a single
``base.qss.template`` plus the token sets in :mod:`src.ui.theme.tokens`. This
class is the seam between the two: it resolves a theme name to a
:class:`~src.ui.theme.tokens.ThemeTokens`, hands it to
:func:`~src.ui.theme.qss_compiler.compile_qss`, and applies the result with
``QApplication.setStyleSheet`` so every widget -- including ones constructed
later -- inherits it without any per-widget styling logic.

**Now a ``QObject``.** It was a plain class through milestone 14, which was
adequate while QSS was the only thing a theme affected. It no longer is: the
icons rendered by :class:`~src.ui.theme.icon_provider.IconProvider` are
recoloured from ``text_primary``, and Plotly figures are themed from
``chart_categorical`` (see :mod:`src.ui.theme.plotly_theme`). Neither is
reachable through a stylesheet, so both must be told when the theme changes.
:attr:`theme_changed` is that notification. A plain observer-callback list
would have worked too, and was rejected because every consumer here is
already a ``QObject`` living on the UI thread -- a Qt signal gives automatic
disconnection on destruction, which a hand-rolled callback list would have to
reimplement badly.

**Milestone 28** adds two accessibility axes alongside colour/density:
:meth:`ThemeManager.set_base_font_size` scales
``ThemeTokens.font_size_sm/md/lg`` together (WCAG 1.4.4, text resize) the same
way :meth:`set_density` scales spacing -- re-deriving and re-applying the
current theme -- and :meth:`set_reduced_motion` is a plain, theme-independent
flag consumers read directly (see :attr:`reduced_motion_changed`'s own
comment for why it is not folded into a token at all).
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from src.core.constants import AVAILABLE_THEMES
from src.core.exceptions import ServiceError
from src.core.logger import get_logger
from src.ui.theme.qss_compiler import compile_qss
from src.ui.theme.tokens import TOKENS_BY_NAME, Density, ThemeTokens

_logger = get_logger(__name__)


class ThemeManager(QObject):
    """Applies token-compiled themes to a running :class:`QApplication`.

    Args:
        application: The ``QApplication`` themes are applied to. Stored by
            reference -- this class does not construct one, since exactly one
            must exist per process and :mod:`src.core.app` owns that.
        parent: Optional ``QObject`` parent. Defaults to ``None`` so the
            manager's lifetime is controlled by whoever holds the reference,
            matching how :mod:`src.core.app` keeps it alive for the duration
            of :meth:`~src.core.app.Application.run`.

    Signals:
        theme_changed: Emitted with the new theme name **after** the
            stylesheet has been applied, so a slot that re-renders icons or
            charts observes an already-consistent application.
    """

    theme_changed = Signal(str)
    # Milestone 28: motion is orthogonal to colour/density and has no QSS
    # representation at all (Qt Style Sheets cannot express "skip this
    # animation") -- so unlike font size, which is folded into the applied
    # ThemeTokens, reduced-motion is a plain bool a consumer (currently
    # ApplicationStatusBar's busy indicator) reads directly. Emitted as its
    # own signal, not bundled into theme_changed, since a reduced-motion
    # toggle in Settings does not itself change any colour token and should
    # not force every theme_changed listener (icon re-render, chart
    # re-theme) to run for no reason.
    reduced_motion_changed = Signal(bool)

    def __init__(
        self, application: QApplication, parent: QObject | None = None
    ) -> None:
        super().__init__(parent)
        self._application = application
        self._current_theme: str | None = None
        self._density: Density = Density.COZY
        # None means "use the theme's own default sizes" -- distinct from
        # any real pixel value, so a caller that never touches this setting
        # (every test that constructs a bare ThemeManager, for instance)
        # gets exactly the token set it always did rather than a
        # ThemeTokens.with_base_font_size(13) call that happens to be a
        # no-op today but would silently start doing something the moment
        # the default in src/core/config.py ever changed.
        self._base_font_size: int | None = None
        self._reduced_motion: bool = False

    def apply_theme(self, theme_name: str) -> None:
        """Compile ``theme_name``'s tokens and apply the stylesheet.

        Args:
            theme_name: One of :data:`~src.core.constants.AVAILABLE_THEMES`.

        Raises:
            ServiceError: If ``theme_name`` is unknown, or the template is
                missing, unreadable, or references an undefined token.
        """
        tokens = self._resolve_tokens(theme_name)
        stylesheet = compile_qss(tokens)

        self._application.setStyleSheet(stylesheet)
        self._current_theme = theme_name
        _logger.info(
            "Applied theme '%s' (density %s).", theme_name, self._density.value
        )
        # Emitted last, deliberately: a slot that re-renders icons reads
        # current_tokens(), which must already describe what is on screen.
        self.theme_changed.emit(theme_name)

    def set_density(self, density: Density) -> None:
        """Change spacing scale and re-apply the current theme.

        Separate from :meth:`apply_theme` because density and colour scheme
        are independent axes -- milestone 25 drives density from
        :class:`~src.core.expertise_level.ExpertiseLevel` while leaving the
        user's dark/light choice alone. A no-op when nothing changes, so
        callers may set it unconditionally without forcing a repolish of the
        entire widget tree.
        """
        if density is self._density:
            return
        self._density = density
        if self._current_theme is not None:
            self.apply_theme(self._current_theme)

    def set_base_font_size(self, base_font_size: int) -> None:
        """Change the base font size and re-apply the current theme.

        Args:
            base_font_size: Passed straight to
                :meth:`~src.ui.theme.tokens.ThemeTokens.with_base_font_size`
                -- see that method for how the small/large sizes are
                derived from it.

        Same no-op-when-unchanged shape as :meth:`set_density`, and for the
        same reason: this is driven by a Settings-dialog value that gets
        re-applied on every save/theme-toggle (see
        :meth:`~src.ui.controllers.theme_controller.ThemeController.
        apply_theme_from_settings`), and a real toggle should not force an
        extra stylesheet recompile when the value did not actually change.
        """
        if base_font_size == self._base_font_size:
            return
        self._base_font_size = base_font_size
        if self._current_theme is not None:
            self.apply_theme(self._current_theme)

    def set_reduced_motion(self, enabled: bool) -> None:
        """Set whether motion-sensitive UI should skip animation, and notify listeners.

        Unlike :meth:`set_density`/:meth:`set_base_font_size`, this never
        re-applies the theme -- see :attr:`reduced_motion_changed`'s own
        comment for why it is not folded into ``theme_changed`` at all.
        """
        if enabled == self._reduced_motion:
            return
        self._reduced_motion = enabled
        self.reduced_motion_changed.emit(enabled)

    def reduced_motion(self) -> bool:
        """Return whether reduced motion is currently enabled."""
        return self._reduced_motion

    def current_theme(self) -> str | None:
        """Return the applied theme's name, or ``None`` before the first apply.

        There is no meaningful Qt-level default to assume, so this class
        takes no theme at construction and requires an explicit first call.
        """
        return self._current_theme

    def current_tokens(self) -> ThemeTokens | None:
        """Return the applied theme's tokens, or ``None`` before the first apply.

        This is what :class:`~src.ui.theme.icon_provider.IconProvider` and
        :mod:`src.ui.theme.plotly_theme` read from a
        :attr:`theme_changed` slot -- they need the colour values, not the
        name.
        """
        if self._current_theme is None:
            return None
        return self._resolve_tokens(self._current_theme)

    def _resolve_tokens(self, theme_name: str) -> ThemeTokens:
        """Return the token set for ``theme_name`` at the current density.

        Validates against :data:`~src.core.constants.AVAILABLE_THEMES` first
        rather than just checking ``TOKENS_BY_NAME`` membership, so that a
        theme present in one and absent from the other produces a clear error
        naming the supported set instead of a bare ``KeyError``.
        """
        if theme_name not in AVAILABLE_THEMES:
            raise ServiceError(
                f"Unknown theme: '{theme_name}'. Available themes: {AVAILABLE_THEMES}."
            )
        tokens = TOKENS_BY_NAME.get(theme_name)
        if tokens is None:
            raise ServiceError(
                f"Theme '{theme_name}' is listed in AVAILABLE_THEMES but has "
                f"no token set in src.ui.theme.tokens.TOKENS_BY_NAME."
            )
        tokens = tokens.with_density(self._density)
        if self._base_font_size is not None:
            tokens = tokens.with_base_font_size(self._base_font_size)
        return tokens
