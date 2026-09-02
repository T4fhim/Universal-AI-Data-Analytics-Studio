# File: src/ui/workbench/stage_rail.py
"""The pipeline's navigation spine -- every stage, its status, one click to jump to it.

Per the plan's A3: **a ``QListWidget``, not custom-painted.** Qt 6 on Windows exposes
accessibility through the UI Automation backend; a standard ``QListWidget`` gives item-level
accessibility, keyboard navigation (arrow keys, Home/End), and focus rings for free, while a
custom-painted rail would need a hand-written ``QAccessibleInterface`` plugin to reach the same
bar. This is a deliberate rejection of a fancier custom-drawn sidebar in favor of the boring
widget that already works with a screen reader.

Holds no service references (see this package's own docstring on why) -- :meth:`update_state`
is called externally, by :class:`~src.ui.workbench.workbench.Workbench`, with plain data already
computed from :class:`~src.services.analysis_orchestrator_service.AnalysisLog`/``StageProposal``.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QWidget

from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.a11y.accessible import describe

_STAGE_ROLE = Qt.ItemDataRole.UserRole
_STATUS_ROLE = Qt.ItemDataRole.UserRole + 1

# Prefix glyphs for each status -- text, not color-only, so status is legible
# without relying on hue (color-only status would be a WCAG 1.4.1 failure and
# invisible in the rail's own ``QListWidget`` accessible text besides).
_STATUS_PREFIX = {
    "complete": "✓ ",  # check mark
    "proposed": "→ ",  # rightwards arrow
    "pending": "· ",  # middle dot
}


def _label_for(stage: PipelineStage, status: str) -> str:
    return f"{_STATUS_PREFIX[status]}{stage.value.title()}"


def _stage_from_item_data(raw: object) -> PipelineStage:
    """Coerce an item's stored ``UserRole`` value back into a real :class:`PipelineStage`.

    ``PySide6``'s ``QVariant`` round-trip does not reliably preserve a ``str``-subclass
    ``Enum`` object's Python type -- a value stored via ``item.setData(role, PipelineStage.
    UPLOAD)`` can come back out as a plain ``str`` (``"upload"``) rather than the original
    enum member, which breaks any code that then calls ``.value`` on it. Handled explicitly
    rather than via a single ``PipelineStage(raw)`` call: an already-correct member is
    returned unchanged, and anything else is coerced through ``str()`` first. ``PipelineStage``
    became a :class:`~enum.StrEnum` rather than a hand-rolled ``str, Enum`` subclass (ruff's
    UP042), and ``StrEnum.__new__``'s stub is typed to take ``str``, not the ``object`` this
    function receives from Qt -- the explicit ``isinstance``/``str()`` split here satisfies
    that narrower signature instead of relying on ``Enum.__call__``'s runtime-only tolerance
    for an already-correct member, which mypy cannot see through.
    """
    if isinstance(raw, PipelineStage):
        return raw
    return PipelineStage(str(raw))


class StageRail(QListWidget):
    """Lists every :class:`~src.services.analysis_orchestrator_service.PipelineStage` and its status.

    Signals:
        stage_selected: Emitted with the clicked item's
            :class:`~src.services.analysis_orchestrator_service.PipelineStage` whenever the
            user clicks or activates (Enter/Space) a rail entry.
    """

    stage_selected = Signal(object)  # PipelineStage

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("stageRail")
        self.setFixedWidth(180)
        describe(
            self,
            name="Pipeline stage rail",
            description=(
                "Lists every guided-pipeline stage and whether it is complete, "
                "proposed next, or not yet reached."
            ),
        )

        for stage in PipelineStage:
            item = QListWidgetItem(_label_for(stage, "pending"), self)
            item.setData(_STAGE_ROLE, stage)
            item.setData(_STATUS_ROLE, "pending")

        self.itemActivated.connect(self._on_item_activated)
        self.itemClicked.connect(self._on_item_activated)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self.stage_selected.emit(_stage_from_item_data(item.data(_STAGE_ROLE)))

    def update_state(
        self, completed: set[PipelineStage], proposed: PipelineStage | None
    ) -> None:
        """Recompute every item's status text from real orchestrator state.

        Args:
            completed: Stages considered done -- ordinarily
                :meth:`~src.services.analysis_orchestrator_service.AnalysisLog.completed_stages`,
                with ``PipelineStage.UPLOAD`` added by the caller when a dataset is active
                (UPLOAD is never logged as a stage run -- see
                :mod:`~src.services.analysis_orchestrator_service`'s own
                ``_AUTO_PROPOSED_STAGES`` comment for why -- so "an active dataset exists" is
                what "UPLOAD complete" actually means, and this class has no dataset
                reference of its own to derive that from).
            proposed: The stage :class:`~src.services.analysis_orchestrator_service.
                AnalysisOrchestratorService.propose_next_stage` currently recommends, or
                ``None`` if nothing is proposed (no active dataset).
        """
        for index in range(self.count()):
            item = self.item(index)
            stage = _stage_from_item_data(item.data(_STAGE_ROLE))
            if stage in completed:
                status = "complete"
            elif stage == proposed:
                status = "proposed"
            else:
                status = "pending"
            item.setText(_label_for(stage, status))
            item.setData(_STATUS_ROLE, status)
            # UI-friendliness pass (unit 2): bold the proposed stage so it reads as
            # "go here next" at a glance, not only via the one-glyph "→ " prefix in
            # _STATUS_PREFIX above -- easy to miss when scanning quickly. Reapplied
            # (and un-set for every other item) on every call rather than only when an
            # item first becomes proposed, since "proposed" moves between calls as the
            # pipeline advances and a stale bold item would otherwise linger. Font
            # weight, not color, for the same reason _STATUS_PREFIX itself is text
            # (WCAG 1.4.1) and to avoid making this stateless widget theme-aware just
            # for one emphasis cue -- mirrors ResultCard._title_label's own
            # font.setBold(...) pattern for emphasis elsewhere in this codebase.
            font = item.font()
            font.setBold(status == "proposed")
            item.setFont(font)

    def set_current_stage(self, stage: PipelineStage | None) -> None:
        """Sync this rail's own current-item cursor to whichever stage is actually shown.

        Unit 6 (UI-friendliness pass, stage-rail keyboard navigation): a direct click on a
        rail item already makes Qt set that item current (and selected) for free -- what was
        missing is every *programmatic* navigation path (:meth:`~src.ui.workbench.workbench.
        Workbench.show_stage`, :meth:`~src.ui.workbench.workbench.Workbench.show_welcome`,
        and the auto-navigate-on-dataset-open branch in :meth:`~src.ui.workbench.workbench.
        Workbench.update_pipeline_state`) left the rail's current-item cursor exactly where a
        user's last rail click (or nothing at all, on first launch) put it. Since arrow-key
        navigation starts from whatever item is currently "current" -- not from whichever
        page is actually visible -- a keyboard user tabbing into the rail after any
        non-rail-driven navigation would have their first Up/Down press jump from a stale,
        invisible starting point instead of the stage they are actually looking at.

        Args:
            stage: The stage to mark current, or ``None`` to clear the current item entirely
                (the welcome page has no corresponding rail item -- see ``UPLOAD``'s own
                "reachable but not yet interactive" note on :meth:`Workbench._on_stage_selected`).
        """
        if stage is None:
            # QListWidget.setCurrentItem(None) is valid, documented Qt behavior (clears the
            # current item) -- the PySide6 stubs just don't declare the None-accepting overload.
            self.setCurrentItem(None)  # type: ignore[call-overload]
            return
        for index in range(self.count()):
            item = self.item(index)
            if _stage_from_item_data(item.data(_STAGE_ROLE)) == stage:
                self.setCurrentItem(item)
                return

    def status_for(self, stage: PipelineStage) -> str | None:
        """Return the currently displayed status for ``stage`` -- ``"complete"``, ``"proposed"``,
        ``"pending"``, or ``None`` if ``stage`` is not in the rail (should not happen; every
        :class:`~src.services.analysis_orchestrator_service.PipelineStage` value gets one item
        at construction).

        Exists mainly for tests to assert the rail's real state without parsing the display
        label's glyph prefix back out.
        """
        for index in range(self.count()):
            item = self.item(index)
            if _stage_from_item_data(item.data(_STAGE_ROLE)) == stage:
                return item.data(_STATUS_ROLE)
        return None
