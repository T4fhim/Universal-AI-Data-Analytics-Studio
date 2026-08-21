# File: src/ui/results/explanation_panel.py
"""``ExplanationPanel``: renders an :class:`~src.analysis.explanation.Explanation`'s 7 fields.

A **sibling** of :class:`~src.ui.results.result_card.ResultCard`, not embedded inside it -- per
the plan's A5 section, that separation is "the key to the API-key problem: results render
deterministically with no LLM; explanations are an optional overlay." A caller with no
``Explanation`` (no AI provider configured, or the AI simply has not run yet for this result)
just never constructs or shows this widget; :class:`ResultCard` never needs to know whether one
exists.

Each field is a collapsible :class:`QGroupBox` (Qt's checkable-group-box idiom doubles as a
disclosure triangle here: unchecked hides the body, checked shows it) defaulting open or closed
per the active :class:`~src.core.expertise_level.ExpertiseLevel`, per A5's own spec: "BEGINNER
opens *what* + *why_it_matters*, RESEARCHER opens *assumptions* + *limitations*, ENGINEER opens
*how_calculated*." The three levels A5 does not name explicitly (STUDENT, ANALYST,
DECISION_MAKER) still need a sensible default rather than an unspecified one falling through to
"nothing open" -- :data:`EXPLANATION_DEFAULT_EXPANDED` picks one consistent with each level's own
:data:`~src.core.expertise_level.EXPERTISE_LEVEL_GUIDANCE` phrasing (STUDENT additionally wants
*how_calculated*, since that guidance text says this user "benefits from seeing how a conclusion
was reached"; ANALYST wants *confidence_or_uncertainty* alongside *what*, matching its guidance's
"caveats worth flagging"; DECISION_MAKER mirrors BEGINNER's *what* + *why_it_matters*, matching
its own "leads with the business-relevant conclusion").
"""

from __future__ import annotations

from PySide6.QtWidgets import QGroupBox, QLabel, QVBoxLayout, QWidget

from src.analysis.explanation import Explanation
from src.core.expertise_level import ExpertiseLevel
from src.ui.a11y.accessible import describe

# Field name -> (display title, how to read the field's value as display text).
_FIELDS: tuple[tuple[str, str], ...] = (
    ("what", "What This Shows"),
    ("why_it_matters", "Why It Matters"),
    ("how_calculated", "How It Was Calculated"),
    ("confidence_or_uncertainty", "Confidence / Uncertainty"),
    ("assumptions", "Assumptions"),
    ("limitations", "Limitations"),
    ("alternative_approaches", "Alternative Approaches"),
)

# Per-ExpertiseLevel default-expanded field names -- see this module's own docstring for the
# rationale behind each level's set, including the three A5 does not name explicitly.
EXPLANATION_DEFAULT_EXPANDED: dict[ExpertiseLevel, tuple[str, ...]] = {
    ExpertiseLevel.BEGINNER: ("what", "why_it_matters"),
    ExpertiseLevel.STUDENT: ("what", "why_it_matters", "how_calculated"),
    ExpertiseLevel.ANALYST: ("what", "confidence_or_uncertainty"),
    ExpertiseLevel.RESEARCHER: ("assumptions", "limitations"),
    ExpertiseLevel.ENGINEER: ("how_calculated",),
    ExpertiseLevel.DECISION_MAKER: ("what", "why_it_matters"),
}


class ExplanationPanel(QWidget):
    """Renders an :class:`~src.analysis.explanation.Explanation`, one collapsible section per field.

    Holds no service references, matching :class:`~src.ui.results.result_card.ResultCard`'s own
    shape -- a caller hands this a real :class:`~src.analysis.explanation.Explanation` and an
    :class:`~src.core.expertise_level.ExpertiseLevel` via :meth:`display`; nothing here calls
    :mod:`src.ai` to produce one.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("explanationPanel")
        describe(
            self,
            name="Explanation",
            description="AI-generated interpretation of the result above, when available.",
            focusable=False,
        )

        layout = QVBoxLayout(self)
        self._groups: dict[str, QGroupBox] = {}
        self._labels: dict[str, QLabel] = {}

        for field_name, display_title in _FIELDS:
            group = QGroupBox(display_title, self)
            group.setObjectName(f"explanationField_{field_name}")
            group.setCheckable(True)
            group.setChecked(False)
            group_layout = QVBoxLayout(group)

            body_label = QLabel(group)
            body_label.setWordWrap(True)
            body_label.setVisible(False)
            group_layout.addWidget(body_label)

            # QGroupBox's own checkbox is the disclosure control -- toggling it shows/hides the
            # body label rather than the whole group box, so the title (and its accessible name)
            # stays visible and announced even while collapsed.
            group.toggled.connect(body_label.setVisible)
            describe(group, name=display_title, focusable=True)

            layout.addWidget(group)
            self._groups[field_name] = group
            self._labels[field_name] = body_label

        layout.addStretch(1)

    def display(self, explanation: Explanation, level: ExpertiseLevel) -> None:
        """Populate every field and expand this ``level``'s defaults.

        Args:
            explanation: The result's interpretation.
            level: Which fields open by default -- see :data:`EXPLANATION_DEFAULT_EXPANDED`.
        """
        default_expanded = set(EXPLANATION_DEFAULT_EXPANDED.get(level, ()))
        values = explanation.to_dict()

        for field_name, _display_title in _FIELDS:
            value = values.get(field_name)
            text = "; ".join(value) if isinstance(value, list) else str(value or "")
            self._labels[field_name].setText(text or "(not provided)")
            self._groups[field_name].setChecked(field_name in default_expanded)

    def is_expanded(self, field_name: str) -> bool:
        """Whether ``field_name``'s section is currently expanded -- used by tests to assert
        :data:`EXPLANATION_DEFAULT_EXPANDED` without reaching into ``_groups`` directly.
        """
        return self._groups[field_name].isChecked()
