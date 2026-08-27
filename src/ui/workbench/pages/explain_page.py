# File: src/ui/workbench/pages/explain_page.py
"""The EXPLAIN stage's page: shows an :class:`~src.analysis.explanation.Explanation`, when one exists.

Per the plan's A5 section, :class:`~src.ui.results.explanation_panel.ExplanationPanel` is "a
**sibling** of ``ResultCard``, not embedded" -- this page is the plainest possible demonstration
of that split: it holds only an ``ExplanationPanel``, no ``ResultCard`` at all, and its guidance
text says plainly what is and is not available without an AI provider configured.

Populating a real ``Explanation`` requires an AI call (:mod:`src.ai.assistant_service` -- "the
AI's role: interpret, not invent new numbers," per :data:`~src.services.
analysis_orchestrator_service._STAGE_RATIONALE`'s own EXPLAIN entry), which needs a configured
LLM provider to be meaningful. Wiring that live call is explicitly out of scope for this
milestone (see the plan's own M22 section, which lists only the rendering side); this page ships
:meth:`show_explanation` as the real, tested rendering path a future milestone's AI wiring calls
into, and defaults to an empty :class:`~src.analysis.explanation.Explanation` (every field blank)
with guidance text saying so, rather than fabricating placeholder content that would look like a
real interpretation.
"""

from __future__ import annotations

from typing import ClassVar

from PySide6.QtWidgets import QVBoxLayout

from src.analysis.explanation import Explanation
from src.core.expertise_level import ExpertiseLevel
from src.services.analysis_orchestrator_service import PipelineStage
from src.ui.results.explanation_panel import ExplanationPanel
from src.ui.workbench.stage_page import StagePage

_DEFAULT_GUIDANCE = (
    "Every prior stage's result should be interpreted in plain language before reporting. "
    "This panel shows the AI's interpretation once one has been generated; with no AI "
    "provider configured, its fields stay empty -- the rest of the pipeline remains fully "
    "usable either way."
)


class ExplainPage(StagePage):
    """The EXPLAIN stage's workbench page: renders whichever ``Explanation`` it is shown."""

    stage: ClassVar[PipelineStage] = PipelineStage.EXPLAIN
    help_anchor: ClassVar[str] = "pipeline.explain"

    def __init__(self, parent=None) -> None:
        self._expertise_level = ExpertiseLevel.BEGINNER
        super().__init__(parent)

    def _build_form(self, layout: QVBoxLayout) -> None:
        self.explanation_panel = ExplanationPanel(self)
        layout.addWidget(self.explanation_panel)
        self.set_guidance(_DEFAULT_GUIDANCE)
        self.show_explanation(Explanation(), self._expertise_level)

    def set_expertise_level(self, level: ExpertiseLevel) -> None:
        self._expertise_level = level

    def show_explanation(self, explanation: Explanation, level: ExpertiseLevel) -> None:
        """Render ``explanation`` -- called with a real :class:`~src.analysis.explanation.
        Explanation` once an AI provider is wired in, and with an empty one (this page's own
        constructor default) when none is available yet."""
        self.explanation_panel.display(explanation, level)
        self.set_result_text(
            "No AI-generated explanation yet."
            if not explanation.what
            else explanation.what
        )
