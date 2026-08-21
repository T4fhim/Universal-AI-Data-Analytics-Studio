# File: src/analysis/explanation.py
"""The shared shape the AI's interpretation layer fills in for a computed result.

Milestone 8: :class:`Explanation` is a **data shape, not new statistics**.
Every deterministic analysis/forecasting function in this package (and
:mod:`src.forecasting`) already computes real numbers — correlation
coefficients, p-values, forecast intervals. This dataclass is what the
AI layer (:mod:`src.ai.assistant_service`) fills in *about* an
already-computed result, and what UI result panels (milestone 10)
render — keeping "AI interprets, doesn't invent numbers" (see
CLAUDE.md's own framing of this project's AI layer) structurally true:
nothing in this module computes anything, it only describes.

Lives in :mod:`src.analysis` rather than :mod:`src.ai` because its
natural neighbors are :mod:`~src.analysis.dataset_profile` and
:mod:`~src.analysis.column_profile` — every later milestone that
attaches an explanation to a result (the orchestrator's EXPLAIN stage
in milestone 9, forecast model comparison, UI result rendering) reaches
for this the same way it reaches for those, not the way it reaches for
:mod:`~src.ai.tool_registry`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Explanation:
    """A structured, plain-language account of one computed result.

    Every field is free text (or a list of free text) the AI layer
    produces — nothing here is derived by this module itself. Fields
    are all independently optional in practice (default to empty
    string/list) since not every result has, for example, a meaningful
    "alternative approaches" to report — a single mean or row count
    has no real alternative method worth naming, while a forecast
    model choice (milestone 9's Automatic Model Competition) very much
    does.

    Attributes:
        what: Plain statement of what the result is/shows.
        why_it_matters: Why this result is relevant to the user's
            actual question or decision, not just what it says.
        how_calculated: Brief account of the method used — named
            clearly enough that a more technical user could look it up
            (e.g. "Pearson correlation coefficient"), without
            necessarily reproducing the full formula.
        confidence_or_uncertainty: How much to trust this result — a
            p-value's meaning, a forecast interval's width, or plainly
            "this is a small sample; treat with caution" when no
            formal uncertainty measure applies.
        assumptions: Conditions the method assumes hold (e.g.
            normality for a t-test) — not necessarily verified, just
            named, so a more advanced user can judge for themselves
            whether they're satisfied.
        limitations: What this result does *not* show or cannot be
            used to conclude (the classic correlation-is-not-causation
            class of caveat, and anything data-specific like "outliers
            were not removed").
        alternative_approaches: Other methods that could have answered
            a similar question, and why this one was used instead (or
            wasn't, if genuinely no reasonable alternative existed —
            in which case this stays empty rather than padded out).
    """

    what: str = ""
    why_it_matters: str = ""
    how_calculated: str = ""
    confidence_or_uncertainty: str = ""
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    alternative_approaches: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a plain, JSON-friendly dict — matches this project's other analysis result shapes.

        Used when an :class:`Explanation` needs to travel through a
        tool result (:mod:`src.ai.tool_registry` handlers return
        JSON-friendly dicts, per that module's own convention) or be
        persisted as part of a per-dataset ``AnalysisLog`` entry
        (milestone 9's Reproducible Analysis).
        """
        return {
            "what": self.what,
            "why_it_matters": self.why_it_matters,
            "how_calculated": self.how_calculated,
            "confidence_or_uncertainty": self.confidence_or_uncertainty,
            "assumptions": list(self.assumptions),
            "limitations": list(self.limitations),
            "alternative_approaches": list(self.alternative_approaches),
        }
