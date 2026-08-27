# File: src/ui/widgets/empty_state.py
"""``EmptyState``: illustration + heading + one actionable next step, replacing silent
"(No X)" placeholder text throughout ``src/ui/`` (milestone 27).

Before this milestone, "nothing here yet" was rendered as a single bare string --
``"(No project open)"``, ``"(No datasets loaded)"``, ``"(No recent projects)"``,
``"(No plugins found in the configured search paths)"`` -- scattered across
``dock_manager.py``, ``menu_bar.py``, and ``settings_dialog.py`` with no shared shape and no
next step for the user reading it. This widget is the one place that shape now lives:
a themed illustration (see :mod:`~src.ui.theme.icon_provider` for the ``currentColor``
substitution trick this module reuses directly, since ``IconProvider`` itself only resolves
``resources/icons/*.svg`` non-recursively and the illustrations live in a dedicated
``resources/icons/illustrations/`` subdirectory -- see that directory's own ``NOTICE.md``),
a bold heading, an explanatory message, and an optional action button.

**No live theme wiring, by design.** Unlike :class:`~src.ui.theme.icon_provider.IconProvider`,
this module does not hold a live :class:`~src.ui.theme.tokens.ThemeTokens` reference that
updates on every theme change -- plumbing a theme-aware provider into every current call site
(``DockManager``, ``ApplicationMenuBar``, ``SettingsDialog``, every ``StagePage`` subclass)
would be a wider change than this milestone's actual acceptance criteria ask for, and the
illustration is decorative supporting art, not the primary information-bearing content (the
heading and message text already flow through the QSS ``#emptyStateHeading``/
``#emptyStateMessage`` selectors added in ``base.qss.template``, which *do* re-theme live like
every other themed label in this codebase). ``DARK_TOKENS.text_secondary`` is used as a fixed,
reasonably-visible-on-either-theme stroke colour -- the same "safe, visible-either-way
placeholder" reasoning :class:`~src.ui.main_window.MainWindow`'s own docstring already gives
for using ``DARK_TOKENS`` before a real theme is attached. Flagged here as a follow-up worth
revisiting if illustration colour fidelity ever becomes a real complaint, not acted on
unilaterally now.

**Illustrations are described, not silenced.** Per this milestone's own a11y-audit criterion,
the illustration label is *not* hidden from assistive technology the way a purely decorative
image normally would be (WCAG's own "empty alt for decorative images" guidance) -- this
project's :func:`~src.ui.a11y.accessible.describe` convention is used instead, giving every
illustration a real accessible description, because a screen-reader user arriving at an empty
state benefits from knowing *what* the illustration depicts (reinforcing, not just decorating)
at least as much as a sighted user does.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from src.core.constants import PROJECT_ROOT
from src.core.logger import get_logger
from src.ui.a11y.accessible import describe
from src.ui.theme.tokens import DARK_TOKENS

_logger = get_logger(__name__)

# Mirrors src/ui/theme/icon_provider.py's own ICONS_DIR constant, one directory deeper -- see
# this module's own docstring for why illustrations are not resolved through IconProvider.
ILLUSTRATIONS_DIR: Path = PROJECT_ROOT / "resources" / "icons" / "illustrations"

_ILLUSTRATION_SIZE = 64
_COLOR_PLACEHOLDER = "currentColor"


def render_illustration(
    name: str, color: str, size: int = _ILLUSTRATION_SIZE
) -> QPixmap:
    """Rasterise ``resources/icons/illustrations/<name>.svg`` with strokes recoloured to ``color``.

    A near-duplicate of :meth:`~src.ui.theme.icon_provider.IconProvider._render`, deliberately
    not shared via import: that method is private to ``IconProvider`` and this module's own
    docstring already explains why illustrations are not resolved through that class at all.
    Returns a transparent, empty :class:`QPixmap` (not a placeholder glyph) when the file is
    missing -- an absent illustration must not crash the caller, matching
    ``IconProvider.icon``'s own "missing icon degrades, never crashes" rule -- logged once.
    """
    pixmap = QPixmap(QSize(size, size))
    pixmap.fill(Qt.GlobalColor.transparent)

    svg_path = ILLUSTRATIONS_DIR / f"{name}.svg"
    if not svg_path.exists():
        _logger.warning(
            "Illustration '%s' not found in %s; showing a blank illustration area.",
            name,
            ILLUSTRATIONS_DIR,
        )
        return pixmap

    markup = svg_path.read_text(encoding="utf-8").replace(_COLOR_PLACEHOLDER, color)
    renderer = QSvgRenderer(markup.encode("utf-8"))
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        # Same QPainter/QPixmap lifetime hazard IconProvider._render's own comment documents.
        painter.end()
    return pixmap


class EmptyState(QWidget):
    """Illustration + heading + message + one optional actionable next step.

    Args:
        heading: Short, bold statement of what is missing -- "No datasets loaded", not
            "(No datasets loaded)". The parenthesised, lowercase style this widget replaces
            read as a debug artifact rather than a real UI message; a real heading does not.
        message: One sentence naming the actionable next step -- what the user should *do*
            about the empty state, not just a restatement that it is empty.
        illustration: Filename stem under ``resources/icons/illustrations/`` (no extension).
        illustration_description: The illustration's accessible description (see this module's
            own docstring on why illustrations are described, not silenced). Defaults to a
            generic description built from ``heading`` when not given.
        illustration_size: Logical pixel side length the illustration is rendered at. Defaults
            to a dock/page-sized illustration; a compact host (e.g. a ``QMenu`` entry, via
            :class:`~src.ui.menu_bar.ApplicationMenuBar`'s "Open Recent" placeholder) passes a
            smaller value so the illustration does not dominate a menu row.
        action_text: Label for an optional action button. When given, :attr:`action_button` is
            constructed and :attr:`action_triggered` fires on click; when omitted, no button is
            shown and :attr:`action_button` is ``None`` -- an empty state whose only actionable
            step is "look at the message" (e.g. a read-only console dock) is legitimate and
            should not be forced to fabricate a button.
        parent: Optional parent widget.

    Signals:
        action_triggered: Emitted when :attr:`action_button` is clicked. Carries no payload --
            same "plain signal, caller resolves what to do" split
            :class:`~src.ui.widgets.guidance_panel.GuidancePanel.suggestion_activated` already
            uses, since what "the" action means is entirely caller-specific (open a file dialog,
            switch a workbench stage, focus a search box).
    """

    action_triggered = Signal()

    def __init__(
        self,
        *,
        heading: str,
        message: str,
        illustration: str = "empty-box",
        illustration_description: str | None = None,
        illustration_size: int = _ILLUSTRATION_SIZE,
        action_text: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("emptyState")

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)

        self._illustration_label = QLabel(self)
        self._illustration_label.setObjectName("emptyStateIllustration")
        self._illustration_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._illustration_label.setPixmap(
            render_illustration(
                illustration, DARK_TOKENS.text_secondary, illustration_size
            )
        )
        describe(
            self._illustration_label,
            name=self.tr("{0} illustration").format(heading),
            description=illustration_description
            or self.tr("Decorative illustration accompanying: {0}").format(heading),
            focusable=False,
        )
        layout.addWidget(self._illustration_label)

        self._heading_label = QLabel(heading, self)
        self._heading_label.setObjectName("emptyStateHeading")
        self._heading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._heading_label.setWordWrap(True)
        layout.addWidget(self._heading_label)

        self._message_label = QLabel(message, self)
        self._message_label.setObjectName("emptyStateMessage")
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._message_label.setWordWrap(True)
        layout.addWidget(self._message_label)

        self.action_button: QPushButton | None = None
        if action_text:
            self.action_button = QPushButton(action_text, self)
            self.action_button.setObjectName("emptyStateActionButton")
            describe(self.action_button, name=action_text)
            self.action_button.clicked.connect(self.action_triggered)
            layout.addWidget(self.action_button)

        describe(self, name=heading, description=message, focusable=False)

    def set_message(self, message: str) -> None:
        """Replace the message text -- for a caller that reuses one instance across refreshes."""
        self._message_label.setText(message)
        describe(
            self, name=self._heading_label.text(), description=message, focusable=False
        )
