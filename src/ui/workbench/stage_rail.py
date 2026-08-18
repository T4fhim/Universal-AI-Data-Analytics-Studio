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
    enum member, which breaks any code that then calls ``.value`` on it. ``PipelineStage(raw)``
    handles both cases uniformly: called with a plain string it looks up the matching member;
    called with an already-correct :class:`PipelineStage` member it returns that same member
    unchanged (``Enum.__call__`` on an existing member is a no-op lookup, not an error).
    """
    return PipelineStage(raw)


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
