# File: src/ui/widgets/guidance_panel.py
"""Renders :class:`~src.services.guidance_service.GuidanceService`'s ranked suggestions.

Embedded once per :class:`~src.ui.workbench.stage_page.StagePage` (see that class's own
docstring for where, in its guidance-card zone) rather than as a single dock shared across
the whole workbench -- a suggestion is most useful exactly where a user already is, next to
the stage-specific guidance text :class:`StagePage` already shows, not in a separate panel
they have to look away to check. :meth:`Workbench.all_pages` is what
:mod:`src.ui.main_window` iterates to push the same ranked list into every page's panel --
see that method's own docstring.

**A real, stateless display widget, not a service consumer.** Like every other widget this
overhaul built (``StageRail``, ``ResultCard``), :class:`GuidancePanel` holds no
:class:`~src.services.guidance_service.GuidanceService` reference of its own --
:meth:`set_suggestions` is called from outside with an already-computed
``list[Suggestion]``, and activating a suggestion only ever emits
:attr:`suggestion_activated` with the suggestion's plain ``action_id`` string.
:mod:`src.ui.main_window` is the one place that turns that string back into a real, invokable
``QAction`` (via ``ActionBinder.action_for(action_id).trigger()``), the same "structure here,
behavior wired by the caller" split every other workbench signal in this codebase already
uses.

``QListWidget``, not a hand-rolled layout of one row per suggestion -- same accessibility
rationale :class:`~src.ui.workbench.stage_rail.StageRail`'s own docstring gives for choosing
it over a custom-painted list: item-level accessibility, keyboard navigation, and focus rings
for free on Qt 6's Windows UI Automation backend.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from src.services.guidance_service import Suggestion
from src.ui.a11y.accessible import describe

_ACTION_ID_ROLE = Qt.ItemDataRole.UserRole

# Shown in place of the list when there is nothing to suggest -- e.g. no active dataset, or a
# dataset every deterministic source genuinely has nothing left to say about (very rare in
# practice: GuidanceService.propose_next_stage alone always contributes one candidate for any
# active dataset, but this stays a real, populated placeholder rather than a blank widget
# either way, matching the "illustrated empty states" decision named for milestone 27 -- this
# text-only placeholder predates that milestone's dedicated EmptyState widget and is a
# reasonable candidate for that widget to replace once it exists).
_EMPTY_PLACEHOLDER_TEXT = "No suggestions right now."


class GuidancePanel(QWidget):
    """A ranked, activatable list of :class:`~src.services.guidance_service.Suggestion`.

    Signals:
        suggestion_activated: Emitted with the activated suggestion's ``action_id`` (a plain
            string -- see this module's own docstring on why) whenever the user activates
            (double-click, or Enter/Space while focused) an entry.
    """

    suggestion_activated = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("guidancePanel")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget(self)
        self._list.setObjectName("guidanceSuggestionList")
        describe(
            self._list,
            name="Suggested next steps",
            description=(
                "Ranked suggestions for what to do next with this dataset, based on the "
                "guided pipeline, chart recommendations, and a data-quality scan. Activate "
                "an entry to jump to it."
            ),
        )
        layout.addWidget(self._list)

        self._list.itemActivated.connect(self._on_item_activated)
        self._list.itemClicked.connect(self._on_item_activated)

        self._show_empty_placeholder()

    def set_suggestions(self, suggestions: list[Suggestion]) -> None:
        """Replace the displayed list with ``suggestions``, already ranked by the caller.

        Rebuilds the list from scratch each time rather than diffing against the previous
        contents -- matching every other "small, session-scoped list" rebuild in this
        codebase (``ApplicationMenuBar.update_recent_projects_menu``,
        ``DockManager.refresh_dataset_list``), for the same reason: the list is expected to
        stay short (``GuidanceService.get_suggestions`` is typically called with a
        ``max_suggestions`` cap by its caller), and a full rebuild is simpler and less
        error-prone than incremental item-state maintenance at this size.
        """
        self._list.clear()
        if not suggestions:
            self._show_empty_placeholder()
            return

        for suggestion in suggestions:
            item = QListWidgetItem(self._list)
            item.setText(f"{suggestion.title}\n{suggestion.rationale}")
            item.setData(_ACTION_ID_ROLE, suggestion.action_id)
            item.setToolTip(suggestion.rationale)
            # AccessibleTextRole mirrors title + rationale explicitly -- a
            # screen reader reading this item should hear the same "what
            # and why" a sighted user reads across the two lines above,
            # not just the title (matching this project's "never
            # color-only, never visual-only" accessibility rule for
            # anything that carries real information).
            item.setData(
                Qt.ItemDataRole.AccessibleTextRole,
                f"{suggestion.title}. {suggestion.rationale}",
            )

    def suggestion_count(self) -> int:
        """Return how many real suggestions are currently displayed (0 for the empty placeholder)."""
        if self._list.count() == 1:
            item = self._list.item(0)
            if item is not None and item.data(_ACTION_ID_ROLE) is None:
                return 0
        return self._list.count()

    def _show_empty_placeholder(self) -> None:
        placeholder = QListWidgetItem(_EMPTY_PLACEHOLDER_TEXT, self._list)
        placeholder.setFlags(placeholder.flags() & ~Qt.ItemFlag.ItemIsSelectable)
        # No action_id -- _on_item_activated below checks for this and does
        # nothing, so an accidental double-click on the placeholder itself
        # can never emit a bogus, unresolvable action id.

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        action_id = item.data(_ACTION_ID_ROLE)
        if action_id:
            self.suggestion_activated.emit(action_id)
