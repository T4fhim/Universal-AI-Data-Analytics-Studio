# File: tests/analysis/test_explanation.py
"""Round-trip proof for :meth:`uadas_core.analysis.explanation.Explanation.from_dict`.

Phase 1.7 adds ``from_dict`` so a serialized :class:`Explanation` carried inside
an ``AnalysisLogEntry`` or a :mod:`uadas_core.provenance` Recipe step reconstructs
as the real dataclass rather than an opaque dict. These tests pin the inverse
relationship with :meth:`Explanation.to_dict` and the tolerance rules (missing
keys fall back to field defaults, unknown keys are ignored) the converters rely
on. Lives under ``tests/analysis/`` rather than the Qt-bound
``tests/ui/results/test_explanation_panel.py`` because it exercises pure
dataclass behaviour with no widget involved.
"""

from __future__ import annotations

from uadas_core.analysis.explanation import Explanation


def test_explanation_round_trips_through_from_dict() -> None:
    e = Explanation(
        what="Revenue rose 12% QoQ",
        why_it_matters="Confirms the pricing change landed",
        how_calculated="Percent change of period totals",
        confidence_or_uncertainty="n=2 periods; directional only",
        assumptions=["periods are comparable length"],
        limitations=["does not isolate pricing from seasonality"],
        alternative_approaches=["fit a trend model over more periods"],
    )
    assert Explanation.from_dict(e.to_dict()) == e


def test_explanation_from_dict_tolerates_missing_keys() -> None:
    assert Explanation.from_dict({"what": "just a mean"}) == Explanation(
        what="just a mean"
    )


def test_explanation_from_dict_ignores_unknown_keys() -> None:
    assert Explanation.from_dict({"what": "x", "legacy": 1}) == Explanation(what="x")
