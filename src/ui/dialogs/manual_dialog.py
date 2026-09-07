# File: src/ui/dialogs/manual_dialog.py
"""The window F1 opens: a non-modal viewer for one compiled manual page at a time.

**``QTextBrowser``, not ``QWebEngineView``.** Qt Assistant itself (Qt's own bundled
documentation viewer) uses ``QTextBrowser`` for exactly this job. It is a native, fully
accessible widget with internal anchor/link navigation and ``QTextDocument`` search built in --
no Chromium process, no accessibility gap of the kind :class:`~src.ui.widgets.chart_view.
ChartView`'s ``QWebEngineView`` usage has to work around (see that module's own docstring), and
no per-instance startup cost worth paying for what is, in the end, static prose.

**Non-modal, and constructed once per window, not once per F1 press.** A modal manual would
block interacting with the rest of the application while reading it -- exactly backwards for
reference material meant to be consulted *while* working. :class:`~src.ui.controllers.
help_controller.HelpController` keeps one instance alive across the whole session and calls
:meth:`show_anchor` again on every subsequent F1 press, the same "lazily construct once, reuse"
shape :class:`~src.ui.controllers.assistant_controller.AssistantController` already uses for
:class:`~uadas_core.ai.assistant_service.AssistantService`.

**Cross-reference links navigate in place.** Every manual page links to related pages by real,
relative Markdown file path (``[Clean](../pipeline/clean.md)``) rather than a second, parallel
anchor-only link syntax, so the same files are equally readable as plain Markdown in an editor,
on GitHub, or through this dialog. Clicking one resolves the target file back to whichever
anchor answers it (:meth:`~src.ui.help.manual_index.ManualIndex.resolve_path`) and re-renders in
place -- ``QTextBrowser``'s own link-following is disabled (``setOpenLinks(False)``) so a
missing or external link fails silently rather than ``QTextBrowser`` attempting (and failing) to
load a bare relative path as if it were a file on disk relative to the process's working
directory.
"""

from __future__ import annotations

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from src.ui.a11y.accessible import describe
from src.ui.help.manual_index import ManualIndex
from src.ui.help.manual_renderer import ManualRenderer
from uadas_core.core.exceptions import ServiceError
from uadas_core.core.logger import get_logger

_logger = get_logger(__name__)

_FALLBACK_ANCHOR = "index"


class ManualDialog(QDialog):
    """Shows one compiled manual page, with in-place navigation between cross-referenced pages."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setMinimumSize(560, 480)

        layout = QVBoxLayout(self)

        self._browser = QTextBrowser(self)
        self._browser.setOpenLinks(False)
        self._browser.anchorClicked.connect(self._on_link_clicked)
        describe(
            self._browser,
            name="Manual content",
            description="The in-app manual. Links navigate to related sections in place.",
        )
        layout.addWidget(self._browser)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close)
        layout.addWidget(close_button)

        self._current_anchor: str | None = None
        _logger.debug("Manual dialog constructed.")

    def show_anchor(self, anchor: str) -> None:
        """Render and display ``anchor``, falling back to the manual's own index page.

        Args:
            anchor: A manual anchor -- typically resolved by
                :meth:`~src.ui.controllers.help_controller.HelpController.show_help_for_focus`.
                An anchor that does not resolve (should not happen for any real
                ``help_anchor`` in the codebase -- see ``tests/ui/help/test_manual_anti_rot.py``
                -- but is not impossible for a hand-typed or stale one) falls back to
                ``"index"`` rather than showing an empty or broken dialog.
        """
        try:
            page = ManualRenderer.render(anchor)
        except ServiceError:
            _logger.warning(
                "Manual anchor %r does not resolve; falling back to %r.",
                anchor,
                _FALLBACK_ANCHOR,
            )
            page = ManualRenderer.render(_FALLBACK_ANCHOR)

        self._current_anchor = page.anchor
        self.setWindowTitle(f"Manual: {page.title}")
        self._browser.setHtml(page.html)

    def _on_link_clicked(self, url: QUrl) -> None:
        if url.scheme() not in ("", "file") or self._current_anchor is None:
            return  # an external link, or nothing shown yet -- nothing to navigate from
        current_page = ManualIndex.resolve(self._current_anchor)
        target_path = (current_page.path.parent / url.path()).resolve()
        anchor = ManualIndex.resolve_path(target_path)
        if anchor is None:
            _logger.warning(
                "Manual link to %s does not resolve to a known page.", target_path
            )
            return
        self.show_anchor(anchor)
